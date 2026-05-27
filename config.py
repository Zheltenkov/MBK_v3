from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env")


@dataclass(frozen=True)
class AppConfig:
    """Runtime configuration for the local assistant app."""

    openrouter_api_key: str
    # Разговорная модель (видит клиент). Лучше быструю чат-модель, НЕ reasoning.
    model: str = "deepseek/deepseek-v4-pro"
    # Молчаливый извлекатель JSON. Если пусто — берём ту же модель.
    extractor_model: str | None = None
    temperature: float = 0.7
    max_tokens: int = 1800


def _read_env_value(name: str) -> str | None:
    value = os.getenv(name) or os.getenv(f"$env:{name}")
    return value.strip() if value else None


def load_config() -> AppConfig:
    """Load OpenRouter config from .env with explicit validation."""
    key = _read_env_value("OPEN_ROUTER_API_KEY") or _read_env_value("OPENROUTER_API_KEY")
    if not key:
        raise ValueError("OPEN_ROUTER_API_KEY не найден в .env")
    if not key.startswith("sk-or-"):
        raise ValueError("OPEN_ROUTER_API_KEY не похож на ключ OpenRouter")

    return AppConfig(
        openrouter_api_key=key,
        model=_read_env_value("OPENROUTER_MODEL") or "deepseek/deepseek-v4-pro",
        extractor_model=_read_env_value("OPENROUTER_EXTRACTOR_MODEL"),
        temperature=float(_read_env_value("OPENROUTER_TEMPERATURE") or 0.7),
        max_tokens=int(_read_env_value("OPENROUTER_MAX_TOKENS") or 1800),
    )
