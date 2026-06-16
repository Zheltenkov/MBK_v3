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
    model: str = "qwen/qwen3.7-max"
    # Молчаливый извлекатель JSON. Если пусто — берём ту же модель.
    extractor_model: str | None = None
    temperature: float = 0.7
    max_tokens: int = 5000
    # Явное кэширование статического префикса (персона+few-shots+знания).
    # Qwen 3.7-max и Anthropic-модели поддерживают cache_control. Если провайдер
    # не поддерживает — параметр игнорируется, ничего не ломает.
    enable_prompt_cache: bool = True
    # Маскировка ПД перед отправкой в зарубежные LLM (ФИО→только имя, телефон скрыт,
    # ДР→только год, адрес→только город). На нашем сервере хранится оригинал.
    enable_pii_masking: bool = True
    # Базовый URL OpenRouter (или совместимого шлюза). Меняется для прокси-шлюзов.
    base_url: str = "https://openrouter.ai/api/v1"
    # HTTP(S)-прокси для исходящих запросов к LLM. Пусто — берём из env HTTPS_PROXY/HTTP_PROXY.
    proxy_url: str | None = None
    # Таймаут запроса к модели, сек. Через прокси/иностранный VPS латентность выше.
    request_timeout: int = 120


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
        model=_read_env_value("OPENROUTER_MODEL") or "qwen/qwen3.7-max",
        extractor_model=_read_env_value("OPENROUTER_EXTRACTOR_MODEL"),
        temperature=float(_read_env_value("OPENROUTER_TEMPERATURE") or 0.7),
        max_tokens=int(_read_env_value("OPENROUTER_MAX_TOKENS") or 5000),
        enable_prompt_cache=(_read_env_value("OPENROUTER_PROMPT_CACHE") or "1") not in ("0", "false", "False", "no"),
        enable_pii_masking=(_read_env_value("ENABLE_PII_MASKING") or "1") not in ("0", "false", "False", "no"),
        base_url=(_read_env_value("OPENROUTER_BASE_URL") or "https://openrouter.ai/api/v1").rstrip("/"),
        proxy_url=_read_env_value("OPENROUTER_PROXY") or _read_env_value("HTTPS_PROXY") or _read_env_value("HTTP_PROXY"),
        request_timeout=int(_read_env_value("OPENROUTER_TIMEOUT") or 120),
    )
