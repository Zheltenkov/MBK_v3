"""
MBK assistant — FastAPI backend.

Заменяет Streamlit-приложение. Бизнес-логика переиспользуется как есть из core.py,
llm_agent.py, prompts.py, state.py, lead_delivery.py, observability.py.

Эндпоинты:
  GET  /api/health
  POST /api/session                            — создать сессию (опционально с анкетой)
  GET  /api/session/{id}                       — текущий state (история, факты, фаза)
  GET  /api/session/{id}/stream                — SSE: либо opening (без message), либо turn (с message)
  GET  /api/session/{id}/usage                 — токены и стоимость по этой сессии
  GET  /api/usage/global                       — суммарно по всем активным сессиям
  POST /api/session/{id}/end                   — закрыть сессию (сохранить summary)

SSE-события в /stream:
  event: chunk    — { "text": "..." }                 каждый чанк токенов
  event: bubbles  — { "bubbles": ["...", "..."] }     после стрима — разбивка на пузыри
  event: state    — { "state": {...}, "lead": {...} } после фоновой extract-фазы
  event: error    — { "message": "..." }              ошибка
  event: done     — {}                                стрим закрылся

Двухфазная архитектура сохранена: пузыри отдаются клиенту сразу, извлекатель работает в фоне,
state-событие приходит с задержкой 2–5 сек. Между ходами future ждётся неблокирующе.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import logging
import os
import secrets
import time
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

import llm_agent
import observability
import usage_tracker
from config import load_config
from core import (
    build_runtime_payload,
    commit_bubbles_only,
    finalize_extraction,
)
from lead_delivery import maybe_deliver
from logger import log_dialog, log_summary
from session_store import Session, SessionStore
from state import should_close_dialog


logger = logging.getLogger("mbk.api")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")


# --------------------------------------------------------------------------- #
# Жизненный цикл и зависимости
# --------------------------------------------------------------------------- #
store: SessionStore | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global store
    store = SessionStore(max_extract_workers=4)
    # Подгрузить переопределения цен из env, если есть.
    usage_tracker.override_pricing_from_env()
    logger.info("MBK backend started. Conversation model=%s, extractor=%s",
                load_config().model, load_config().extractor_model or "(same)")
    yield
    if store is not None:
        store.executor.shutdown(wait=False, cancel_futures=True)


app = FastAPI(title="MBK assistant", version="1.0.0", lifespan=lifespan)


# CORS: на этапе пилота открываем всё, перед боем — сузим до конкретных доменов
# через env (CORS_ALLOWED_ORIGINS=https://app.example.com,https://staging.example.com).
_origins_env = os.getenv("CORS_ALLOWED_ORIGINS", "*")
allowed_origins = [o.strip() for o in _origins_env.split(",") if o.strip()] or ["*"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _store() -> SessionStore:
    assert store is not None, "SessionStore не инициализирован"
    return store


# --------------------------------------------------------------------------- #
# Контракты ввода
# --------------------------------------------------------------------------- #
class CreateSessionBody(BaseModel):
    anketa: dict[str, Any] | None = None


class LoginBody(BaseModel):
    username: str
    password: str


AUTH_COOKIE_NAME = "mbk_auth"
AUTH_TTL_SECONDS = int(os.getenv("MBK_AUTH_TTL_SECONDS", "43200"))


# --------------------------------------------------------------------------- #
# Статическая авторизация
# --------------------------------------------------------------------------- #
@app.middleware("http")
async def require_api_auth(request: Request, call_next):
    path = request.url.path
    public_api = path == "/api/health" or path.startswith("/api/auth/")
    if not path.startswith("/api/") or public_api:
        return await call_next(request)

    try:
        authorized = _verify_auth_token(request.cookies.get(AUTH_COOKIE_NAME))
    except HTTPException as exc:
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})

    if not authorized:
        return JSONResponse(status_code=401, content={"detail": "Требуется авторизация"})
    return await call_next(request)


# --------------------------------------------------------------------------- #
# Эндпоинты
# --------------------------------------------------------------------------- #
@app.get("/api/health")
async def health() -> dict:
    cfg = load_config()
    return {
        "status": "ok",
        "conversation_model": cfg.model,
        "extractor_model": cfg.extractor_model or cfg.model,
    }


@app.post("/api/auth/login")
async def login(body: LoginBody) -> JSONResponse:
    expected_username, expected_password = _auth_credentials()
    username_ok = hmac.compare_digest(body.username.strip(), expected_username)
    password_ok = hmac.compare_digest(body.password, expected_password)
    if not (username_ok and password_ok):
        raise HTTPException(status_code=401, detail="Неверный логин или пароль")

    response = JSONResponse(content={"ok": True, "username": expected_username})
    response.set_cookie(
        AUTH_COOKIE_NAME,
        _make_auth_token(expected_username),
        max_age=AUTH_TTL_SECONDS,
        httponly=True,
        secure=_secure_auth_cookie(),
        samesite="lax",
        path="/",
    )
    return response


@app.get("/api/auth/me")
async def auth_me(request: Request) -> dict:
    username = _auth_username_from_token(request.cookies.get(AUTH_COOKIE_NAME))
    if not username:
        return {"ok": False, "username": None}
    return {"ok": True, "username": username}


@app.post("/api/auth/logout")
async def logout() -> JSONResponse:
    response = JSONResponse(content={"ok": True})
    response.delete_cookie(AUTH_COOKIE_NAME, path="/")
    return response


@app.post("/api/session")
async def create_session(body: CreateSessionBody) -> dict:
    session = await _store().create(anketa=body.anketa)
    return {
        "session_id": session.id,
        "has_anketa": bool(session.anketa),
        "state": _public_state(session),
    }


@app.get("/api/session/{session_id}")
async def get_session(session_id: str) -> dict:
    session = await _store().get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="session not found")
    return {"session_id": session.id, "state": _public_state(session), "anketa": session.anketa}


@app.get("/api/session/{session_id}/usage")
async def get_usage(session_id: str) -> dict:
    session = await _store().get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="session not found")
    return session.usage.summary()


@app.get("/api/usage/global")
async def get_global_usage() -> dict:
    summary = usage_tracker.aggregate(s.usage for s in _store().all_sessions())
    summary["active_sessions"] = len(_store().all_sessions())
    return summary


@app.post("/api/session/{session_id}/end")
async def end_session(session_id: str) -> dict:
    session = await _store().get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="session not found")
    try:
        log_summary(session.id, session.state)
    except Exception:  # noqa: BLE001
        pass
    _store().persist(session)
    return {"ok": True, "usage": session.usage.summary()}


# --------------------------------------------------------------------------- #
# SSE-стрим: opening или turn в зависимости от наличия message
# --------------------------------------------------------------------------- #
@app.get("/api/session/{session_id}/stream")
async def stream(session_id: str, request: Request, message: str | None = None) -> EventSourceResponse:
    session = await _store().get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="session not found")

    user_message = (message or "").strip()
    is_opening = (not user_message) and (not session.state.get("chat_history"))

    return EventSourceResponse(
        _run_turn_sse(session, user_message, is_opening=is_opening, request=request),
        media_type="text/event-stream",
    )


# --------------------------------------------------------------------------- #
# Главная корутина одного хода (opening или обычный turn)
# --------------------------------------------------------------------------- #
async def _run_turn_sse(
    session: Session,
    user_message: str,
    is_opening: bool,
    request: Request,
):
    """Yields SSE-события: chunk → bubbles → state → done.
    Полностью повторяет двухфазную архитектуру: пузыри сразу, extract в фоне."""
    cfg = load_config()
    loop = asyncio.get_event_loop()

    # 1) Если в фоне болтается предыдущая extract-фаза — дожимаем её перед стартом нового стрима.
    #    На отдыхающем юзере (5+ сек между ходами) future уже done, ждать не придётся.
    await _flush_pending_extraction(session)

    if not is_opening and not user_message:
        yield _sse_error("empty message")
        return

    session.touch()

    payload = build_runtime_payload(session.state, user_message)
    role = "opening" if is_opening else "conversation"
    usage_cb = session.usage.collector(role=role)

    # 2) Стрим разговорной/opening-модели.
    try:
        if is_opening:
            has_anketa = bool(session.anketa)
            sync_iter = llm_agent.stream_opening(payload, cfg, has_anketa=has_anketa, usage_collector=usage_cb)
        else:
            sync_iter = llm_agent.stream_conversation(payload, cfg, usage_collector=usage_cb)
    except Exception as exc:  # noqa: BLE001
        yield _sse_error(f"failed to start stream: {exc}")
        return

    collected_parts: list[str] = []
    try:
        # Прокидываем sync-генератор в async через executor.
        sentinel = object()
        while True:
            if await request.is_disconnected():
                logger.info("client disconnected mid-stream, session=%s", session.id)
                break
            chunk = await loop.run_in_executor(None, lambda: next(sync_iter, sentinel))
            if chunk is sentinel:
                break
            collected_parts.append(chunk)
            yield {"event": "chunk", "data": json.dumps({"text": chunk}, ensure_ascii=False)}
    except Exception as exc:  # noqa: BLE001
        logger.exception("stream error")
        yield _sse_error(f"stream error: {exc}")
        return

    full_reply = "".join(collected_parts).strip()
    if not full_reply:
        yield _sse_error("empty model response")
        return

    # 3) Быстрая фаза — пузыри. Для opening user_message пустой, но commit_bubbles_only
    #    корректно положит только пузыри ассистента (user-сообщение всё равно создастся, но пустое
    #    мы потом подчистим внутри _attach_opening_bubbles).
    if is_opening:
        bubbles_phase = _attach_opening_bubbles(session.state, full_reply)
    else:
        bubbles_phase = commit_bubbles_only(session.state, user_message, full_reply)

    session.state = bubbles_phase["current_state"]
    session.has_started_opening = session.has_started_opening or is_opening
    _store().persist(session)

    try:
        log_dialog(session.id, user_message or "(opening)", True, session.state, {})
        log_dialog(session.id, "\n\n".join(bubbles_phase["messages"]), False, session.state, {})
    except Exception:  # noqa: BLE001
        pass

    yield {"event": "bubbles", "data": json.dumps({"bubbles": bubbles_phase["messages"]}, ensure_ascii=False)}

    # 4) Медленная фаза — в фоне. Отдаём done сразу, state-событие придёт асинхронно.
    if not is_opening:
        extract_cb = session.usage.collector(role="extraction")
        future = _store().executor.submit(
            _run_extraction_with_usage,
            session.state,
            user_message,
            full_reply,
            cfg,
            extract_cb,
        )
        session.pending_extraction = future
        # state-событие отправим, когда future закончится — для этого подождём в той же
        # SSE-сессии, но не дольше N секунд (чтобы не держать соединение бесконечно).
        try:
            result = await asyncio.wait_for(asyncio.wrap_future(future), timeout=20.0)
            session.state = result["current_state"]
            session.pending_extraction = None
            _store().persist(session)
            yield {
                "event": "state",
                "data": json.dumps(
                    {
                        "state": _public_state(session),
                        "lead_delivered": session.state.get("lead_delivered"),
                    },
                    ensure_ascii=False,
                    default=str,
                ),
            }
        except asyncio.TimeoutError:
            # Не страшно — на следующем ходе _flush_pending_extraction подхватит.
            logger.warning("extraction did not finish within 20s, will resolve on next turn")
    yield {"event": "done", "data": "{}"}


def _run_extraction_with_usage(state, user_message, full_reply, cfg, usage_cb):
    """Обёртка над finalize_extraction, чтобы прокинуть usage_collector в llm_agent.extract_state.

    finalize_extraction(core.py) не принимает usage_collector — он не знает про токены.
    Мы прокидываем сюда callback через монки-патчинг: подменяем extract_state на время
    одного вызова. Это аккуратнее, чем менять сигнатуру finalize_extraction."""
    original = llm_agent.extract_state
    def patched(payload, assistant_reply, config):
        return original(payload, assistant_reply, config, usage_collector=usage_cb)
    llm_agent.extract_state = patched
    try:
        return finalize_extraction(state, user_message, full_reply, cfg)
    finally:
        llm_agent.extract_state = original


async def _flush_pending_extraction(session: Session) -> None:
    """Перед новым ходом — дожать предыдущую фоновую extract-фазу (если ещё крутится)."""
    fut = session.pending_extraction
    if fut is None:
        return
    if not fut.done():
        try:
            await asyncio.wait_for(asyncio.wrap_future(fut), timeout=20.0)
        except asyncio.TimeoutError:
            logger.warning("flush_pending_extraction timed out, session=%s", session.id)
            return
    try:
        result = fut.result(timeout=0)
        session.state = result["current_state"]
    except Exception:  # noqa: BLE001
        pass
    session.pending_extraction = None
    _store().persist(session)


def _attach_opening_bubbles(state: dict, full_reply: str) -> dict:
    """Версия commit_bubbles_only для opening-сценария: user-реплики нет, поэтому подшиваем
    только пузыри ассистента."""
    from copy import deepcopy

    from utils import guard_bubbles
    from prompts import split_bubbles

    bubbles = guard_bubbles(split_bubbles(full_reply)) or [full_reply.strip() or "…"]
    new_state = deepcopy(state)
    history = new_state.setdefault("chat_history", [])
    for b in bubbles:
        history.append({"role": "assistant", "content": b})
    new_state["message_count"] = state.get("message_count", 0) + 1
    return {"messages": bubbles, "current_state": new_state}


# --------------------------------------------------------------------------- #
# Хелперы
# --------------------------------------------------------------------------- #
def _public_state(session: Session) -> dict:
    """Слепок state для клиента: всё, что нужно фронту для рендера. PII не вырезаем —
    клиент видит то же, что ассистент собрал."""
    s = session.state
    return {
        "chat_history": s.get("chat_history", []),
        "current_facts": s.get("current_facts", {}),
        "fact_statuses": s.get("fact_statuses", {}),
        "dialog_phase": s.get("dialog_phase"),
        "selected_product_id": s.get("selected_product_id"),
        "declined_products": s.get("declined_products", []),
        "product_fit_result": s.get("product_fit_result"),
        "lead_delivered": s.get("lead_delivered"),
        "lead_delivery_status": s.get("lead_delivery_status"),
        "closed": should_close_dialog(s),
    }


def _sse_error(message: str) -> dict:
    return {"event": "error", "data": json.dumps({"message": message}, ensure_ascii=False)}


def _auth_credentials() -> tuple[str, str]:
    username = _read_env_value("MBK_AUTH_USERNAME")
    password = _read_env_value("MBK_AUTH_PASSWORD")
    if not username or not password:
        raise HTTPException(status_code=503, detail="Не настроены MBK_AUTH_USERNAME и MBK_AUTH_PASSWORD")
    return username, password


def _read_env_value(name: str) -> str | None:
    value = os.getenv(name) or os.getenv(f"$env:{name}")
    return value.strip() if value else None


def _secure_auth_cookie() -> bool:
    value = (_read_env_value("MBK_AUTH_COOKIE_SECURE") or "0").lower()
    return value in {"1", "true", "yes"}


def _make_auth_token(username: str) -> str:
    expires_at = int(time.time()) + AUTH_TTL_SECONDS
    payload = {"u": username, "exp": expires_at, "n": secrets.token_urlsafe(16)}
    payload_json = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    payload_b64 = _base64url_encode(payload_json)
    signature = _sign_auth_payload(payload_b64)
    return f"{payload_b64}.{signature}"


def _verify_auth_token(token: str | None) -> bool:
    return _auth_username_from_token(token) is not None


def _auth_username_from_token(token: str | None) -> str | None:
    if not token or "." not in token:
        return None
    payload_b64, signature = token.split(".", 1)
    if not hmac.compare_digest(signature, _sign_auth_payload(payload_b64)):
        return None
    try:
        payload = json.loads(_base64url_decode(payload_b64))
        username = str(payload.get("u") or "")
        expires_at = int(payload.get("exp") or 0)
    except (ValueError, TypeError, json.JSONDecodeError):
        return None
    expected_username, _ = _auth_credentials()
    if time.time() >= expires_at:
        return None
    if not hmac.compare_digest(username, expected_username):
        return None
    return username


def _sign_auth_payload(payload_b64: str) -> str:
    _, password = _auth_credentials()
    return hmac.new(password.encode("utf-8"), payload_b64.encode("utf-8"), hashlib.sha256).hexdigest()


def _base64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _base64url_decode(data: str) -> bytes:
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode((data + padding).encode("ascii"))


# --------------------------------------------------------------------------- #
# Базовый JSON-обработчик для непойманных HTTPException — чтобы фронт получал детали
# --------------------------------------------------------------------------- #
@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})
