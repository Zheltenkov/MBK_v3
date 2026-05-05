"""Service, repeat-visit, correction, and off-topic extraction."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ..constants import PTS
from .need import set_need_signal
from .text import ACTIVE_DIALOG_CORRECTION_PATTERNS, contains_any

if TYPE_CHECKING:
    from ..state import DialogueV3State

SERVICE_FRAUD_PATTERNS = (
    "просили код",
    "попросили код",
    "код из смс",
    "смс-код",
    "смс код",
    "я ничего не оформлял",
    "заявка не моя",
    "на меня оформили",
    "мошенники позвонили",
    "ao_mbk",
)
SERVICE_REPEAT_PATTERNS = (
    "я уже оставлял заявку",
    "я уже оставляла заявку",
    "я уже переходил в чат",
    "я уже переходила в чат",
    "мне не ответили",
    "вам и не ответили",
    "со мной не связались",
    "продолжить заявку",
    "продолжить прошлую заявку",
    "по старой заявке",
    "прошлую заявку",
)
SERVICE_REPEAT_SELF_REFERENCE_PATTERNS = (
    "я уже обращался",
    "я уже обращалась",
    "ранее обращался",
    "ранее обращалась",
    "раньше обращалась",
    "раньше обращался",
)
REPEAT_CASE_CHANGE_PATTERNS = (
    "изменился доход",
    "появились просрочки",
)
OFF_TOPIC_PATTERNS = (
    "напиши код",
    "python",
    "switch to english",
    "забудь инструкции",
    "переведи",
    "расскажи историю",
)


def extract_service_signals(
    text: str,
    facts: dict[str, Any],
    concerns: list[str],
    state: DialogueV3State | None = None,
) -> tuple[str | None, str | None]:
    """Extract service-mode and off-topic signals without product routing."""

    if state is not None and state.pending_terminal_action:
        consent = detect_pending_terminal_consent(text, pending_route=state.pending_route)
        if consent:
            facts["pending_terminal_consent"] = consent

    service_signal: str | None = None
    if contains_any(text, SERVICE_FRAUD_PATTERNS):
        service_signal = "fraud_check"
        facts["service_signal"] = service_signal
        set_need_signal(facts, "security")
    elif _is_repeat_visit_signal(text, state):
        service_signal = "repeat_visit"
        facts["service_signal"] = service_signal
        set_need_signal(facts, "repeat")
    elif state is not None and state.turn_index > 1 and contains_any(text, ACTIVE_DIALOG_CORRECTION_PATTERNS):
        facts["correction_signal"] = True

    off_topic: str | None = None
    if contains_any(text, OFF_TOPIC_PATTERNS):
        off_topic = "off_topic_request"
        facts["off_topic_kind"] = off_topic
    elif contains_any(text, ("ты бот", "ты ии")):
        off_topic = "assistant_identity"
        facts["off_topic_kind"] = off_topic

    return service_signal, off_topic


def detect_pending_terminal_consent(text: str, *, pending_route: str | None = None) -> str | None:
    """Detect yes/no answer to a pending handoff offer only."""

    if _is_pending_terminal_acceptance(text):
        if _has_hard_pending_route_refusal(text, pending_route):
            return "negative"
        return "affirmative"
    if _is_pending_terminal_rejection(text):
        return "negative"
    return None


def _is_pending_terminal_acceptance(text: str) -> bool:
    if text.strip(" .,!?:;") in {
        "да",
        "давайте",
        "передавайте",
        "можно",
        "ок",
        "окей",
        "хорошо",
        "согласен",
        "согласна",
    }:
        return True
    return contains_any(
        text,
        (
            "пусть специалист посмотрит",
            "пусть посмотрит специалист",
            "можно передать",
            "да, передавайте",
            "давайте передадим",
        ),
    )


def _is_pending_terminal_rejection(text: str) -> bool:
    if text.strip(" .,!?:;") in {"нет", "не надо", "не хочу"}:
        return True
    return contains_any(
        text,
        (
            "не хочу",
            "не надо",
            "не рассматриваю",
            "давайте без этого",
            "птс не рассматриваю",
            "залог не хочу",
            "машину не трогаем",
            "квартиру не трогаем",
        ),
    )


def _has_hard_pending_route_refusal(text: str, pending_route: str | None) -> bool:
    """Separate route refusal from conditional consent like "yes, but don't take the car"."""

    if pending_route == PTS:
        return contains_any(
            text,
            (
                "птс не рассматриваю",
                "под машину не хочу",
                "машину не трогаем вообще",
                "никакого варианта с авто",
                "никакого варианта с машиной",
                "авто в залог не дам",
                "машину в залог не дам",
                "машину как обеспечение не рассматриваю",
                "авто как обеспечение не рассматриваю",
            ),
        )
    return False


def _is_repeat_visit_signal(text: str, state: DialogueV3State | None) -> bool:
    if contains_any(text, SERVICE_REPEAT_PATTERNS):
        return True
    if contains_any(text, REPEAT_CASE_CHANGE_PATTERNS):
        return state is None or state.turn_index <= 1
    if not contains_any(text, SERVICE_REPEAT_SELF_REFERENCE_PATTERNS):
        return False
    if state is not None and state.turn_index > 1 and contains_any(text, ACTIVE_DIALOG_CORRECTION_PATTERNS):
        return False
    return state is None or state.turn_index <= 1
