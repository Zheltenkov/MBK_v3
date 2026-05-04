"""Optional LLM client adapters for dialogue_v3 actor writer."""

from __future__ import annotations

import os
from dataclasses import dataclass

from .actor_writer import LLMClient


@dataclass(frozen=True)
class LLMClientStatus:
    available: bool
    reason: str
    model_name: str


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


def build_optional_llm_client(model_name: str) -> tuple[LLMClient | None, LLMClientStatus]:
    """Build an optional LLM client without making deterministic mode depend on it."""

    api_key = os.getenv("MBK_OPENAI_API_KEY") or os.getenv("OPENAI_API_KEY")
    if not api_key:
        return None, LLMClientStatus(
            available=False,
            reason="OPENAI_API_KEY/MBK_OPENAI_API_KEY is not set",
            model_name=model_name,
        )
    try:
        return OpenAIChatLLMClient(model_name=model_name, api_key=api_key), LLMClientStatus(
            available=True,
            reason="openai client configured",
            model_name=model_name,
        )
    except Exception as exc:
        return None, LLMClientStatus(
            available=False,
            reason=str(exc),
            model_name=model_name,
        )
