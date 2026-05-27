from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.request
from typing import Any, Iterator

from assistant_contracts import StateUpdate
from config import AppConfig
from prompts import (
    CONVERSATION_SYSTEM_PROMPT,
    EXTRACTION_SYSTEM_PROMPT,
    STYLE_EXAMPLES,
)

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
_RETRYABLE = {408, 409, 425, 429, 500, 502, 503, 504}


def _is_reasoning_model(model: str) -> bool:
    """Reasoning-модели (deepseek v4, o-серия и пр.) тормозят живой чат — гасим reasoning."""
    m = model.lower()
    return m.startswith("deepseek/deepseek-v4") or "reason" in m or "/o1" in m or "/o3" in m


def _headers(config: AppConfig) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {config.openrouter_api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://local.mbk-human-assistant",
        "X-Title": "MBK Human Assistant Local App",
    }


def _maybe_suppress_reasoning(payload: dict[str, Any], config: AppConfig) -> None:
    if _is_reasoning_model(config.model):
        payload["reasoning"] = {"effort": "none", "exclude": True}
        payload["include_reasoning"] = False


# --------------------------------------------------------------------------- #
# Контекст клиента (общий для обоих вызовов): что уже известно — отдельным
# системным сообщением, чтобы не выглядело как текст клиента.
# --------------------------------------------------------------------------- #
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


# --------------------------------------------------------------------------- #
# Сетевые вызовы
# --------------------------------------------------------------------------- #
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


def _post_stream(config: AppConfig, payload: dict[str, Any]) -> Iterator[str]:
    """Стримим content-дельты из OpenRouter (SSE)."""
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
            delta = (chunk.get("choices") or [{}])[0].get("delta") or {}
            piece = delta.get("content")
            if piece:
                yield piece


# --------------------------------------------------------------------------- #
# Публичный API
# --------------------------------------------------------------------------- #
def stream_conversation(payload: dict[str, Any], config: AppConfig) -> Iterator[str]:
    """Живой разговорный ответ клиенту — чистый текст, токен за токеном (как GPT)."""
    body: dict[str, Any] = {
        "model": config.model,
        "messages": _conversation_messages(payload),
        "temperature": config.temperature,
        "max_tokens": config.max_tokens,
    }
    _maybe_suppress_reasoning(body, config)
    yield from _post_stream(config, body)


def generate_reply(payload: dict[str, Any], config: AppConfig) -> str:
    """Не-стримовый вариант того же разговорного ответа (для эвала/совместимости)."""
    body: dict[str, Any] = {
        "model": config.model,
        "messages": _conversation_messages(payload),
        "temperature": config.temperature,
        "max_tokens": config.max_tokens,
    }
    _maybe_suppress_reasoning(body, config)
    data = _post(config, body)
    content = ((data.get("choices") or [{}])[0].get("message") or {}).get("content")
    if not content:
        raise RuntimeError("empty conversation content from model")
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


def extract_state(payload: dict[str, Any], assistant_reply: str, config: AppConfig) -> dict[str, Any]:
    """Молчаливый бэкенд-разбор хода в StateUpdate. Клиент его не видит."""
    extractor_model = config.extractor_model or config.model
    user_content = (
        f"{_context_block(payload)}\n\n"
        f"Последняя реплика клиента:\n{payload.get('latest_user_message', '')}\n\n"
        f"Ответ оператора:\n{assistant_reply}\n\n"
        "Верни только JSON-объект StateUpdate."
    )
    body: dict[str, Any] = {
        "model": extractor_model,
        "messages": [
            {"role": "system", "content": EXTRACTION_SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ],
        "temperature": 0.0,
        "max_tokens": 900,
        "response_format": {"type": "json_object"},
    }
    if _is_reasoning_model(extractor_model):
        body["reasoning"] = {"effort": "none", "exclude": True}
        body["include_reasoning"] = False

    data = _post(config, body)
    content = ((data.get("choices") or [{}])[0].get("message") or {}).get("content")
    if not content:
        raise RuntimeError("empty extractor content from model")
    parsed = _extract_json(str(content))
    return StateUpdate.model_validate(parsed).model_dump()
