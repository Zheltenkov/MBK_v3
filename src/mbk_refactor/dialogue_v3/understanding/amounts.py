"""Amount, payment, and income extraction for dialogue_v3 turns."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from .debt import has_mfo_signal
from .need import DEBT_SOLUTION_PATTERNS, MONEY_REQUEST_PATTERNS
from .text import ACTIVE_DIALOG_CORRECTION_PATTERNS, contains_any

if TYPE_CHECKING:
    from ..state import DialogueV3State

NO_STABLE_INCOME_PATTERNS = ("дохода стабильного нет", "нет стабильного дохода")
NO_INCOME_PATTERNS = ("дохода нет", "нет дохода", "без дохода")
NO_OFFICIAL_INCOME_PATTERNS = (
    "официального дохода нет",
    "неофициальный доход",
    "неофициально",
    "не официально",
)
STABLE_INCOME_PATTERNS = ("официально", "работаю", "стабильный", "самозанят")

AMOUNT_PATTERN = re.compile(
    r"(\d+(?:[,.]\d+)?)\s*(млн|миллион|миллиона|миллионов|тыс|тысяч|к|руб|₽)?"
)
COMPOSITE_MILLION_THOUSAND_PATTERN = re.compile(
    r"(\d+(?:[,.]\d+)?)\s*(млн|миллион|миллиона|миллионов)\s+"
    r"(\d+(?:[,.]\d+)?)\s*(тыс|тысяч|к)\b"
)
AMOUNT_RANGE_PATTERN = re.compile(
    r"(\d+(?:[,.]\d+)?)\s*[-–—]\s*(\d+(?:[,.]\d+)?)\s*"
    r"(млн|миллион|миллиона|тыс|тысяч|к|руб|₽)?"
)
WORD_NUMBER_VALUES = {
    "один": 1,
    "одна": 1,
    "два": 2,
    "две": 2,
    "три": 3,
    "четыре": 4,
    "пять": 5,
    "шесть": 6,
    "семь": 7,
    "восемь": 8,
    "девять": 9,
    "десять": 10,
    "одиннадцать": 11,
    "двенадцать": 12,
    "тринадцать": 13,
    "четырнадцать": 14,
    "пятнадцать": 15,
    "шестнадцать": 16,
    "семнадцать": 17,
    "восемнадцать": 18,
    "девятнадцать": 19,
    "двадцать": 20,
    "тридцать": 30,
    "сорок": 40,
    "пятьдесят": 50,
    "шестьдесят": 60,
    "семьдесят": 70,
    "восемьдесят": 80,
    "девяносто": 90,
    "сто": 100,
    "двести": 200,
    "триста": 300,
    "четыреста": 400,
    "пятьсот": 500,
    "шестьсот": 600,
    "семьсот": 700,
    "восемьсот": 800,
    "девятьсот": 900,
}
WORD_MILLION_UNITS = {"миллион", "миллиона", "миллионов"}
WORD_THOUSAND_UNITS = {"тысяча", "тысячи", "тысяч"}


def extract_amounts_with_context(
    text: str,
    facts: dict[str, Any],
    state: DialogueV3State | None = None,
) -> None:
    """Extract monetary facts using local keywords plus previous asked-slot context."""

    last_slot = get_last_asked_slot(state)

    total_debt = _find_total_debt_amount(text, last_slot)
    if total_debt is not None:
        facts["total_debt"] = total_debt

    if _looks_like_payment_label_correction(text):
        monthly_payments = _first_contextual_amount(text)
        if monthly_payments is not None:
            facts["monthly_payments"] = _scale_short_payment_amount(monthly_payments)

    if _can_extract_monthly_payment(text, last_slot):
        monthly_payments = _find_amount_near(text, ("плачу", "платеж", "платежи"))
        if monthly_payments is None and last_slot == "monthly_payments":
            monthly_payments = _first_contextual_amount(text)
        elif monthly_payments is None and contains_any(text, ("в месяц", "ежемесячно")):
            monthly_payments = _first_contextual_amount(text)
        if monthly_payments is not None:
            facts["monthly_payments"] = _scale_short_payment_amount(monthly_payments)

    comfortable_payment = _find_amount_near(text, ("комфортно", "комфортнее", "комфортный", "могу платить"))
    if comfortable_payment is None and _is_comfortable_payment_context(text, last_slot):
        comfortable_payment = _first_contextual_amount(text)
    if comfortable_payment is not None:
        facts["comfortable_payment"] = _scale_short_payment_amount(comfortable_payment)

    _extract_income_amount(text, facts, last_slot)

    desired_amount = _find_desired_amount(text, last_slot)
    if desired_amount is not None:
        facts["desired_amount"] = desired_amount


def _find_total_debt_amount(text: str, last_slot: str | None) -> int | None:
    corrected_total_debt = _corrected_total_debt_amount(text)
    if corrected_total_debt is not None:
        return corrected_total_debt

    total_debt = _find_debt_amount_in_local_clause(text)
    if total_debt is None and last_slot in {"total_debt", "desired_amount_or_total_debt"}:
        total_debt = _first_contextual_amount(text)
    if total_debt is None and _looks_like_standalone_total_debt(text):
        total_debt = _first_contextual_amount(text)
    return total_debt


def _corrected_total_debt_amount(text: str) -> int | None:
    if not contains_any(text, ("долг", "долги", "задолж")):
        return None
    match = re.search(
        r"\b(?:долг\w*|задолж\w*)\b.{0,80}?"
        r"\bне\s+(\d+(?:[,.]\d+)?)\s*(млн|миллион|миллиона|миллионов|тыс|тысяч|к|руб|₽)?"
        r".{0,40}?\bа\s+(\d+(?:[,.]\d+)?)\s*(млн|миллион|миллиона|миллионов|тыс|тысяч|к|руб|₽)?",
        text,
    )
    if match is None:
        return None
    previous_unit = match.group(2)
    corrected_unit = match.group(4) or previous_unit
    return _parse_amount(match.group(3), corrected_unit)


def _find_debt_amount_in_local_clause(text: str) -> int | None:
    for keyword in ("долг", "задолж"):
        for match in re.finditer(re.escape(keyword), text):
            clause = _sentence_clause_around(text, match.start())
            if _debt_clause_is_payment_label(clause):
                continue
            amount = _first_amount(clause)
            if amount is not None:
                return amount
    return None


def _sentence_clause_around(text: str, index: int) -> str:
    start = max(text.rfind(".", 0, index), text.rfind("?", 0, index), text.rfind("!", 0, index))
    end_candidates = [position for position in (text.find(".", index), text.find("?", index), text.find("!", index)) if position != -1]
    end = min(end_candidates) if end_candidates else len(text)
    return text[start + 1 : end]


def _debt_clause_is_payment_label(text: str) -> bool:
    return bool(
        contains_any(text, ("платеж", "платежи", "плачу", "уходит", "выходит"))
        and contains_any(text, ("долг", "долги", "долгам", "кредит", "кредитам"))
        and not contains_any(text, ("общий долг", "сумма долга", "всего долг", "всего долгов", "задолженность"))
    )


def _derive_payment_load(facts: dict[str, Any]) -> None:
    monthly = facts.get("monthly_payments")
    official_income = facts.get("official_income")
    comfortable = facts.get("comfortable_payment")
    if isinstance(monthly, int) and isinstance(official_income, int) and official_income > 0:
        facts["high_payment_load"] = monthly / official_income >= 0.5
    if isinstance(monthly, int) and isinstance(comfortable, int):
        facts["payment_gap_large"] = monthly > comfortable * 1.5


derive_payment_load = _derive_payment_load


def get_last_asked_slot(state: DialogueV3State | None) -> str | None:
    """Return the last slot the assistant asked for, without selecting a route."""

    if state is None:
        return None
    if state.asked_slots:
        return state.asked_slots[-1]
    route = getattr(state, "route", None)
    route_next_slot = getattr(route, "next_slot", None)
    if isinstance(route_next_slot, str):
        return route_next_slot
    if state.trace_history:
        last_trace = state.trace_history[-1]
        actor_move = last_trace.get("actor_move")
        if isinstance(actor_move, dict):
            actor_next_slot = actor_move.get("next_slot")
            if isinstance(actor_next_slot, str):
                return actor_next_slot
        next_slot = last_trace.get("next_slot")
        if isinstance(next_slot, str):
            return next_slot
    return None


def _extract_income_amount(text: str, facts: dict[str, Any], last_slot: str | None) -> None:
    if contains_any(text, NO_STABLE_INCOME_PATTERNS):
        facts["income_status"] = "unstable"
        return
    if contains_any(text, NO_OFFICIAL_INCOME_PATTERNS):
        facts["income_status"] = "no_official_income"
        return
    if contains_any(text, NO_INCOME_PATTERNS):
        facts["income_status"] = "none"
        return

    if _corrected_total_debt_amount(text) is not None and not _has_explicit_income_context(text):
        return

    if not _can_extract_official_income(text, last_slot):
        return

    income = _find_amount_near(text, ("доход", "заработ", "получаю"))
    if income is None and (
        last_slot == "income_status" or contains_any(text, STABLE_INCOME_PATTERNS)
    ):
        income = _first_contextual_amount(text)
    if income is not None:
        if income < 1_000 and (last_slot == "income_status" or contains_any(text, STABLE_INCOME_PATTERNS)):
            income *= 1_000
        facts["official_income"] = income
        facts["income_status"] = "stable"
    elif last_slot == "income_status" and contains_any(text, STABLE_INCOME_PATTERNS):
        facts["income_status"] = "stable"


def _find_desired_amount(text: str, last_slot: str | None) -> int | None:
    if last_slot == "desired_amount":
        return _first_contextual_amount(text)
    if not contains_any(text, MONEY_REQUEST_PATTERNS + ("нужно", "нужна сумма", "сумма нужна")):
        return None
    if contains_any(text, DEBT_SOLUTION_PATTERNS) and not contains_any(text, ("на руки", "получить сумму", "нужна сумма")):
        return None
    return _find_amount_near(text, ("нужн", "сумма", "деньги", "получить", "на руки", "взять"))


def _has_income_context(text: str, last_slot: str | None) -> bool:
    return bool(
        last_slot == "income_status"
        or contains_any(text, ("доход", "заработ", "зарплат", "получаю"))
        or contains_any(text, STABLE_INCOME_PATTERNS)
        or contains_any(text, NO_STABLE_INCOME_PATTERNS + NO_OFFICIAL_INCOME_PATTERNS + NO_INCOME_PATTERNS)
    )


def _has_explicit_income_context(text: str) -> bool:
    return bool(
        contains_any(text, ("доход", "заработ", "зарплат", "получаю"))
        or contains_any(text, STABLE_INCOME_PATTERNS)
        or contains_any(text, NO_STABLE_INCOME_PATTERNS + NO_OFFICIAL_INCOME_PATTERNS + NO_INCOME_PATTERNS)
    )


def _has_monthly_payment_context(text: str, last_slot: str | None) -> bool:
    return bool(
        last_slot == "monthly_payments"
        or contains_any(text, ("плачу", "платеж", "платежи", "в месяц", "ежемесячно"))
    )


def _can_extract_monthly_payment(text: str, last_slot: str | None) -> bool:
    monthly_context = _has_monthly_payment_context(text, last_slot)
    if not monthly_context:
        return False
    if last_slot in {"income_status", "comfortable_payment"}:
        return False
    explicit_payment_context = contains_any(text, ("плачу", "платеж", "платежи"))
    if last_slot != "monthly_payments" and _has_income_context(text, last_slot) and not explicit_payment_context:
        return False
    return True


def _looks_like_payment_label_correction(text: str) -> bool:
    return bool(
        contains_any(
            text,
            (
                "это платеж",
                "это платежи",
                "это выплаты",
                "это ежемесячный платеж",
                "это ежемесячные платежи",
            ),
        )
        and contains_any(text, ("платеж", "платежи", "выплаты", "по долгам", "по кредитам"))
    )


def _can_extract_official_income(text: str, last_slot: str | None) -> bool:
    income_context = _has_income_context(text, last_slot)
    if not income_context:
        return False
    if last_slot == "monthly_payments" and _has_monthly_payment_context(text, last_slot):
        return False
    return True


def _is_comfortable_payment_context(text: str, last_slot: str | None) -> bool:
    if last_slot == "comfortable_payment" and not _looks_like_payment_correction(text):
        return True
    return contains_any(text, ("нормально", "нормальный платеж", "нормально было бы"))


def _looks_like_payment_correction(text: str) -> bool:
    return bool(
        contains_any(text, ACTIVE_DIALOG_CORRECTION_PATTERNS)
        and (
            contains_any(text, ("платеж", "платежи", "плачу", "в месяц"))
            or contains_any(text, ("по карте", "по картам", "по кредиту", "по кредитам"))
        )
    )


def _find_amount_near(text: str, keywords: tuple[str, ...]) -> int | None:
    for keyword in keywords:
        index = text.find(keyword)
        if index == -1:
            continue
        window = text[index : index + 80]
        composite_amount = _first_composite_amount(window)
        if composite_amount is not None:
            return composite_amount
        range_amount = _first_contextual_amount_range(window)
        if range_amount is not None:
            return range_amount
        match = AMOUNT_PATTERN.search(window)
        if match:
            return _parse_amount(match.group(1), match.group(2))
    return None


def _scale_short_payment_amount(amount: int) -> int:
    return amount * 1_000 if 0 < amount < 1_000 else amount


def _first_contextual_amount(text: str) -> int | None:
    return _first_amount(text)


def _first_amount(text: str) -> int | None:
    composite_amount = _first_composite_amount(text)
    if composite_amount is not None:
        return composite_amount
    range_amount = _first_contextual_amount_range(text)
    if range_amount is not None:
        return range_amount
    word_amount = _first_word_amount(text)
    if word_amount is not None:
        return word_amount
    for match in AMOUNT_PATTERN.finditer(text):
        if match.group(2) is None and _is_month_duration_after(text, match.end()):
            continue
        return _parse_amount(match.group(1), match.group(2))
    return None


def _first_composite_amount(text: str) -> int | None:
    match = COMPOSITE_MILLION_THOUSAND_PATTERN.search(text)
    if match is None:
        return None
    million_part = _parse_amount(match.group(1), match.group(2))
    thousand_part = _parse_amount(match.group(3), match.group(4))
    return million_part + thousand_part


def _first_contextual_amount_range(text: str) -> int | None:
    match = AMOUNT_RANGE_PATTERN.search(text)
    if match is None:
        return None
    return _parse_amount(match.group(2), match.group(3))


def _is_month_duration_after(text: str, position: int) -> bool:
    return re.match(r"\s*(месяц|месяца|месяцев)\b", text[position:]) is not None


def _looks_like_standalone_total_debt(text: str) -> bool:
    if not re.search(r"\d", text):
        return False
    if _looks_like_payment_label_correction(text):
        return False
    return bool(
        has_mfo_signal(text)
        or contains_any(text, ("долг", "долги", "задолженность"))
    )


def _first_word_amount(text: str) -> int | None:
    tokens = re.findall(r"[а-я]+", text)
    if not tokens:
        return None

    for index, token in enumerate(tokens):
        if token in WORD_MILLION_UNITS:
            million_count = _parse_word_number(tokens[max(0, index - 3) : index]) or 1
            tail_value = _parse_amount_tail_after_million(tokens[index + 1 :])
            return million_count * 1_000_000 + tail_value

    for index, token in enumerate(tokens):
        if token in WORD_THOUSAND_UNITS:
            thousand_count = _parse_word_number(tokens[max(0, index - 3) : index])
            if thousand_count:
                return thousand_count * 1_000
    return None


def _parse_amount_tail_after_million(tokens: list[str]) -> int:
    if not tokens:
        return 0
    for index, token in enumerate(tokens):
        if token in WORD_THOUSAND_UNITS:
            thousand_count = _parse_word_number(tokens[:index])
            return (thousand_count or 0) * 1_000
    short_thousand_count = _parse_word_number(tokens[:3])
    if short_thousand_count is None:
        return 0
    return short_thousand_count * 1_000 if short_thousand_count < 1_000 else short_thousand_count


def _parse_word_number(tokens: list[str]) -> int | None:
    total = 0
    for token in tokens:
        value = WORD_NUMBER_VALUES.get(token)
        if value is None:
            continue
        total += value
    return total or None


def _parse_amount(number: str, unit: str | None) -> int:
    value = float(number.replace(",", "."))
    if unit in {"млн", "миллион", "миллиона", "миллионов"}:
        value *= 1_000_000
    elif unit in {"тыс", "тысяч", "к"}:
        value *= 1_000
    return int(value)
