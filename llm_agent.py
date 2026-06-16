from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.request
from typing import Any, Callable, Iterator

from pydantic import ValidationError

import observability
from assistant_contracts import FactUpdate, ProductFitResult, StateUpdate, StatusUpdate, TargetCompletion
from config import AppConfig
from prompts import (
    CONVERSATION_SYSTEM_PROMPT,
    EXTRACTION_SYSTEM_PROMPT,
    STYLE_EXAMPLES,
    relevant_product_knowledge,
)

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
_RETRYABLE = {408, 409, 425, 429, 500, 502, 503, 504}


def _is_reasoning_model(model: str) -> bool:
    m = (model or "").lower()
    return (
        m.startswith("deepseek/deepseek-v4")
        or m.startswith("qwen/qwen3.7-max")
        or "qwen3.7-max" in m
        or "reason" in m
        or "/o1" in m
        or "/o3" in m
    )


def _headers(config: AppConfig) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {config.openrouter_api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://local.mbk-human-assistant",
        "X-Title": "MBK Human Assistant Local App",
    }


def _maybe_suppress_reasoning(payload: dict[str, Any], model_name: str) -> None:
    if _is_reasoning_model(model_name):
        payload["reasoning"] = {"effort": "none", "exclude": True}
        payload["include_reasoning"] = False


def _context_block(payload: dict[str, Any]) -> str:
    facts = payload.get("current_facts", {})
    statuses = payload.get("fact_statuses", {})
    rules = payload.get("business_rules_summary", "")
    parts = []
    if rules:
        parts.append(f"Рабочие ориентиры МБК:\n{rules}")
    parts.append(
        "Что уже известно о клиенте (используй, НЕ переспрашивай):\n"
        + json.dumps(facts, ensure_ascii=False, indent=2)
    )
    if statuses:
        parts.append("Статусы фактов:\n" + json.dumps(statuses, ensure_ascii=False))
    declined = payload.get("declined_products") or []
    if declined:
        parts.append("Клиент уже отказался от вариантов (НЕ предлагай их снова): " + ", ".join(declined))
    delivered = payload.get("lead_delivered")
    if delivered:
        label = delivered.get("product_label") or delivered.get("product_id") or "—"
        parts.append(
            f"ВАЖНО: лид по направлению «{label}» уже передан специалисту в этой сессии. "
            "НЕ начинай новую квалификацию под другой продукт. Отвечай на вопросы клиента "
            "и направляй к ожиданию специалиста."
        )
    return "\n\n".join(parts)


def _history_messages(payload: dict[str, Any]) -> list[dict[str, str]]:
    msgs: list[dict[str, str]] = []
    for turn in payload.get("short_history", []):
        role = "assistant" if turn.get("role") == "assistant" else "user"
        content = str(turn.get("content", "")).strip()
        if content:
            msgs.append({"role": role, "content": content})
    return msgs


def _cached_tokens(usage: dict) -> int:
    """Достаёт cached_tokens из usage OpenRouter (prompt_tokens_details.cached_tokens)."""
    if not isinstance(usage, dict):
        return 0
    details = usage.get("prompt_tokens_details")
    if isinstance(details, dict):
        return int(details.get("cached_tokens", 0) or 0)
    # некоторые провайдеры кладут плоско
    return int(usage.get("cached_tokens", 0) or 0)


def _apply_cache_control(messages: list[dict[str, Any]], enable: bool) -> list[dict[str, Any]]:
    """Размечает статический префикс cache_control-брейкпоинтами (синтаксис Anthropic/Alibaba).

    Ставим до 2 точек кэша:
      - на первый system-блок (персона + few-shots) — байт-в-байт каждый ход, всегда хит;
      - на второй system-блок (релевантные знания) — стабилен в рамках обсуждения одного
        продукта, хит при повторе.
    Динамический блок фактов (третий system) и история не кэшируются — они меняются.

    Если провайдер не поддерживает cache_control — поле просто игнорируется, запрос валиден.
    """
    if not enable:
        return messages
    out: list[dict[str, Any]] = []
    system_seen = 0
    for m in messages:
        # Кэшируем только первые ДВА system-сообщения (персона+few-shots, затем знания).
        if m.get("role") == "system" and system_seen < 2 and isinstance(m.get("content"), str):
            system_seen += 1
            out.append({
                "role": "system",
                "content": [
                    {
                        "type": "text",
                        "text": m["content"],
                        "cache_control": {"type": "ephemeral"},
                    }
                ],
            })
        else:
            out.append(m)
    return out


def _conversation_messages(payload: dict[str, Any]) -> list[dict[str, str]]:
    knowledge = relevant_product_knowledge(
        payload.get("current_facts") or {},
        str(payload.get("latest_user_message") or ""),
    )
    return [
        {"role": "system", "content": CONVERSATION_SYSTEM_PROMPT + "\n\n" + STYLE_EXAMPLES},
        {"role": "system", "content": knowledge},
        {"role": "system", "content": _context_block(payload)},
        *_history_messages(payload),
        {"role": "user", "content": str(payload.get("latest_user_message", ""))},
    ]


def _opening_messages(payload: dict[str, Any], has_anketa: bool) -> list[dict[str, str]]:
    """Сборка сообщений для авто-старта: реплики клиента ещё нет, вместо неё — внутренняя
    подсказка о том, что клиент только что подключился."""
    facts = payload.get("current_facts") or {}
    knowledge = relevant_product_knowledge(facts, "")
    if has_anketa:
        hint = (
            "Клиент только что прислал анкету и впервые открыл чат. Начни разговор первым: "
            "коротко поздоровайся по имени из анкеты, обозначь себя (Олег, специалист МБК), "
            "одной фразой подведи, что видишь в заявке, и задай первый по сути уточняющий вопрос, "
            "который реально продвинет к маршруту. Без длинных вступлений. 1–3 коротких сообщения."
        )
    else:
        hint = (
            "Клиент только что открыл чат, анкеты нет. Начни разговор первым: коротко поздоровайся, "
            "представься (Олег, специалист МБК) и задай открытый вопрос — что привело и какая сумма. "
            "Без длинных вступлений. 1–2 коротких сообщения."
        )
    return [
        {"role": "system", "content": CONVERSATION_SYSTEM_PROMPT + "\n\n" + STYLE_EXAMPLES},
        {"role": "system", "content": knowledge},
        {"role": "system", "content": _context_block(payload)},
        {"role": "system", "content": hint},
    ]


def _post(config: AppConfig, payload: dict[str, Any]) -> dict[str, Any]:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    last_error: Exception | None = None
    for attempt in range(1, 4):
        request = urllib.request.Request(OPENROUTER_URL, data=body, headers=_headers(config))
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                return json.loads(response.read())
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:800]
            last_error = RuntimeError(f"OpenRouter HTTP {exc.code}: {detail}")
            if exc.code not in _RETRYABLE:
                break
        except (TimeoutError, urllib.error.URLError, json.JSONDecodeError) as exc:
            last_error = exc
        if attempt < 3:
            time.sleep(1.5 * attempt)
    raise RuntimeError(str(last_error))


def _post_stream(
    config: AppConfig, payload: dict[str, Any], usage_sink: dict | None = None
) -> Iterator[str]:
    """Стримим content-дельты OpenRouter (SSE). При include_usage=True последний чанк
    содержит usage → кладём в usage_sink."""
    payload = {**payload, "stream": True}
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(OPENROUTER_URL, data=body, headers=_headers(config))
    with urllib.request.urlopen(request, timeout=120) as response:
        for raw_line in response:
            line = raw_line.decode("utf-8", errors="replace").strip()
            if not line or not line.startswith("data:"):
                continue
            data = line[len("data:"):].strip()
            if data == "[DONE]":
                break
            try:
                chunk = json.loads(data)
            except json.JSONDecodeError:
                continue
            if usage_sink is not None and isinstance(chunk.get("usage"), dict):
                usage_sink.update(chunk["usage"])
            delta = (chunk.get("choices") or [{}])[0].get("delta") or {}
            piece = delta.get("content")
            if piece:
                yield piece


def stream_opening(
    payload: dict[str, Any],
    config: AppConfig,
    has_anketa: bool,
    usage_collector: Callable[[str, int, int], None] | None = None,
) -> Iterator[str]:
    """Авто-старт диалога: бот первым обращается к клиенту. С анкетой — приветствие по имени
    и квалифицирующий вопрос; без анкеты — открытый «что привело»."""
    messages = _apply_cache_control(_opening_messages(payload, has_anketa=has_anketa), config.enable_prompt_cache)
    body: dict[str, Any] = {
        "model": config.model,
        "messages": messages,
        "temperature": config.temperature,
        "max_tokens": config.max_tokens,
        "stream_options": {"include_usage": True},
    }
    _maybe_suppress_reasoning(body, config.model)

    usage_sink: dict = {}
    collected: list[str] = []
    err: str | None = None
    with observability.generation(
        name="opening",
        model=config.model,
        input_messages=messages,
        model_parameters={"temperature": config.temperature, "max_tokens": config.max_tokens, "stream": True},
    ) as gen:
        try:
            for piece in _post_stream(config, body, usage_sink):
                collected.append(piece)
                yield piece
        except BaseException as exc:  # noqa: BLE001
            err = repr(exc)
            raise
        finally:
            observability.finalize_generation(
                gen, output="".join(collected),
                usage=observability.usage_from_openrouter(usage_sink),
                error=err,
            )
            if usage_collector and usage_sink:
                try:
                    usage_collector(
                        config.model,
                        int(usage_sink.get("prompt_tokens", 0) or 0),
                        int(usage_sink.get("completion_tokens", 0) or 0),
                        _cached_tokens(usage_sink),
                    )
                except Exception:  # noqa: BLE001
                    pass


def stream_conversation(
    payload: dict[str, Any],
    config: AppConfig,
    usage_collector: Callable[[str, int, int], None] | None = None,
) -> Iterator[str]:
    """Живой ответ токен за токеном. Каждый вызов трассируется как Langfuse generation.
    Если задан usage_collector(model, prompt_tokens, completion_tokens) — вызывается
    после стрима с финальным usage из OpenRouter (когда тот пришёл)."""
    messages = _apply_cache_control(_conversation_messages(payload), config.enable_prompt_cache)
    body: dict[str, Any] = {
        "model": config.model,
        "messages": messages,
        "temperature": config.temperature,
        "max_tokens": config.max_tokens,
        "stream_options": {"include_usage": True},
    }
    _maybe_suppress_reasoning(body, config.model)

    usage_sink: dict = {}
    collected: list[str] = []
    err: str | None = None
    with observability.generation(
        name="conversation",
        model=config.model,
        input_messages=messages,
        model_parameters={
            "temperature": config.temperature,
            "max_tokens": config.max_tokens,
            "stream": True,
        },
    ) as gen:
        try:
            for piece in _post_stream(config, body, usage_sink):
                collected.append(piece)
                yield piece
        except BaseException as exc:  # noqa: BLE001 — нужно поймать всё, чтобы залогировать ошибку
            err = repr(exc)
            raise
        finally:
            observability.finalize_generation(
                gen,
                output="".join(collected),
                usage=observability.usage_from_openrouter(usage_sink),
                error=err,
            )
            if usage_collector and usage_sink:
                try:
                    usage_collector(
                        config.model,
                        int(usage_sink.get("prompt_tokens", 0) or 0),
                        int(usage_sink.get("completion_tokens", 0) or 0),
                        _cached_tokens(usage_sink),
                    )
                except Exception:  # noqa: BLE001 — учёт не должен валить пайплайн
                    pass


def generate_reply(payload: dict[str, Any], config: AppConfig) -> str:
    """Не-стримовый разговорный ответ (для эвала/совместимости)."""
    messages = _conversation_messages(payload)
    body: dict[str, Any] = {
        "model": config.model,
        "messages": messages,
        "temperature": config.temperature,
        "max_tokens": config.max_tokens,
    }
    _maybe_suppress_reasoning(body, config.model)

    with observability.generation(
        name="conversation",
        model=config.model,
        input_messages=messages,
        model_parameters={"temperature": config.temperature, "max_tokens": config.max_tokens},
    ) as gen:
        try:
            data = _post(config, body)
        except Exception as exc:
            observability.finalize_generation(gen, error=repr(exc))
            raise
        content = ((data.get("choices") or [{}])[0].get("message") or {}).get("content")
        if not content:
            observability.finalize_generation(gen, error="empty content")
            raise RuntimeError("empty conversation content from model")
        observability.finalize_generation(
            gen,
            output=str(content),
            usage=observability.usage_from_openrouter(data.get("usage")),
        )
        return str(content)


def _strip_code_fence(raw: str) -> str:
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text)
    return text.strip()


def _extract_json(raw: str) -> dict[str, Any]:
    text = _strip_code_fence(raw)
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start < 0 or end <= start:
            raise
        value = json.loads(text[start : end + 1])
    if not isinstance(value, dict):
        raise ValueError("extractor response is not a JSON object")
    return value


def _keep_model_fields(value: Any, model_cls: type) -> Any:
    """Drop harmless extra keys from LLM JSON while keeping the public contract strict."""
    if not isinstance(value, dict):
        return value
    allowed = set(model_cls.model_fields)
    return {key: item for key, item in value.items() if key in allowed}


def _sanitize_state_update_payload(value: dict[str, Any]) -> dict[str, Any]:
    """Repair common extractor drift before schema validation.

    The Pydantic models stay `extra=forbid`; this adapter is the explicit repair layer for
    model output, so harmless keys like status_updates[].source do not break the turn.
    """
    clean = _keep_model_fields(value, StateUpdate)
    if isinstance(clean.get("fact_updates"), list):
        clean["fact_updates"] = [_keep_model_fields(item, FactUpdate) for item in clean["fact_updates"]]
    if isinstance(clean.get("status_updates"), list):
        clean["status_updates"] = [_keep_model_fields(item, StatusUpdate) for item in clean["status_updates"]]
    if isinstance(clean.get("product_fit_result"), dict):
        clean["product_fit_result"] = _keep_model_fields(clean["product_fit_result"], ProductFitResult)
    if isinstance(clean.get("target_completion"), dict):
        clean["target_completion"] = _keep_model_fields(clean["target_completion"], TargetCompletion)
    return clean


def _as_float(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        normalized = re.sub(r"[^\d,.\-]", "", value).replace(",", ".")
        try:
            return float(normalized) if normalized else None
        except ValueError:
            return None
    return None


def _dependent_count(household: dict[str, Any]) -> int:
    raw_count = household.get("dependents_count")
    if isinstance(raw_count, bool):
        return 0
    if isinstance(raw_count, (int, float)):
        return max(0, int(raw_count))
    return 1 if household.get("has_dependents") is True else 0


def _mentions_debt_distress(payload: dict[str, Any], facts: dict[str, Any]) -> bool:
    debts = facts.get("debts") if isinstance(facts.get("debts"), dict) else {}
    if debts.get("has_current_overdue") is True:
        return True
    text = str(payload.get("latest_user_message") or "").lower()
    markers = ("долг", "просроч", "плачу с трудом", "не вытяг", "кредитор", "банкрот", "реструктур")
    return any(marker in text for marker in markers)


def _has_historical_overdue(debts: dict[str, Any]) -> bool:
    value = debts.get("historical_overdue")
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    text = str(value).strip().lower()
    return bool(text) and text not in {"нет", "не было", "false", "0", "none", "null"}


def _block_product(pfr: dict[str, Any], product_id: str) -> None:
    blocked = list(pfr.get("blocked_products") or [])
    if product_id not in blocked:
        blocked.append(product_id)
    pfr["blocked_products"] = blocked
    pfr["eligible_products"] = [p for p in (pfr.get("eligible_products") or []) if p != product_id]


def _apply_deterministic_fit_overrides(state_update: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    """Apply deterministic product-fit facts that should not depend on LLM discretion."""
    facts = payload.get("current_facts") if isinstance(payload.get("current_facts"), dict) else {}
    debts = facts.get("debts") if isinstance(facts.get("debts"), dict) else {}
    employment = facts.get("employment") if isinstance(facts.get("employment"), dict) else {}
    household = facts.get("household") if isinstance(facts.get("household"), dict) else {}

    pfr = state_update.get("product_fit_result") or {}
    if _has_historical_overdue(debts):
        _block_product(pfr, "unsecured_loan")
        _block_product(pfr, "partner_unsecured")
        if pfr.get("recommended_product_id") in {"unsecured_loan", "partner_unsecured"}:
            pfr["recommended_product_id"] = None
        state_update["product_fit_result"] = pfr

    debt_total = _as_float(debts.get("total"))

    # ЖЁСТКИЙ СТОП БФЛ ПО СУММЕ. Банкротство при долге < 300 000 экономически бессмысленно
    # (процедура стоит дороже долга). Поэтому фиксируем блок всегда, а не только когда
    # модель попыталась рекомендовать БФЛ: downstream eval/логика должны видеть явную причину тупика.
    if debt_total is not None and debt_total < 300_000:
        _block_product(pfr, "bfl_realization")
        _block_product(pfr, "bfl_restructuring")
        if pfr.get("recommended_product_id") in {"bfl_realization", "bfl_restructuring", "bfl"}:
            pfr["recommended_product_id"] = None
        # Помечаем причину — извлекатель/лог увидят, что это осознанный блок, не пустота.
        reasons = list(pfr.get("block_reasons") or [])
        if "bfl_debt_below_threshold" not in reasons:
            reasons.append("bfl_debt_below_threshold")
        pfr["block_reasons"] = reasons
        state_update["product_fit_result"] = pfr

    monthly_income = _as_float(employment.get("monthly_income") or employment.get("income"))
    if debt_total is None or monthly_income is None or debt_total < 300_000:
        return state_update
    if not _mentions_debt_distress(payload, facts):
        return state_update

    current_rec = pfr.get("recommended_product_id")
    if current_rec not in (None, "", "bfl_realization", "bfl_restructuring"):
        return state_update

    dependents = _dependent_count(household)
    plan_capacity = (monthly_income - 20_000 - 15_000 * dependents) * 60 * 0.7
    target = "bfl_restructuring" if plan_capacity > debt_total else "bfl_realization"
    declined = set(payload.get("declined_products") or []) | set(state_update.get("declined_products") or [])
    if target in declined:
        return state_update

    pfr["recommended_product_id"] = target
    eligible = list(pfr.get("eligible_products") or [])
    if target not in eligible:
        eligible.append(target)
    pfr["eligible_products"] = eligible
    pfr.setdefault("blocked_products", [])
    pfr.setdefault("missing_facts", [])
    pfr["handoff_required"] = pfr.get("handoff_required", False)
    state_update["product_fit_result"] = pfr
    if not state_update.get("dialog_phase") or state_update.get("dialog_phase") == "qualification":
        state_update["dialog_phase"] = "product_fit"
    return state_update


EXTRACTOR_MAX_ATTEMPTS = 2


def _extract_state_attempt(
    payload: dict[str, Any],
    config: AppConfig,
    extractor_model: str,
    messages: list[dict[str, str]],
    usage_collector: Callable[[str, int, int], None] | None,
    attempt: int,
) -> dict[str, Any]:
    """Одна попытка извлечения. Возвращает validated dict либо бросает исключение —
    дальше driver решает, повторять или сдаваться."""
    body: dict[str, Any] = {
        "model": extractor_model,
        "messages": messages,
        "temperature": 0.0,
        "max_tokens": 900,
        "response_format": {"type": "json_object"},
    }
    _maybe_suppress_reasoning(body, extractor_model)

    span_name = "extraction" if attempt == 1 else f"extraction_retry_{attempt}"
    with observability.generation(
        name=span_name,
        model=extractor_model,
        input_messages=messages,
        model_parameters={"temperature": 0.0, "max_tokens": 900, "response_format": "json_object"},
    ) as gen:
        try:
            data = _post(config, body)
        except Exception as exc:
            observability.finalize_generation(gen, error=repr(exc))
            raise
        usage = data.get("usage") or {}
        if usage_collector and usage:
            try:
                usage_collector(
                    extractor_model,
                    int(usage.get("prompt_tokens", 0) or 0),
                    int(usage.get("completion_tokens", 0) or 0),
                    _cached_tokens(usage),
                )
            except Exception:  # noqa: BLE001
                pass
        content = ((data.get("choices") or [{}])[0].get("message") or {}).get("content")
        if not content:
            observability.finalize_generation(gen, error="empty extractor content")
            raise RuntimeError("empty extractor content from model")
        try:
            parsed = _extract_json(str(content))
            validated = StateUpdate.model_validate(_sanitize_state_update_payload(parsed)).model_dump()
            validated = _apply_deterministic_fit_overrides(validated, payload)
        except Exception as exc:
            observability.finalize_generation(gen, output=str(content), error=f"validate: {exc}")
            raise
        observability.finalize_generation(
            gen,
            output=validated,
            usage=observability.usage_from_openrouter(usage),
        )
        return validated


def extract_state(
    payload: dict[str, Any],
    assistant_reply: str,
    config: AppConfig,
    usage_collector: Callable[[str, int, int], None] | None = None,
) -> dict[str, Any]:
    """Извлекатель JSON с повторной попыткой на синтаксическом сбое.

    Эмпирика прода/эвалов: на длинных reasoning-выходах ~5% попыток возвращают
    JSON с пропущенной запятой или незакрытой скобкой. Repair-слой Pydantic
    срабатывает уже на распарсенном dict — на синтаксисе ему делать нечего.
    Поэтому на сбое парсинга/валидации делаем ещё одну попытку с явным
    усилением требования по формату.
    """
    extractor_model = config.extractor_model or config.model
    base_user_content = (
        f"{_context_block(payload)}\n\n"
        f"Последняя реплика клиента:\n{payload.get('latest_user_message', '')}\n\n"
        f"Ответ оператора:\n{assistant_reply}\n\n"
        "Верни только JSON-объект StateUpdate."
    )

    last_error: Exception | None = None
    for attempt in range(1, EXTRACTOR_MAX_ATTEMPTS + 1):
        if attempt == 1:
            user_content = base_user_content
        else:
            user_content = (
                base_user_content
                + "\n\nКРИТИЧНО: предыдущий ответ был с синтаксически невалидным JSON "
                  "(пропущенная запятая, незакрытая скобка или лишний текст вокруг). "
                  "Верни СТРОГО валидный JSON-объект — без markdown-обёртки, без комментариев, "
                  "со всеми запятыми. Никакого текста до или после JSON."
            )
        messages = [
            {"role": "system", "content": EXTRACTION_SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ]
        try:
            return _extract_state_attempt(
                payload=payload,
                config=config,
                extractor_model=extractor_model,
                messages=messages,
                usage_collector=usage_collector,
                attempt=attempt,
            )
        except (json.JSONDecodeError, ValidationError, ValueError) as exc:
            # JSON-парс / pydantic-валидация / «не объект» — повторяем с усиленным hint.
            last_error = exc
            if attempt >= EXTRACTOR_MAX_ATTEMPTS:
                break
        except RuntimeError as exc:
            # «empty extractor content» — тоже стоит повторить.
            last_error = exc
            if "empty extractor" not in str(exc) or attempt >= EXTRACTOR_MAX_ATTEMPTS:
                raise
    assert last_error is not None
    raise last_error
