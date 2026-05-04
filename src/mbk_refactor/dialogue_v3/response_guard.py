"""Deterministic response guard for actor writer output."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .actions import ActionEvent
from .constants import AUTO_AUX, BFL_RD, BFL_RI
from .moves import ActorMove
from .safe_fallback import ActorWriterOutput

INTERNAL_WORDS = [
    "route",
    "scenario",
    "graph",
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

        if move.terminal_action is None:
            for marker in HANDOFF_LANGUAGE:
                if marker in lowered:
                    issues.append(
                        GuardIssue(
                            "handoff_without_action",
                            f"handoff language without terminal action: {marker}",
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
