from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.request
from typing import Any, Iterator

import observability
from assistant_contracts import FactUpdate, ProductFitResult, StateUpdate, StatusUpdate, TargetCompletion
from config import AppConfig
from prompts import (
    CONVERSATION_SYSTEM_PROMPT,
    EXTRACTION_SYSTEM_PROMPT,
    STYLE_EXAMPLES,
)

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
_RETRYABLE = {408, 409, 425, 429, 500, 502, 503, 504}


def _is_reasoning_model(model: str) -> bool:
    m = (model or "").lower()
    return m.startswith("deepseek/deepseek-v4") or "reason" in m or "/o1" in m or "/o3" in m


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
    return "\n\n".join(parts)


def _history_messages(payload: dict[str, Any]) -> list[dict[str, str]]:
    msgs: list[dict[str, str]] = []
    for turn in payload.get("short_history", []):
        role = "assistant" if turn.get("role") == "assistant" else "user"
        content = str(turn.get("content", "")).strip()
        if content:
            msgs.append({"role": role, "content": content})
    return msgs


def _conversation_messages(payload: dict[str, Any]) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": CONVERSATION_SYSTEM_PROMPT + "\n\n" + STYLE_EXAMPLES},
        {"role": "system", "content": _context_block(payload)},
        *_history_messages(payload),
        {"role": "user", "content": str(payload.get("latest_user_message", ""))},
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


def stream_conversation(payload: dict[str, Any], config: AppConfig) -> Iterator[str]:
    """Живой ответ токен за токеном. Каждый вызов трассируется как Langfuse generation."""
    messages = _conversation_messages(payload)
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


def extract_state(payload: dict[str, Any], assistant_reply: str, config: AppConfig) -> dict[str, Any]:
    extractor_model = config.extractor_model or config.model
    user_content = (
        f"{_context_block(payload)}\n\n"
        f"Последняя реплика клиента:\n{payload.get('latest_user_message', '')}\n\n"
        f"Ответ оператора:\n{assistant_reply}\n\n"
        "Верни только JSON-объект StateUpdate."
    )
    messages = [
        {"role": "system", "content": EXTRACTION_SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]
    body: dict[str, Any] = {
        "model": extractor_model,
        "messages": messages,
        "temperature": 0.0,
        "max_tokens": 900,
        "response_format": {"type": "json_object"},
    }
    _maybe_suppress_reasoning(body, extractor_model)

    with observability.generation(
        name="extraction",
        model=extractor_model,
        input_messages=messages,
        model_parameters={"temperature": 0.0, "max_tokens": 900, "response_format": "json_object"},
    ) as gen:
        try:
            data = _post(config, body)
        except Exception as exc:
            observability.finalize_generation(gen, error=repr(exc))
            raise
        content = ((data.get("choices") or [{}])[0].get("message") or {}).get("content")
        if not content:
            observability.finalize_generation(gen, error="empty extractor content")
            raise RuntimeError("empty extractor content from model")
        try:
            parsed = _extract_json(str(content))
            validated = StateUpdate.model_validate(_sanitize_state_update_payload(parsed)).model_dump()
        except Exception as exc:
            observability.finalize_generation(gen, output=str(content), error=f"validate: {exc}")
            raise
        observability.finalize_generation(
            gen,
            output=validated,
            usage=observability.usage_from_openrouter(data.get("usage")),
        )
        return validated
