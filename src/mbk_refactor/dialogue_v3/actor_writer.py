"""Actor-like writer for dialogue_v3.

The writer owns wording only. Route, actions, next slots, and facts are read-only
inputs produced by deterministic backend layers.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from typing import Any, Callable, Literal

from .actor_prompts import ACTOR_STYLE_PACK, FEW_SHOT_EXAMPLES, SYSTEM_PROMPT
from .moves import ActorMove
from .response_guard import GuardValidation
from .safe_fallback import ActorWriterOutput, deterministic_question_for_slot
from .state import DialogueV3State

WriterMode = Literal["deterministic", "llm", "llm_guarded"]
LLMClient = Callable[[list[dict[str, str]]], str]


@dataclass(frozen=True)
class CompactStateSummary:
    """Small writer context that avoids exposing mutable dialogue state."""

    session_id: str
    turn_index: int
    last_user_text: str = ""
    known_facts: dict[str, Any] | None = None


def build_compact_state_summary(state: DialogueV3State) -> CompactStateSummary:
    """Prepare compact, read-only context for the actor writer."""

    known_facts = {
        key: fact.value
        for key, fact in state.facts.items()
        if fact.quality not in {"unknown", "not_applicable"}
    }
    last_user_text = ""
    for message in reversed(state.messages):
        if message.role == "user":
            last_user_text = message.content
            break
    return CompactStateSummary(
        session_id=state.session_id,
        turn_index=state.turn_index,
        last_user_text=last_user_text,
        known_facts=known_facts,
    )


class ActorWriter:
    """Generate actor-like wording while preserving backend decisions."""

    def __init__(self, *, mode: WriterMode = "deterministic", llm_client: LLMClient | None = None):
        self.mode = mode
        self.llm_client = llm_client

    def write(
        self,
        *,
        move: ActorMove,
        state_summary: CompactStateSummary | None = None,
    ) -> ActorWriterOutput:
        """Return structured writer output for one ActorMove."""

        if self.mode == "deterministic" or self.llm_client is None:
            return self._write_deterministic(move=move, state_summary=state_summary)

        raw_response = self.llm_client(self._build_llm_messages(move, state_summary))
        return _parse_actor_json(raw_response)

    def repair(
        self,
        *,
        move: ActorMove,
        state_summary: CompactStateSummary | None,
        output: ActorWriterOutput,
        validation: GuardValidation,
    ) -> ActorWriterOutput:
        """Ask the LLM writer for one text-only repair pass."""

        if self.mode == "deterministic" or self.llm_client is None:
            return self._write_deterministic(move=move, state_summary=state_summary)

        raw_response = self.llm_client(
            self._build_llm_messages(
                move,
                state_summary,
                repair_payload={
                    "previous_output": {
                        "body": output.body,
                        "followup_question": output.followup_question,
                    },
                    "validation_issues": [
                        {"code": issue.code, "message": issue.message}
                        for issue in validation.issues
                    ],
                    "repair_instruction": "Исправь только текст. Не меняй route/action/next_slot/facts.",
                },
            )
        )
        return _parse_actor_json(raw_response)

    def _write_deterministic(
        self,
        *,
        move: ActorMove,
        state_summary: CompactStateSummary | None,
    ) -> ActorWriterOutput:
        if move.move_type == "ask_slot" and move.next_slot:
            return ActorWriterOutput(
                body="",
                followup_question=deterministic_question_for_slot(move.next_slot),
            )

        if move.move_type == "answer_then_ask_slot" and move.next_slot:
            return ActorWriterOutput(
                body="Сначала уточню один факт, чтобы не предложить неподходящий вариант.",
                followup_question=deterministic_question_for_slot(move.next_slot),
            )

        if move.move_type == "handle_offtopic_then_ask" and move.next_slot:
            return ActorWriterOutput(
                body=_offtopic_redirect(move, state_summary),
                followup_question=deterministic_question_for_slot(move.next_slot),
            )

        if move.move_type == "handle_objection_then_ask" and move.next_slot:
            return ActorWriterOutput(
                body=_objection_answer(move.client_concern),
                followup_question=deterministic_question_for_slot(move.next_slot),
            )

        if move.move_type == "security_action":
            return ActorWriterOutput(
                body="Код из СМС никому не сообщайте. Сейчас это вопрос безопасности: проверим обращение и не будем передавать лишние данные в чате."
            )

        if move.move_type == "repeat_action":
            return ActorWriterOutput(
                body="Это повторное обращение после перехода к специалисту. Анкету заново проходить не нужно - восстановим контакт и отметим, что ответа не было."
            )

        if move.move_type == "terminal_action":
            return ActorWriterOutput(body=_terminal_body(move))

        if move.move_type == "no_solution_manual_review":
            return ActorWriterOutput(
                body="Автоматически обещать решение здесь нельзя. Передам ситуацию специалисту для аккуратной проверки."
            )

        return ActorWriterOutput(
            body="Сейчас не могу корректно сформулировать ответ. Напишите, пожалуйста, еще раз."
        )

    def _build_llm_messages(
        self,
        move: ActorMove,
        state_summary: CompactStateSummary | None,
        repair_payload: dict[str, Any] | None = None,
    ) -> list[dict[str, str]]:
        payload = {
            "actor_move": asdict(move),
            "state_summary": asdict(state_summary) if state_summary else {},
            "style_pack": ACTOR_STYLE_PACK,
            "few_shots": FEW_SHOT_EXAMPLES,
        }
        if repair_payload:
            payload["repair"] = repair_payload
        return [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
        ]


def _parse_actor_json(raw_response: str) -> ActorWriterOutput:
    try:
        payload = json.loads(raw_response)
    except json.JSONDecodeError as exc:
        raise ValueError("actor writer returned invalid JSON") from exc
    if not isinstance(payload, dict):
        raise ValueError("actor writer JSON must be an object")
    return ActorWriterOutput(
        body=str(payload.get("body") or ""),
        followup_question=str(payload.get("followup_question") or ""),
    )


def _offtopic_redirect(
    move: ActorMove,
    state_summary: CompactStateSummary | None,
) -> str:
    text = (state_summary.last_user_text if state_summary else "").lower()
    if "python" in text or "код" in text:
        return "Сергей, Python - это точно не ко мне. Я здесь по кредитам, долгам и вариантам снижения нагрузки."
    if "english" in text:
        return "English здесь не нужен, Сергей. Разбираем российские долги, рубли и платежи. Давайте по делу."
    if "бот" in text or "робот" in text or "ии" in text:
        return "Я здесь как специалист по кредитам и долгам: смотрю вашу ситуацию и веду к следующему рабочему шагу."
    return "Давайте вернемся к вашей финансовой ситуации."


def _objection_answer(client_concern: str | None) -> str:
    if client_concern == "vehicle_retention":
        return "Это нормальное условие. То, что машина нужна каждый день, не значит, что авто-вариант сразу отпадает. Сначала проверяем формат пользования до оформления."
    if client_concern == "property_risk":
        return "Риск здесь нельзя обнулить словами. Сначала нужно понять, есть ли смысл смотреть залоговый вариант до оформления."
    if client_concern == "bankruptcy_fear":
        return "Если банкротство пугает, это нормально. Сейчас смотрим не обещания, а законный и посильный вариант."
    if client_concern == "challenges_credit_bureau_claim":
        return "Вы правы: сам факт МФО часто портит картину для банков. Тогда тем более не будем просто докидывать новый займ."
    return "Позицию услышал. Дальше нужен один факт, чтобы двигаться аккуратно."


def _terminal_body(move: ActorMove) -> str:
    if move.selected_route == "BFL_RD":
        return "Новый кредит здесь не выглядит первым вариантом: платеж уже выше комфортного, но вы хотите платить. Передам специалисту по долгам - он проверит законный посильный график без обещаний заранее."
    if move.selected_route == "BFL_RI":
        return "Здесь важнее разбор долговой нагрузки и просрочек, а не новый займ вслепую. Передам специалисту по долгам для проверки вариантов без обещаний заранее."
    if move.selected_route in {"PTS", "MORTGAGE_MAIN", "MORTGAGE_AUX", "AUTO_AUX"}:
        return "Базовые данные собраны. Передам ситуацию специалисту: он проверит подходящий формат и ограничения без обещаний заранее."
    if move.selected_route in {"UNSECURED", "MICRO"}:
        return "Базовые данные собраны. Отправлю на проверку подходящего варианта без обещаний по одобрению или условиям."
    return "Передам ситуацию специалисту для проверки без обещаний заранее."
