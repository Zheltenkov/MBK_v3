"""Debt signal extraction for dialogue_v3 turns."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from .need import detect_need_intent, set_need_signal
from .post_terminal import BANKRUPTCY_CLARIFICATION_PATTERNS
from .text import contains_any

if TYPE_CHECKING:
    from ..state import DialogueV3State

MFO_PATTERNS = (
    r"(?<![а-яёa-z])м\s*ф\s*о(?![а-яёa-z])",
    r"(?<![а-яёa-z])микро\s*займ[а-яё]*(?![а-яёa-z])",
    r"(?<![а-яёa-z])займ\s+до\s+зарплат[а-яё]*(?![а-яёa-z])",
)
CREDIT_CARD_LOAN_TYPE_PATTERNS = (
    r"\bкредитн\w*\s+карт\w*\b",
    r"\bкредитк\w*\b",
    r"\bпо\s+\w*\s*карт\w*\b",
    r"\bзакрыть\s+\w*\s*карт\w*\b",
    r"\bпогасить\s+\w*\s*карт\w*\b",
)
DEBT_WORD_PATTERNS = ("кредит", "кредиты", "карты", "долг", "долги", "займ")
COLLECTOR_PATTERNS = ("коллектор",)
ARREARS_PATTERNS = ("просроч", "не плачу", "пропустил", "пропустила")
NO_ARREARS_PATTERNS = ("просрочек нет", "без просрочек")
HIGH_LOAD_PATTERNS = (
    "нагрузка",
    "платежи большие",
    "платить тяжело",
    "платежи тяжело тянуть",
    "тяжело тянуть",
)
WANTS_TO_PAY_PATTERNS = ("хочу платить", "не списывать", "законный график")
BANKRUPTCY_FEAR_PATTERNS = (
    "банкротство не хочу",
    "банкротство пугает",
    "боюсь банкротства",
)
MFO_RATING_CONCERN_PATTERNS = (
    "мфо портит рейтинг",
    "мфо портят рейтинг",
    "окб это видит",
    "бюро видит мфо",
    "займы портят кредитную историю",
    "займы портят рейтинг",
    "портит кредитную историю",
)
DEBT_PROCEDURE_HARD_REFUSAL_PATTERNS = (
    "банкротство не рассматриваю",
    "никаких судов",
    "суды не рассматриваю",
    "юридические процедуры не хочу",
    "никаких процедур",
    "не хочу никакие процедуры",
    "никакого банкротства и реструктуризации",
    "не хочу юридический разбор долгов",
)


def extract_debt_signals(
    text: str,
    facts: dict[str, Any],
    concerns: list[str],
    state: DialogueV3State | None = None,
) -> None:
    """Extract debt pressure and client-position signals."""

    last_slot = _last_asked_slot(state)
    _extract_dependents_context(text, facts, last_slot)
    _extract_previous_debt_procedure(text, facts, last_slot)

    mfo_signal = has_mfo_signal(text)
    if contains_any(text, DEBT_WORD_PATTERNS) or mfo_signal:
        facts["has_current_loans"] = True

    if has_credit_card_loan_type_signal(text):
        facts["has_current_loans"] = True
        facts["loan_types_known"] = True
        facts["loan_types"] = ("credit_cards",)

    if mfo_signal:
        facts["has_mfo"] = True
        facts["loan_types_known"] = True
        set_need_signal(facts, "debt_solution")

    if contains_any(text, NO_ARREARS_PATTERNS):
        facts["has_arrears"] = False
    elif contains_any(text, ARREARS_PATTERNS):
        facts["has_arrears"] = True
        arrears_months = _extract_month_count(text)
        if arrears_months is not None:
            facts["arrears_months"] = arrears_months

    if contains_any(text, COLLECTOR_PATTERNS):
        facts["collector_pressure"] = True

    if contains_any(text, HIGH_LOAD_PATTERNS):
        facts["high_payment_load"] = True

    if contains_any(text, WANTS_TO_PAY_PATTERNS):
        facts["client_wants_to_pay"] = True
        set_need_signal(facts, "debt_solution")
    if contains_any(text, BANKRUPTCY_FEAR_PATTERNS):
        facts["client_fears_bankruptcy"] = True
        concerns.append("bankruptcy_fear")
    if contains_any(text, BANKRUPTCY_CLARIFICATION_PATTERNS):
        facts["bankruptcy_clarification_question"] = True
        concerns.append("bankruptcy_clarification_question")
    if contains_any(text, MFO_RATING_CONCERN_PATTERNS):
        facts["mfo_rating_concern"] = True
        facts["credit_bureau_objection"] = True
        concerns.append("mfo_rating_concern")
    if contains_any(text, DEBT_PROCEDURE_HARD_REFUSAL_PATTERNS):
        facts["client_refuses_debt_procedure"] = True

    need_intent = detect_need_intent(text)
    if (
        need_intent.debt_solution
        or mfo_signal
        or contains_any(text, ("коллектор", "банкрот", "долг", "долги"))
    ):
        facts["need_type"] = "debt_solution"
    elif need_intent.payment_reduction:
        facts["need_type"] = "payment_reduction"
    elif need_intent.strong_new_money:
        facts["need_type"] = "new_money"


def has_mfo_signal(text: str) -> bool:
    return any(re.search(pattern, text) for pattern in MFO_PATTERNS)


def has_credit_card_loan_type_signal(text: str) -> bool:
    return any(re.search(pattern, text) for pattern in CREDIT_CARD_LOAN_TYPE_PATTERNS)


def _extract_month_count(text: str) -> float | None:
    if re.search(r"\bпар[ау]\b.{0,20}\bмесяц", text):
        return 2.0
    if re.search(r"\b(?:два|две|двух)\b.{0,20}\bмесяц", text):
        return 2.0
    if re.search(r"\bодин\b.{0,20}\bмесяц", text):
        return 1.0
    match = re.search(r"(\d+(?:[,.]\d+)?)\s*(месяц|месяца|месяцев)", text)
    if not match:
        if re.search(r"\bмесяц(?:а|ев)?\b", text):
            return 1.0
        return None
    return float(match.group(1).replace(",", "."))


def _extract_dependents_context(
    text: str,
    facts: dict[str, Any],
    last_slot: str | None,
) -> None:
    if last_slot != "bfl_dependents_context" and "иждив" not in text:
        return
    if contains_any(text, ("иждивенцев нет", "нет иждивенцев", "никого на иждивении")):
        facts["has_dependents"] = False
        facts["bfl_dependents_context_known"] = True
        return
    if "иждив" not in text and last_slot != "bfl_dependents_context":
        return
    facts["has_dependents"] = True
    count = _extract_dependents_count(text)
    if count is not None:
        facts["dependents_count"] = count
    relation = _extract_dependent_relation(text)
    if relation is not None:
        facts["dependent_relation"] = relation
    if count is not None or relation is not None:
        facts["bfl_dependents_context_known"] = True


def _extract_previous_debt_procedure(
    text: str,
    facts: dict[str, Any],
    last_slot: str | None,
) -> None:
    has_procedure_words = contains_any(text, ("банкрот", "реструктуризац"))
    has_previous_context = contains_any(text, ("раньше", "ранее", "до этого", "предыдущ"))
    if last_slot != "previous_debt_procedure" and not (has_procedure_words and has_previous_context):
        return
    if not has_procedure_words:
        return
    negative = contains_any(
        text,
        (
            "не было",
            "не проходил",
            "не проходила",
            "раньше не",
            "ранее не",
            "до этого не",
        ),
    )
    positive = contains_any(
        text,
        (
            "было банкротство",
            "была реструктуризация",
            "проходил банкротство",
            "проходила банкротство",
            "проходил реструктуризацию",
            "проходила реструктуризацию",
        ),
    )
    if negative and not positive:
        facts["previous_debt_procedure"] = False
        facts["previous_bankruptcy"] = False
        facts["previous_restructuring"] = False
    elif positive:
        facts["previous_debt_procedure"] = True
        if "банкрот" in text:
            facts["previous_bankruptcy"] = True
        if "реструктуризац" in text:
            facts["previous_restructuring"] = True


def _extract_dependents_count(text: str) -> int | None:
    match = re.search(r"(\d+)\s+(?:иждивен|человек|дет)", text)
    if match:
        return int(match.group(1))
    if contains_any(text, ("один иждивен", "одна иждивен")):
        return 1
    if contains_any(text, ("двое", "два иждивен", "две иждивен")):
        return 2
    return None


def _extract_dependent_relation(text: str) -> str | None:
    if contains_any(text, ("мама", "мать", "матери")):
        return "mother"
    if contains_any(text, ("отец", "папа")):
        return "father"
    if contains_any(text, ("ребен", "ребён", "дети", "дочь", "сын")):
        return "children"
    if contains_any(text, ("супруг", "супруга", "жена", "муж")):
        return "spouse"
    return None


def _last_asked_slot(state: DialogueV3State | None) -> str | None:
    if state is None:
        return None
    if state.asked_slots:
        return state.asked_slots[-1]
    route = getattr(state, "route", None)
    route_next_slot = getattr(route, "next_slot", None)
    return route_next_slot if isinstance(route_next_slot, str) else None
