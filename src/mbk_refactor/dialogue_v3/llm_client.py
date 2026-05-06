"""Optional LLM client adapters for dialogue_v3 actor writer."""

from __future__ import annotations

import os
from dataclasses import dataclass

from .actor_writer import LLMClient


@dataclass(frozen=True)
class LLMClientStatus:
    configured: bool
    verified: bool
    available: bool
    reason: str
    model_name: str
    last_error: str | None = None


class OpenAIChatLLMClient:
    """Small OpenAI-compatible chat adapter for actor writer JSON responses."""

    def __init__(self, *, model_name: str, api_key: str | None = None):
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise RuntimeError("openai package is not installed") from exc

        self.model_name = model_name
        self._client = OpenAI(api_key=api_key)

    def __call__(self, messages: list[dict[str, str]]) -> str:
        response = self._client.chat.completions.create(
            model=self.model_name,
            messages=messages,
            temperature=0.7,
            response_format={"type": "json_object"},
        )
        content = response.choices[0].message.content
        if not content:
            raise RuntimeError("LLM returned an empty response")
        return content

    def verify(self) -> None:
        """Make a minimal call to verify auth/model access on explicit request."""

        self._client.chat.completions.create(
            model=self.model_name,
            messages=[
                {
                    "role": "user",
                    "content": 'Return exactly this JSON object: {"ok": true}',
                }
            ],
            temperature=0,
            max_tokens=8,
            response_format={"type": "json_object"},
        )


def build_optional_llm_client(
    model_name: str,
    *,
    verify: bool = False,
) -> tuple[LLMClient | None, LLMClientStatus]:
    """Build an optional LLM client without making deterministic mode depend on it."""

    api_key = os.getenv("MBK_OPENAI_API_KEY") or os.getenv("OPENAI_API_KEY")
    if not api_key:
        return None, LLMClientStatus(
            configured=False,
            verified=False,
            available=False,
            reason="missing_api_key",
            model_name=model_name,
        )
    try:
        client = OpenAIChatLLMClient(model_name=model_name, api_key=api_key)
    except Exception as exc:
        return None, _failed_status(model_name, exc, configured=True)

    if verify:
        try:
            client.verify()
        except Exception as exc:
            return None, _failed_status(model_name, exc, configured=True)
        return client, LLMClientStatus(
            configured=True,
            verified=True,
            available=True,
            reason="openai client verified",
            model_name=model_name,
        )

    return client, LLMClientStatus(
        configured=True,
        verified=False,
        available=False,
        reason="openai_client_configured_unverified",
        model_name=model_name,
    )


def mark_llm_status_verified(status: LLMClientStatus) -> LLMClientStatus:
    """Mark a configured client as verified after a successful writer call."""

    return LLMClientStatus(
        configured=status.configured,
        verified=True,
        available=True,
        reason="openai client verified",
        model_name=status.model_name,
    )


def mark_llm_status_failed(status: LLMClientStatus, error: str) -> LLMClientStatus:
    """Mark a configured client as unavailable after a writer/auth/model failure."""

    return LLMClientStatus(
        configured=status.configured,
        verified=False,
        available=False,
        reason=_reason_from_error_text(error),
        model_name=status.model_name,
        last_error=error,
    )


def _failed_status(
    model_name: str,
    exc: Exception,
    *,
    configured: bool,
) -> LLMClientStatus:
    error = _format_exception(exc)
    return LLMClientStatus(
        configured=configured,
        verified=False,
        available=False,
        reason=_reason_from_exception(exc),
        model_name=model_name,
        last_error=error,
    )


def _format_exception(exc: Exception) -> str:
    return f"{type(exc).__name__}: {exc}"


def _reason_from_exception(exc: Exception) -> str:
    name = type(exc).__name__
    if name == "ImportError":
        return "openai_package_missing"
    return _reason_from_error_text(_format_exception(exc))


def _reason_from_error_text(error: str) -> str:
    lowered = error.lower()
    if "authenticationerror" in lowered or "incorrect api key" in lowered or "401" in lowered:
        return "invalid_api_key"
    if ":" in error:
        return error.split(":", 1)[0]
    return error or "llm_error"
