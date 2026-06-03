"""
Учёт токенов и стоимости.

Подключается к llm_agent через usage_collector-колбэк (см. llm_agent.py). На каждый вызов
к OpenRouter (стрим разговорной модели и не-стрим извлекателя) ловим usage из ответа,
аккумулируем в SessionUsage и считаем стоимость по тарифной таблице PRICING.

PRICING выражено в USD за миллион токенов. Цифры — ориентировочные плейсхолдеры под
текущие тарифы OpenRouter; обнови, когда сверишься со страницей модели на openrouter.ai
(там цена видна прямо на карточке модели).
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from threading import Lock
from typing import Iterable


# USD за 1 000 000 токенов. Обновляй под актуальные тарифы.
# "cached_input" — ставка за чтение из кэша (обычно 10–25% от обычного input).
# Если не задана — берём input (консервативно, не занижаем стоимость).
# Если модели нет в таблице — стоимость не считается, но токены всё равно копятся.
PRICING_PER_MILLION_TOKENS: dict[str, dict[str, float]] = {
    "qwen/qwen3.7-max":          {"input": 3.00,  "output": 9.00,  "cached_input": 0.60},
    "qwen/qwen3.6-plus":         {"input": 1.20,  "output": 3.50,  "cached_input": 0.24},
    "anthropic/claude-opus-4.7": {"input": 15.00, "output": 75.00, "cached_input": 1.50},
    "anthropic/claude-haiku-4.5":{"input": 0.80,  "output": 4.00,  "cached_input": 0.08},
    "deepseek/deepseek-v4-pro":  {"input": 0.27,  "output": 1.10,  "cached_input": 0.027},
    "openai/gpt-5.4-mini":       {"input": 0.15,  "output": 0.60,  "cached_input": 0.015},
}


@dataclass
class UsageEvent:
    model: str
    role: str  # "conversation" | "extraction" | "opening" | "other"
    prompt_tokens: int
    completion_tokens: int
    cached_tokens: int
    total_tokens: int
    cost_usd: float
    at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


def _compute_cost_usd(model: str, prompt_tokens: int, completion_tokens: int, cached_tokens: int = 0) -> float:
    rates = PRICING_PER_MILLION_TOKENS.get(model)
    if not rates:
        return 0.0
    cached = max(0, min(int(cached_tokens or 0), int(prompt_tokens or 0)))
    fresh_input = int(prompt_tokens or 0) - cached
    cached_rate = rates.get("cached_input", rates["input"])
    return (
        fresh_input * rates["input"]
        + cached * cached_rate
        + int(completion_tokens or 0) * rates["output"]
    ) / 1_000_000


@dataclass
class SessionUsage:
    """Аккумулятор расхода для одной сессии."""
    session_id: str
    events: list[UsageEvent] = field(default_factory=list)
    _lock: Lock = field(default_factory=Lock, repr=False)

    def add(self, model: str, role: str, prompt_tokens: int, completion_tokens: int, cached_tokens: int = 0) -> UsageEvent:
        cost = _compute_cost_usd(model, prompt_tokens, completion_tokens, cached_tokens)
        event = UsageEvent(
            model=model,
            role=role,
            prompt_tokens=int(prompt_tokens or 0),
            completion_tokens=int(completion_tokens or 0),
            cached_tokens=int(cached_tokens or 0),
            total_tokens=int((prompt_tokens or 0) + (completion_tokens or 0)),
            cost_usd=cost,
        )
        with self._lock:
            self.events.append(event)
        return event

    def collector(self, role: str):
        """Возвращает callback под llm_agent (model, prompt_tokens, completion_tokens, cached_tokens)."""
        def _cb(model: str, prompt_tokens: int, completion_tokens: int, cached_tokens: int = 0) -> None:
            self.add(model, role, prompt_tokens, completion_tokens, cached_tokens)
        return _cb

    def summary(self) -> dict:
        with self._lock:
            events = list(self.events)
        by_role: dict[str, dict] = {}
        by_model: dict[str, dict] = {}
        total_input = total_output = total_cached = 0
        total_cost = 0.0
        for ev in events:
            for bucket, key in ((by_role, ev.role), (by_model, ev.model)):
                slot = bucket.setdefault(key, {"prompt_tokens": 0, "completion_tokens": 0, "cached_tokens": 0, "cost_usd": 0.0, "calls": 0})
                slot["prompt_tokens"] += ev.prompt_tokens
                slot["completion_tokens"] += ev.completion_tokens
                slot["cached_tokens"] += ev.cached_tokens
                slot["cost_usd"] += ev.cost_usd
                slot["calls"] += 1
            total_input += ev.prompt_tokens
            total_output += ev.completion_tokens
            total_cached += ev.cached_tokens
            total_cost += ev.cost_usd
        return {
            "session_id": self.session_id,
            "total_calls": len(events),
            "total_input_tokens": total_input,
            "total_output_tokens": total_output,
            "total_cached_tokens": total_cached,
            "cache_hit_ratio": round(total_cached / total_input, 3) if total_input else 0.0,
            "total_tokens": total_input + total_output,
            "total_cost_usd": round(total_cost, 6),
            "by_role": {k: _round_costs(v) for k, v in by_role.items()},
            "by_model": {k: _round_costs(v) for k, v in by_model.items()},
        }


def _round_costs(slot: dict) -> dict:
    slot = dict(slot)
    slot["cost_usd"] = round(slot["cost_usd"], 6)
    return slot


def aggregate(usages: Iterable[SessionUsage]) -> dict:
    """Свёртка по нескольким сессиям — для глобальных дашбордов."""
    total = {"sessions": 0, "calls": 0, "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0}
    for u in usages:
        s = u.summary()
        total["sessions"] += 1
        total["calls"] += s["total_calls"]
        total["input_tokens"] += s["total_input_tokens"]
        total["output_tokens"] += s["total_output_tokens"]
        total["cost_usd"] += s["total_cost_usd"]
    total["cost_usd"] = round(total["cost_usd"], 6)
    return total


# Глобальная функция для конфигурации PRICING из переменных окружения, если хочется
# обновлять цены без правок кода (опционально, можно не использовать).
def override_pricing_from_env(prefix: str = "PRICE_") -> None:
    """Формат: PRICE_qwen_qwen3_7_max_INPUT=3.0 / PRICE_qwen_qwen3_7_max_OUTPUT=9.0"""
    for key, value in os.environ.items():
        if not key.startswith(prefix) or not (key.endswith("_INPUT") or key.endswith("_OUTPUT")):
            continue
        try:
            direction = "input" if key.endswith("_INPUT") else "output"
            model_key = key[len(prefix):-len("_INPUT") if direction == "input" else -len("_OUTPUT")]
            # PRICE_qwen_qwen3_7_max → "qwen/qwen3.7-max"
            model = model_key.replace("_", "/", 1).replace("_", "-")
            PRICING_PER_MILLION_TOKENS.setdefault(model, {"input": 0.0, "output": 0.0})
            PRICING_PER_MILLION_TOKENS[model][direction] = float(value)
        except (ValueError, IndexError):
            continue
