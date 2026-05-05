"""Deterministic response guard for actor writer output."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .actions import ActionEvent
from .constants import (
    AUTO_AUX,
    BFL_RD,
    BFL_RI,
    HANDOFF_BFL_SPECIALIST,
    HANDOFF_EXPERT,
    PTS,
    SELF_SERVE_LINKS_3,
    SELF_SERVE_LINKS_7,
    UNSECURED,
)
from .moves import ActorMove
from .safe_fallback import ActorWriterOutput

INTERNAL_WORDS = [
    "route",
    "scenario",
    "graph",
    "pipeline",
    "planner",
    "validator",
    "gate",
    "terminal",
    "action_id",
    "manual_review",
    BFL_RI,
    BFL_RD,
    AUTO_AUX,
    "слот",
    "пайплайн",
    "роутинг",
    "сценарий",
    "гейт",
    "валидатор",
]

INTERNAL_WORKFLOW_TERMS = [
    "ветка",
    "ветке",
    "ветку",
    "сбор данных",
    "дособерем данные",
    "этап сбора",
    "маршрут",
    "сценарий",
]

FORBIDDEN_CLAIMS = [
    "точно одобрят",
    "гарантированно одобрят",
    "точно спишут",
    "долги точно спишут",
    "риска нет",
    "без риска",
    "машина точно останется",
    "квартира точно не пострадает",
    "ставка будет",
    "имущество точно не затронут",
    "квартиру точно сохраните",
    "машину точно не затронут",
]

HANDOFF_LANGUAGE = [
    "передам",
    "передаю",
    "специалисту",
    "отправлю",
    "отправлю данные",
    "запущу проверку",
]

URL_PATTERN = re.compile(
    r"(https?://|www\.|t\.me/|wa\.me/|\b[a-z0-9-]+\.(?:ru|com|рф)\b)",
    re.IGNORECASE,
)

CODE_EXECUTION_MARKERS = [
    "```",
    "def ",
    "return ",
    "import ",
    "print(",
    "for ",
    "while ",
    "class ",
    "function ",
    "перевод:",
    "translation:",
]

PLAIN_ASK_SLOT_CANNED_PHRASES = [
    "чтобы не гадать",
    "не гадать вслепую",
    "важно понять",
    "без этой цифры",
    "сначала нужно",
    "по вашим данным",
    "это полезная опора",
    "дальше смотрим не",
]

TERMINAL_MOVE_TYPES = {
    "terminal_action",
    "security_action",
    "repeat_action",
    "no_solution_manual_review",
}


@dataclass(frozen=True)
class GuardIssue:
    code: str
    message: str


@dataclass(frozen=True)
class GuardValidation:
    accepted: bool
    issues: list[GuardIssue] = field(default_factory=list)
    repairable: bool = True

    @property
    def issue_codes(self) -> set[str]:
        return {issue.code for issue in self.issues}


class ResponseGuard:
    """Validate text safety without taking business decisions."""

    def validate(
        self,
        *,
        output: ActorWriterOutput,
        move: ActorMove,
        events: list[ActionEvent] | None = None,
    ) -> GuardValidation:
        issues: list[GuardIssue] = []
        text = output.text.strip()
        lowered = text.lower()

        if not text:
            issues.append(GuardIssue("empty_response", "assistant response must not be empty"))

        if text.count("?") > 1:
            issues.append(GuardIssue("too_many_questions", "response has more than one question"))

        if _question_goal_mismatch(output, move):
            issues.append(
                GuardIssue(
                    "question_goal_mismatch",
                    "follow-up question does not match the backend question goal",
                )
            )

        if _income_amount_invented_from_monthly_payment(output, move):
            issues.append(
                GuardIssue(
                    "income_amount_invented_from_monthly_payment",
                    "income question reused the known monthly payment as an income amount",
                )
            )

        for phrase in _plain_ask_slot_canned_phrases(output, move):
            issues.append(
                GuardIssue(
                    "plain_ask_slot_canned_phrase",
                    f"plain ask_slot contains canned justification: {phrase}",
                )
            )

        if _is_terminal_text_move(move):
            if output.followup_question.strip() or "?" in text:
                issues.append(
                    GuardIssue(
                        "terminal_followup_question",
                        "terminal response must not ask a follow-up question",
                    )
                )

        for word in INTERNAL_WORDS:
            if _contains_internal_word(lowered, word):
                issues.append(GuardIssue("internal_word", f"internal word is visible: {word}"))

        normalized_lowered = lowered.replace("ё", "е")
        for term in INTERNAL_WORKFLOW_TERMS:
            if _contains_workflow_term(normalized_lowered, term):
                issues.append(
                    GuardIssue(
                        "internal_workflow_term",
                        f"internal workflow term is visible: {term}",
                    )
                )

        for marker in FORBIDDEN_CLAIMS:
            if marker in lowered:
                issues.append(GuardIssue("forbidden_claim", f"forbidden claim marker: {marker}"))

        if move.terminal_action == HANDOFF_EXPERT and not _has_handoff_expert_next_step(lowered):
            issues.append(
                GuardIssue(
                    "handoff_next_step_missing",
                    "HANDOFF_EXPERT terminal text must explain the specialist next step",
                )
            )

        if move.terminal_action is None:
            for marker in HANDOFF_LANGUAGE:
                if marker in lowered:
                    if _allowed_recommendation_offer_handoff_language(move):
                        continue
                    if _allowed_post_terminal_specialist_reference(move, marker):
                        continue
                    issues.append(
                        GuardIssue(
                            "handoff_without_action",
                            f"handoff language without terminal action: {marker}",
                        )
                    )

        if move.terminal_action in {SELF_SERVE_LINKS_3, SELF_SERVE_LINKS_7} and _has_handoff_language(lowered):
            issues.append(
                GuardIssue(
                    "self_serve_handoff_language",
                    "self-serve terminal text must not describe a specialist handoff",
                )
            )

        if move.selected_route == UNSECURED and _has_vehicle_specific_specialist_check(lowered):
            issues.append(
                GuardIssue(
                    "unsecured_vehicle_handoff_language",
                    "UNSECURED text must not describe vehicle specialist checks",
                )
            )

        if _vehicle_specific_handoff_backend_mismatch(lowered, move, events):
            issues.append(
                GuardIssue(
                    "vehicle_handoff_backend_mismatch",
                    "vehicle specialist language must match a PTS handoff action or pending offer",
                )
            )

        if URL_PATTERN.search(text):
            issues.append(GuardIssue("url_invention", "response contains a URL"))

        if move.move_type == "handle_offtopic_then_ask":
            for marker in CODE_EXECUTION_MARKERS:
                if marker in lowered:
                    issues.append(
                        GuardIssue(
                            "offtopic_executed",
                            f"off-topic request appears to be executed: {marker}",
                        )
                    )

        if events is not None and move.terminal_action is not None:
            if not any(event.action_id == move.terminal_action for event in events):
                issues.append(
                    GuardIssue(
                        "missing_action_event",
                        "terminal action must produce a matching ActionEvent",
                    )
                )

        return GuardValidation(accepted=not issues, issues=issues)


def _contains_internal_word(lowered_text: str, word: str) -> bool:
    lowered_word = word.lower()
    if lowered_word.isascii():
        return bool(re.search(rf"\b{re.escape(lowered_word)}\b", lowered_text))
    return lowered_word in lowered_text


def _contains_workflow_term(normalized_lowered_text: str, term: str) -> bool:
    normalized_term = term.lower().replace("ё", "е")
    if " " in normalized_term:
        return normalized_term in normalized_lowered_text
    return bool(
        re.search(
            rf"(?<![A-Za-zА-Яа-яЁё0-9_]){re.escape(normalized_term)}(?![A-Za-zА-Яа-яЁё0-9_])",
            normalized_lowered_text,
        )
    )


def _is_terminal_text_move(move: ActorMove) -> bool:
    return move.terminal_action is not None or move.move_type in TERMINAL_MOVE_TYPES


QUESTION_GOAL_MARKERS: dict[str, tuple[str, ...]] = {
    "need_type": (
        "главное",
        "цель",
        "закрыть",
        "долг",
        "карт",
        "снизить",
        "сумм",
        "на руки",
    ),
    "desired_amount_or_total_debt": ("сумм", "долг", "задолж", "на руки", "размер"),
    "total_debt": ("долг", "долгов", "задолж", "карт", "кредит"),
    "monthly_payments": ("ежемесяч", "платеж", "платежи", "плачу", "уходит", "в месяц"),
    "income_status": ("доход", "официаль", "зарплат", "работа", "самозанят"),
    "comfortable_payment": ("комфорт", "посильн", "платеж", "платить"),
    "delinquency_context": ("просроч", "задерж", "платите", "без задерж"),
    "loan_types": ("долг", "карт", "кредит", "мфо", "займ", "банк"),
    "collateral_preference": ("рассмотр", "вариант", "залог", "авто или недвиж", "машин или недвиж"),
    "urgency": ("сроч", "срок", "когда", "насколько быстро"),
    "car_brand_model": (
        "марка",
        "модель",
        "марку",
        "модель",
        "какая машина",
        "какая у вас машина",
        "какая у вас марка",
        "какой автомобиль",
        "что за автомобиль",
        "что за машина",
    ),
    "car_year": ("год", "какого года", "года", "выпуска"),
    "car_owner": ("оформлен", "оформлена", "собственник", "на ком", "на кого", "владел"),
    "car_pledge_or_restrictions": (
        "залог",
        "автокредит",
        "арест",
        "огранич",
        "обремен",
    ),
    "property_type": ("квартир", "дом", "объект", "недвиж", "жилье", "апартамент", "комнат"),
    "property_region": ("город", "регион", "где", "объект"),
    "property_owner_or_ownership": ("оформлен", "оформлена", "собственник", "на кого", "на ком", "владел"),
    "property_encumbrance_basic": ("ипотек", "залог", "арест", "обремен", "огранич"),
    "bfl_property_context": (
        "недвиж",
        "квартир",
        "дом",
        "город",
        "оформлен",
        "собственник",
        "единствен",
        "ипотек",
        "залог",
        "арест",
        "обремен",
    ),
    "bfl_dependents_context": ("иждив", "кто", "сколько", "дет", "родител"),
    "bfl_vehicle_context": ("машин", "авто", "автомоб", "год", "марка", "модель"),
    "previous_debt_procedure": ("раньше", "банкрот", "реструктуризац", "процедур"),
}


def _question_goal_mismatch(output: ActorWriterOutput, move: ActorMove) -> bool:
    """Check writer wording against backend-owned slot goals without parsing facts."""

    goal = move.question_goal or move.next_slot
    if goal not in QUESTION_GOAL_MARKERS:
        return False
    question = output.followup_question.strip()
    if not question:
        return False
    normalized_question = question.lower().replace("ё", "е")
    return not any(marker in normalized_question for marker in QUESTION_GOAL_MARKERS[goal])


def _income_amount_invented_from_monthly_payment(
    output: ActorWriterOutput,
    move: ActorMove,
) -> bool:
    """Reject visible text that relabels the current payment amount as income."""

    if (move.question_goal or move.next_slot) != "income_status":
        return False
    known_facts = move.known_facts or {}
    if known_facts.get("official_income") is not None or known_facts.get("other_income") is not None:
        return False
    monthly_payments = known_facts.get("monthly_payments")
    if not isinstance(monthly_payments, int):
        return False

    normalized_text = output.text.lower().replace("ё", "е")
    for amount_match in re.finditer(
        r"\bдоход\w*\b.{0,80}?(\d+(?:[,.]\d+)?)\s*(тысяч|тыс|т\.?\s?р\.?|руб|₽)?",
        normalized_text,
    ):
        amount = _parse_visible_amount(
            amount_match.group(1),
            amount_match.group(2),
            reference_amount=monthly_payments,
        )
        if amount == monthly_payments:
            return True
    return False


def _plain_ask_slot_canned_phrases(
    output: ActorWriterOutput,
    move: ActorMove,
) -> list[str]:
    """Flag overused mini-lecture phrases only for plain slot intake."""

    if move.move_type != "ask_slot":
        return []
    lowered = output.text.lower().replace("ё", "е")
    return [phrase for phrase in PLAIN_ASK_SLOT_CANNED_PHRASES if phrase in lowered]


def _parse_visible_amount(
    raw_amount: str,
    raw_unit: str | None,
    *,
    reference_amount: int,
) -> int | None:
    normalized_amount = raw_amount.replace(",", ".")
    try:
        number = float(normalized_amount)
    except ValueError:
        return None
    unit = (raw_unit or "").lower()
    if unit.startswith("ты") or unit.startswith("т."):
        return int(number * 1000)
    if number.is_integer():
        integer = int(number)
        if integer == reference_amount:
            return integer
        if integer < 1000 and integer * 1000 == reference_amount:
            return integer * 1000
    return None


def _has_handoff_expert_next_step(lowered_text: str) -> bool:
    """Require HANDOFF_EXPERT text to visibly close the specialist handoff."""

    normalized_text = lowered_text.replace("ё", "е")
    has_specialist = "специалист" in normalized_text
    has_next_step = any(
        marker in normalized_text
        for marker in (
            "передам",
            "передаю",
            "передаем",
            "дальше",
            "посмотрит",
            "проверит",
            "свяжется",
            "разберет",
        )
    )
    return has_specialist and has_next_step


def _has_handoff_language(lowered_text: str) -> bool:
    return any(marker in lowered_text for marker in HANDOFF_LANGUAGE)


def _has_vehicle_specific_specialist_check(lowered_text: str) -> bool:
    normalized_text = lowered_text.replace("ё", "е")
    return bool(
        "специалист" in normalized_text
        and re.search(r"(?<![a-zа-я0-9_])(?:машин\w*|авто|птс)(?![a-zа-я0-9_])", normalized_text)
    )


def _vehicle_specific_handoff_backend_mismatch(
    lowered_text: str,
    move: ActorMove,
    events: list[ActionEvent] | None,
) -> bool:
    if not _has_vehicle_specific_specialist_check(lowered_text):
        return False
    if move.action_scope == "bfl_handoff" and move.selected_route in {BFL_RD, BFL_RI}:
        return False
    if move.move_type == "post_terminal_answer" and move.action_scope == "handoff_expert":
        return False
    if move.move_type == "recommendation_offer":
        return not (
            move.pending_terminal_action == HANDOFF_EXPERT
            and move.pending_route in {PTS, AUTO_AUX}
            and move.selected_route in {PTS, AUTO_AUX}
        )
    if move.terminal_action == HANDOFF_EXPERT and move.selected_route in {PTS, AUTO_AUX}:
        if events is None:
            return False
        return not any(
            event.action_id == HANDOFF_EXPERT and event.selected_route in {PTS, AUTO_AUX}
            for event in events
        )
    return True


def _allowed_post_terminal_specialist_reference(move: ActorMove, marker: str) -> bool:
    """Allow references to the already active specialist after terminal handoff."""

    return bool(
        move.move_type == "post_terminal_answer"
        and move.action_scope is not None
        and marker == "специалисту"
    )


def _allowed_recommendation_offer_handoff_language(move: ActorMove) -> bool:
    """Allow consent questions before a backend-selected handoff event."""

    return bool(
        move.move_type == "recommendation_offer"
        and move.pending_terminal_action in {HANDOFF_EXPERT, HANDOFF_BFL_SPECIALIST}
    )
