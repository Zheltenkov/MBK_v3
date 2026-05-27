from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.request
from typing import Any

from assistant_contracts import AssistantTurn
from config import AppConfig
from prompts import get_full_system_prompt


OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"


def _is_deepseek_reasoning_model(model: str) -> bool:
    return model.startswith("deepseek/deepseek-v4")


def _strip_code_fence(raw: str) -> str:
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text)
    return text.strip()


def _extract_json(raw: str) -> dict[str, Any]:
    """Parse a model response into a JSON object suitable for AssistantTurn validation."""
    text = _strip_code_fence(raw)
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start < 0 or end <= start:
            raise
        value = json.loads(text[start : end + 1])

    if isinstance(value, list):
        return {"messages": [str(item) for item in value]}
    if not isinstance(value, dict):
        raise ValueError("model response is not a JSON object")
    return value


def _runtime_user_prompt(payload: dict[str, Any]) -> str:
    """Serialize deterministic runtime context as data, not hidden prompt logic."""
    public_payload = {
        "current_facts": payload.get("current_facts", {}),
        "fact_statuses": payload.get("fact_statuses", {}),
        "short_history": payload.get("short_history", []),
        "latest_user_message": payload.get("latest_user_message", ""),
        "business_rules_summary": payload.get("business_rules_summary", ""),
    }
    return (
        "Контекст текущего хода ниже. Ответь клиенту строго по контракту AssistantTurn.\n"
        "Верни только JSON-объект, без markdown и пояснений.\n\n"
        "Минимальная форма ответа:\n"
        '{"messages":["..."],"dialog_phase":"qualification","fact_updates":[],'
        '"status_updates":[],"product_fit_result":null,"target_completion":null,'
        '"internal_summary":"..."}\n\n'
        f"{json.dumps(public_payload, ensure_ascii=False, indent=2)}"
    )


def _openrouter_chat(config: AppConfig, messages: list[dict[str, str]]) -> str:
    payload: dict[str, Any] = {
        "model": config.model,
        "messages": messages,
        "temperature": config.temperature,
        "max_tokens": config.max_tokens,
        "response_format": {"type": "json_object"},
    }
    if _is_deepseek_reasoning_model(config.model):
        # DeepSeek V4 can spend the whole budget on reasoning and return content=None.
        # Ask OpenRouter to suppress reasoning tokens in the response and keep budget for JSON.
        payload["reasoning"] = {"effort": "none", "exclude": True}
        payload["include_reasoning"] = False

    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")

    last_error: Exception | None = None
    for attempt in range(1, 4):
        request = urllib.request.Request(
            OPENROUTER_URL,
            data=body,
            headers={
                "Authorization": f"Bearer {config.openrouter_api_key}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://local.mbk-human-assistant",
                "X-Title": "MBK Human Assistant Local App",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                data = json.loads(response.read())
            choice = data["choices"][0]
            message = choice.get("message") or {}
            content = message.get("content")
            if not content:
                finish_reason = choice.get("finish_reason")
                reasoning_len = len(message.get("reasoning") or "")
                raise ValueError(
                    f"empty model content; finish_reason={finish_reason}; reasoning_len={reasoning_len}"
                )
            return str(content)
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:800]
            last_error = RuntimeError(f"OpenRouter HTTP {exc.code}: {detail}")
            if exc.code not in {408, 409, 425, 429, 500, 502, 503, 504}:
                break
        except (TimeoutError, urllib.error.URLError, json.JSONDecodeError, KeyError, ValueError) as exc:
            last_error = exc

        if attempt < 3:
            time.sleep(1.5 * attempt)

    raise RuntimeError(str(last_error))


def run_assistant_agent(payload: dict[str, Any], config: AppConfig) -> dict[str, Any]:
    """Call OpenRouter and validate the assistant turn contract."""
    raw = _openrouter_chat(
        config,
        [
            {"role": "system", "content": get_full_system_prompt()},
            {"role": "user", "content": _runtime_user_prompt(payload)},
        ],
    )
    parsed = _extract_json(raw)
    turn = AssistantTurn.model_validate(parsed)
    return turn.model_dump()
