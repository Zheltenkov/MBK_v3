"""Safe deterministic response renderer for Step 1."""

from __future__ import annotations

from dataclasses import dataclass

from .moves import ActorMove


@dataclass(frozen=True)
class ActorWriterOutput:
    body: str = ""
    followup_question: str = ""

    @property
    def text(self) -> str:
        parts = [part.strip() for part in (self.body, self.followup_question) if part.strip()]
        return "\n\n".join(parts)


def render_safe_fallback(move: ActorMove) -> ActorWriterOutput:
    """Render a safe answer from backend-owned ActorMove only."""

    if move.move_type == "ask_slot" and move.next_slot:
        return ActorWriterOutput(followup_question=deterministic_question_for_slot(move.next_slot))

    if move.move_type == "handle_offtopic_then_ask" and move.next_slot:
        return ActorWriterOutput(
            body="Давайте вернемся к вашей финансовой ситуации.",
            followup_question=deterministic_question_for_slot(move.next_slot),
        )

    if move.move_type == "handle_objection_then_ask" and move.next_slot:
        return ActorWriterOutput(
            body=_concern_body(move.client_concern),
            followup_question=deterministic_question_for_slot(move.next_slot),
        )

    if move.move_type == "answer_then_ask_slot" and move.next_slot:
        return ActorWriterOutput(
            body="Понял вопрос. Сначала уточню один факт, чтобы не предлагать неподходящий вариант.",
            followup_question=deterministic_question_for_slot(move.next_slot),
        )

    if move.move_type == "security_action":
        return ActorWriterOutput(
            body="Коды из СМС никому не сообщайте. Передам обращение на проверку безопасности."
        )

    if move.move_type == "repeat_action":
        return ActorWriterOutput(
            body="Передам повторное обращение, чтобы восстановить контекст и проверить, почему не ответили."
        )

    if move.move_type in {"terminal_action", "no_solution_manual_review"}:
        return ActorWriterOutput(
            body="Передам ситуацию специалисту для проверки без обещаний заранее."
        )

    return ActorWriterOutput(
        body="Сейчас не могу корректно сформулировать ответ. Напишите, пожалуйста, еще раз."
    )


def deterministic_question_for_slot(slot: str) -> str:
    """Map the next backend slot to one customer-facing question."""

    questions = {
        "need_type": "Деньги нужны больше закрыть долги или карты, снизить ежемесячный платеж или получить сумму на руки?",
        "property_type": "Какая недвижимость есть: квартира, дом или другой объект?",
        "property_owner_or_ownership": "На кого оформлена недвижимость и готов ли собственник участвовать?",
        "property_encumbrance_basic": "Есть ли по недвижимости ипотека, залог, арест или другие обременения?",
        "car_brand_model": "Какая у вас машина: марка и модель?",
        "car_year": "Какого года автомобиль?",
        "car_owner": "На кого оформлен автомобиль?",
        "car_pledge_or_restrictions": "Автомобиль сейчас в залоге, кредите, аресте или с ограничениями?",
        "income_status": "Какой сейчас доход: официальный, неофициальный, стабильный или нестабильный?",
        "delinquency_context": "Есть ли просрочки, и если да, сколько они длятся?",
        "desired_amount_or_total_debt": "Какая сумма нужна или какой общий долг нужно разобрать?",
        "total_debt": "Какой общий размер задолженности?",
        "monthly_payments": "Сколько сейчас уходит в месяц на платежи по кредитам и долгам?",
        "comfortable_payment": "Какой ежемесячный платеж был бы для вас комфортным?",
        "loan_types": "Какие долги есть: банки, карты, МФО, займы или другое?",
        "urgency": "Насколько срочно нужна сумма?",
    }
    return questions.get(slot, "Какой факт по ситуации важно уточнить следующим?")


def _concern_body(concern: str | None) -> str:
    if concern == "property_risk":
        return "Понимаю страх за жилье. Риск нельзя обнулить словами; сначала уточним базовые параметры."
    if concern == "vehicle_retention":
        return "Понял, машина нужна вам для жизни или работы. Это не означает, что ее нужно отдавать."
    if concern == "bankruptcy_fear":
        return "Понимаю, что банкротство может пугать. Сейчас смотрим на законный и посильный вариант."
    return "Понял вашу позицию. Уточню один факт, чтобы двигаться аккуратно."
