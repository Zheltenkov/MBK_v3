"""Actor-like writer for dialogue_v3.

The writer owns wording only. Route, actions, next slots, and facts are read-only
inputs produced by deterministic backend layers.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from typing import Any, Callable, Literal

from .actor_prompts import ACTOR_STYLE_PACK, FEW_SHOT_EXAMPLES, SYSTEM_PROMPT
from .constants import AUTO_AUX, MORTGAGE_AUX, MORTGAGE_MAIN, PTS
from .facts import ExtractedTurn
from .moves import ActorMove, terminal_action_scope
from .response_guard import GuardValidation
from .safe_fallback import (
    ActorWriterOutput,
    deterministic_output_for_slot,
    deterministic_question_for_slot,
)
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
    newly_extracted_facts: dict[str, Any] | None = None
    conversation_summary: str = ""
    emitted_terminal_actions: list[str] | None = None


def build_compact_state_summary(
    state: DialogueV3State,
    extracted_turn: ExtractedTurn | None = None,
) -> CompactStateSummary:
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
        newly_extracted_facts=dict(extracted_turn.facts) if extracted_turn else None,
        conversation_summary=_conversation_summary(known_facts),
        emitted_terminal_actions=sorted(state.emitted_terminal_actions),
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
            return deterministic_output_for_slot(move.next_slot)

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

        if move.move_type == "post_terminal_answer":
            return ActorWriterOutput(body=_post_terminal_body(move))

        if move.move_type == "terminal_action":
            return ActorWriterOutput(body=_terminal_body(move))

        if move.move_type == "no_solution_manual_review":
            return ActorWriterOutput(body=_terminal_body(move))

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
            "writer_context": _build_writer_context(move, state_summary),
            "slot_wording_hints": SLOT_WORDING_HINTS,
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


SLOT_WORDING_HINTS = {
    "need_type": "Уточнить, что главное: закрыть долги/карты, снизить платеж, получить сумму на руки или другое.",
    "total_debt": "Спросить общую сумму долгов, кредитов, карт и займов.",
    "monthly_payments": "Спросить текущую сумму ежемесячных платежей.",
    "income_status": "Спросить доход в месяц и официальный ли он.",
    "comfortable_payment": "Спросить посильный ежемесячный платеж.",
    "delinquency_context": "Спросить, есть ли просрочки и сколько они длятся.",
    "property_type": "Спросить, что за объект: квартира, дом или другое.",
    "property_region": "Спросить регион или город объекта.",
    "property_encumbrance_basic": "Спросить ипотеку, залог, аресты или ограничения.",
    "car_brand_model": "Спросить марку и модель машины.",
    "car_year": "Спросить год выпуска машины.",
    "car_owner": "Спросить, на кого оформлена машина.",
    "car_pledge_or_restrictions": "Спросить залог, автокредит, аресты или ограничения по машине.",
}


def _build_writer_context(
    move: ActorMove,
    state_summary: CompactStateSummary | None,
) -> dict[str, Any]:
    """Build a read-only prompt payload; backend decisions remain authoritative."""

    known_facts = dict(state_summary.known_facts or {}) if state_summary else {}
    known_facts.update(move.known_facts or {})
    emitted_terminal_actions = list(state_summary.emitted_terminal_actions or []) if state_summary else []
    return {
        "latest_user_message": state_summary.last_user_text if state_summary else "",
        "conversation_summary": state_summary.conversation_summary if state_summary else "",
        "known_facts": known_facts,
        "newly_extracted_facts": dict(state_summary.newly_extracted_facts or {}) if state_summary else {},
        "selected_route": move.selected_route,
        "phase": move.phase,
        "move_type": move.move_type,
        "next_slot": move.next_slot,
        "terminal_action": move.terminal_action,
        "action_scope": move.action_scope,
        "terminal_action_already_emitted": _terminal_action_already_emitted(
            move,
            emitted_terminal_actions,
        ),
        "direct_answer_topic": move.direct_answer_topic,
        "client_concern": move.client_concern,
        "question_goal": move.question_goal,
        "must_say": list(move.must_say),
        "must_not_say": list(move.must_not_say),
    }


def _terminal_action_already_emitted(
    move: ActorMove,
    emitted_terminal_actions: list[str],
) -> bool:
    if move.terminal_action:
        return f"{move.selected_route}:{move.terminal_action}" in emitted_terminal_actions
    return any(action_key.startswith(f"{move.selected_route}:") for action_key in emitted_terminal_actions)


def _conversation_summary(known_facts: dict[str, Any]) -> str:
    parts: list[str] = []
    need_type = known_facts.get("need_type")
    if need_type == "debt_solution":
        parts.append("клиент хочет закрыть долги или карты")
    elif need_type == "payment_reduction":
        parts.append("клиент хочет снизить ежемесячный платеж")
    elif need_type == "new_money":
        parts.append("клиенту нужна сумма на руки")
    if known_facts.get("total_debt") is not None:
        parts.append(f"общий долг около {known_facts['total_debt']}")
    if known_facts.get("monthly_payments") is not None:
        parts.append(f"текущий платеж около {known_facts['monthly_payments']}")
    if known_facts.get("official_income") is not None:
        parts.append(f"официальный доход около {known_facts['official_income']}")
    elif known_facts.get("income_status") not in (None, "unknown"):
        parts.append(f"доход: {known_facts['income_status']}")
    if known_facts.get("comfortable_payment") is not None:
        parts.append(f"комфортный платеж около {known_facts['comfortable_payment']}")
    if known_facts.get("has_arrears") is True:
        parts.append("есть просрочка")
    if known_facts.get("has_arrears") is False:
        parts.append("просрочек нет")
    return "; ".join(parts)


def _offtopic_redirect(
    move: ActorMove,
    state_summary: CompactStateSummary | None,
) -> str:
    text = (state_summary.last_user_text if state_summary else "").lower()
    prefix = _client_name_prefix(move=move, state_summary=state_summary)
    if "python" in text or "код" in text:
        return f"{prefix}Python - это точно не ко мне. Я здесь по кредитам, долгам и вариантам снижения нагрузки."
    if "english" in text:
        return f"{prefix}English здесь не нужен. Разбираем российские долги, рубли и платежи. Давайте по делу."
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
    scope = move.action_scope or terminal_action_scope(move.terminal_action)
    if scope == "bfl_handoff":
        return _bfl_terminal_body(move)
    if scope == "handoff_expert":
        return _expert_handoff_body(move)
    if scope == "manual_review":
        return "Автоматически обещать решение здесь нельзя. Передам на ручной разбор, чтобы ситуацию проверили аккуратно."
    if scope == "self_serve_links":
        return "По базовым данным можно показать варианты для самостоятельной подачи. Перед заявкой сверяйте условия и платеж без обещаний по одобрению."
    if scope == "security_check":
        return "Код из СМС никому не сообщайте. Сейчас это вопрос безопасности: проверим обращение и не будем передавать лишние данные в чате."
    if scope == "repeat_handoff":
        return "Это повторное обращение после перехода к специалисту. Анкету заново проходить не нужно - восстановим контакт и отметим, что ответа не было."
    return "Передам ситуацию специалисту для проверки без обещаний заранее."


def _expert_handoff_body(move: ActorMove) -> str:
    if move.selected_route in {PTS, AUTO_AUX}:
        return (
            "По машине основные параметры уже понятны. Передам ситуацию специалисту: "
            "он проверит формат по авто и ограничения без обещаний заранее."
        )
    if move.selected_route in {MORTGAGE_MAIN, MORTGAGE_AUX}:
        return (
            "По недвижимости основные параметры уже понятны. Передам ситуацию специалисту: "
            "он проверит объект, ограничения и возможный формат без обещаний заранее."
        )
    return "Передам ситуацию специалисту: он проверит подходящий формат и ограничения без обещаний заранее."


def _bfl_terminal_body(move: ActorMove) -> str:
    reasons = _bfl_reason_parts(move.known_facts)
    if reasons:
        reason_text = " ".join(reasons)
    else:
        reason_text = "Здесь уже важнее не добирать новый кредит, а разобрать долговую нагрузку."
    return (
        f"{reason_text} Передам специалисту по долгам: он проверит, можно ли идти "
        "в сторону посильного графика выплат и какие риски есть. Без обещаний заранее."
    )


def _bfl_reason_parts(known_facts: dict[str, Any]) -> list[str]:
    parts: list[str] = []
    total_debt = _money(known_facts.get("total_debt"))
    monthly_payments = _money(known_facts.get("monthly_payments"))
    official_income = _money(known_facts.get("official_income"))
    comfortable_payment = _money(known_facts.get("comfortable_payment"))
    income_status = known_facts.get("income_status")
    has_arrears = known_facts.get("has_arrears")
    arrears = known_facts.get("delinquency_context")

    if total_debt and monthly_payments:
        parts.append(f"Долг около {total_debt}, текущий платеж примерно {monthly_payments}.")
    elif total_debt:
        parts.append(f"Долг около {total_debt}, поэтому новый кредит не стоит добирать вслепую.")
    elif monthly_payments:
        parts.append(f"Текущий платеж примерно {monthly_payments}, сначала нужно разобрать нагрузку.")
    else:
        parts.append("Здесь уже важнее не добирать новый кредит, а разобрать долговую нагрузку.")

    if official_income:
        parts.append(f"Доход около {official_income},")
        if comfortable_payment:
            parts[-1] += f" комфортный платеж ниже - около {comfortable_payment}."
        else:
            parts[-1] += " поэтому важно считать посильный график."
    elif income_status == "stable":
        if comfortable_payment:
            parts.append(f"Доход есть, комфортный платеж ниже - около {comfortable_payment}.")
        else:
            parts.append("Доход есть, значит сначала смотрим посильный график.")
    elif comfortable_payment:
        parts.append(f"Комфортный платеж ниже текущего - около {comfortable_payment}.")

    if has_arrears is True:
        if arrears:
            parts.append(f"Плюс появилась просрочка: {arrears}.")
        else:
            parts.append("Плюс появилась просрочка.")
    elif has_arrears is False:
        parts.append("Просрочек нет, но нагрузку все равно нужно снижать аккуратно.")

    return parts


def _post_terminal_body(move: ActorMove) -> str:
    if move.action_scope == "bfl_handoff":
        if move.direct_answer_topic == "bankruptcy_clarification":
            return (
                "Не обязательно банкротство. По вашим вводным первым делом смотрят "
                "посильный график или реструктуризацию: доход есть, вы хотите платить, "
                "задача - снизить нагрузку. Банкротство - отдельный вариант, его не "
                "назначают с ходу; специалист сравнит риски и скажет, что реалистичнее. "
                "Без обещаний заранее."
            )
        return (
            "Дальше с вами работает специалист по долгам: он разберет нагрузку, "
            "платежи, доход и просрочку, а потом проверит реалистичный способ снизить "
            "платеж. Повторно проходить те же вопросы не нужно."
        )
    return "Дальше уже идет выбранный разбор. Повторно проходить те же вопросы не нужно."


def _money(value: Any) -> str | None:
    if not isinstance(value, int):
        return None
    return f"{value:,} ₽".replace(",", " ")


def _client_name_prefix(
    *,
    move: ActorMove,
    state_summary: CompactStateSummary | None,
) -> str:
    known_facts = dict(state_summary.known_facts or {}) if state_summary else {}
    known_facts.update(move.known_facts or {})
    raw_name = known_facts.get("client_first_name") or known_facts.get("full_name")
    if not isinstance(raw_name, str):
        return ""
    first_name = raw_name.strip().split()[0] if raw_name.strip() else ""
    return f"{first_name}, " if first_name else ""
