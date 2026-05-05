"""Need-level semantic observations for dialogue_v3 turns."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from .text import contains_any, matches_any_regex

MONEY_REQUEST_PATTERNS = (
    "хочу взять денег",
    "нужны деньги",
    "деньги нужны",
    "получить сумму",
    "сумму на руки",
    "хочу кредит",
    "нужна сумма",
)
STRONG_NEW_MONEY_PATTERNS = (
    "получить сумму",
    "получить деньги на руки",
    "сумму на руки",
    "деньги на руки",
    "нужна сумма на руки",
    "нужны деньги на руки",
)
DEBT_SOLUTION_PATTERNS = (
    "закрыть карты",
    "закрыть карту",
    "закрыть кредитные карты",
    "закрыть кредитную карту",
    "закрыть кредитки",
    "закрыть кредитку",
    "погасить карты",
    "закрыть кредиты",
    "закрыть кредит",
    "закрыть долги",
    "закрыть долг",
    "перекрыть долги",
    "перекрыть долг",
    "погасить кредитки",
    "объединить кредиты",
    "рефинансироваться",
)
PAYMENT_REDUCTION_PATTERNS = (
    "снизить платеж",
    "снизить ежемесячный платеж",
    "уменьшить платеж",
    "уменьшить ежемесячный платеж",
    "снизить нагрузку",
    "уменьшить нагрузку",
    "платеж меньше",
    "платежи тяжело тянуть",
    "тяжело тянуть платеж",
    "платить тяжело",
    "не вывожу платежи",
    "не вывожу кредиты",
    "не вывожу долги",
)
REPAIR_PURPOSE_PATTERNS = ("ремонт",)

NEED_SIGNAL_PRIORITY = {
    "unknown": 0,
    "new_money": 1,
    "repair_or_purpose": 2,
    "payment_reduction": 3,
    "debt_solution": 4,
    "explicit_mortgage": 5,
    "explicit_pts": 5,
    "security": 6,
    "repeat": 6,
}
NEED_TYPE_BY_SIGNAL = {
    "new_money": "new_money",
    "payment_reduction": "payment_reduction",
    "debt_solution": "debt_solution",
    "security": "security",
}

DEBT_SOLUTION_REGEXES = (
    re.compile(
        r"\b(закрыть|погасить|перекрыть)\b.{0,50}"
        r"\b(кредитн\w*\s+карт\w*|карт\w*|кредитк\w*|кредит\w*|долг\w*)\b"
    ),
    re.compile(r"\b(объединить|рефинансир\w*)\b.{0,50}\b(кредит\w*|долг\w*|карт\w*)\b"),
    re.compile(r"\bрефинансироваться\b"),
)
PAYMENT_REDUCTION_REGEXES = (
    re.compile(r"\b(снизить|уменьшить)\b.{0,40}\b(платеж\w*|нагрузк\w*)\b"),
    re.compile(r"\b(тяжело|не вывожу)\b.{0,50}\b(платеж\w*|кредит\w*|долг\w*)\b"),
)


@dataclass(frozen=True)
class NeedIntentResult:
    """Turn-local semantic observations about the client's need."""

    need_type: str | None = None
    early_need_signal: str | None = None
    purpose_goal: str | None = None
    debt_solution: bool = False
    payment_reduction: bool = False
    strong_new_money: bool = False
    generic_new_money: bool = False


def detect_need_intent(text: str) -> NeedIntentResult:
    """Detect need semantics without choosing a product route."""

    facts: dict[str, Any] = {}
    extract_need_signals(text, facts)
    return NeedIntentResult(
        need_type=_str_or_none(facts.get("need_type")),
        early_need_signal=_str_or_none(facts.get("early_need_signal")),
        purpose_goal=_str_or_none(facts.get("purpose_goal")),
        debt_solution=_is_debt_solution_need(text),
        payment_reduction=_is_payment_reduction_need(text),
        strong_new_money=_is_strong_new_money_need(text),
        generic_new_money=_is_generic_new_money_need(text),
    )


def extract_need_signals(text: str, facts: dict[str, Any]) -> None:
    """Extract broad need signals; priorities prevent weaker purpose words from overriding debt."""

    if _is_debt_solution_need(text):
        _set_need_signal(facts, "debt_solution")
    if _is_payment_reduction_need(text):
        _set_need_signal(facts, "payment_reduction")
    purpose_goal = _detect_purpose_goal(text)
    if purpose_goal is not None:
        facts["purpose_goal"] = purpose_goal
        _set_need_signal(facts, "repair_or_purpose")
    if _is_generic_new_money_need(text):
        if _is_strong_new_money_need(text):
            _set_need_signal(facts, "new_money")
        else:
            _set_early_need_signal(facts, "new_money")


def _detect_purpose_goal(text: str) -> str | None:
    if not contains_any(text, REPAIR_PURPOSE_PATTERNS):
        return None
    return "car_repair" if contains_any(text, ("ремонт машины", "ремонт авто")) else "repair"


def _is_debt_solution_need(text: str) -> bool:
    return contains_any(text, DEBT_SOLUTION_PATTERNS) or matches_any_regex(text, DEBT_SOLUTION_REGEXES)


def _is_payment_reduction_need(text: str) -> bool:
    return contains_any(text, PAYMENT_REDUCTION_PATTERNS) or matches_any_regex(text, PAYMENT_REDUCTION_REGEXES)


def _is_strong_new_money_need(text: str) -> bool:
    return contains_any(text, STRONG_NEW_MONEY_PATTERNS)


def _is_generic_new_money_need(text: str) -> bool:
    return contains_any(text, MONEY_REQUEST_PATTERNS)


def _set_need_signal(facts: dict[str, Any], signal: str) -> None:
    _set_early_need_signal(facts, signal)
    need_type = NEED_TYPE_BY_SIGNAL.get(signal)
    if need_type:
        facts["need_type"] = need_type


def _set_early_need_signal(facts: dict[str, Any], signal: str) -> None:
    current = str(facts.get("early_need_signal") or "unknown")
    if NEED_SIGNAL_PRIORITY.get(signal, 0) >= NEED_SIGNAL_PRIORITY.get(current, 0):
        facts["early_need_signal"] = signal


def _str_or_none(value: Any) -> str | None:
    return value if isinstance(value, str) else None


set_need_signal = _set_need_signal
set_early_need_signal = _set_early_need_signal
