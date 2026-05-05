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
        return deterministic_output_for_slot(move.next_slot)

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

    if move.move_type == "post_terminal_answer":
        return ActorWriterOutput(body=_post_terminal_body(move))

    if move.move_type == "recommendation_offer":
        return recommendation_offer_output(move)

    if move.move_type in {"terminal_action", "no_solution_manual_review"}:
        if move.action_scope == "bfl_handoff":
            return ActorWriterOutput(
                body="Долговая нагрузка уже требует отдельного разбора. Передам специалисту по долгам: он проверит посильный вариант и риски без обещаний заранее."
            )
        return ActorWriterOutput(
            body="Передам ситуацию специалисту для проверки без обещаний заранее."
        )

    return ActorWriterOutput(
        body="Сейчас не могу корректно сформулировать ответ. Напишите, пожалуйста, еще раз."
    )


def deterministic_question_for_slot(slot: str) -> str:
    """Map the next backend slot to one customer-facing question."""

    return deterministic_output_for_slot(slot).followup_question


def deterministic_output_for_slot(slot: str) -> ActorWriterOutput:
    """Map the backend-owned next slot to deterministic manager-like wording."""

    outputs = {
        "need_type": ActorWriterOutput(
            followup_question="Что сейчас главное: закрыть долги или карты, снизить ежемесячный платеж, получить сумму на руки или другое?",
        ),
        "property_type": ActorWriterOutput(
            followup_question="Это квартира, дом или другой объект?",
        ),
        "property_owner_or_ownership": ActorWriterOutput(
            followup_question="На кого оформлена недвижимость и готов ли собственник участвовать?",
        ),
        "property_encumbrance_basic": ActorWriterOutput(
            followup_question="Есть ли по недвижимости ипотека, залог, арест или другие обременения?",
        ),
        "car_brand_model": ActorWriterOutput(
            followup_question="Какая у вас машина: марка и модель?",
        ),
        "car_year": ActorWriterOutput(
            followup_question="Какого года автомобиль?",
        ),
        "car_owner": ActorWriterOutput(
            followup_question="На кого оформлен автомобиль?",
        ),
        "car_pledge_or_restrictions": ActorWriterOutput(
            followup_question="Автомобиль сейчас в залоге, кредите, аресте или с ограничениями?",
        ),
        "income_status": ActorWriterOutput(
            followup_question="Какой у вас доход в месяц и он официальный?",
        ),
        "delinquency_context": ActorWriterOutput(
            followup_question="Есть просрочки или пока платите без задержек?",
        ),
        "desired_amount_or_total_debt": ActorWriterOutput(
            followup_question="Какая сумма нужна на руки или какой общий долг нужно разобрать?",
        ),
        "total_debt": ActorWriterOutput(
            followup_question="Какая сейчас общая сумма долгов по кредитам и картам?",
        ),
        "monthly_payments": ActorWriterOutput(
            followup_question="Сколько примерно уходит в месяц на платежи?",
        ),
        "comfortable_payment": ActorWriterOutput(
            followup_question="Какой ежемесячный платеж был бы комфортным?",
        ),
        "loan_types": ActorWriterOutput(
            followup_question="Какие долги есть: карты, кредиты, МФО или займы?",
        ),
        "collateral_preference": ActorWriterOutput(
            body="По нагрузке новый обычный кредит может быть не первым вариантом.",
            followup_question="Авто или недвижимость как вариант для проверки условий готовы рассматривать или точно нет?",
        ),
        "bfl_property_context": ActorWriterOutput(
            followup_question="Какая недвижимость есть: тип, город, на ком оформлена, единственное ли жилье и есть ли обременения?",
        ),
        "bfl_dependents_context": ActorWriterOutput(
            followup_question="Кто у вас на иждивении и сколько человек?",
        ),
        "bfl_vehicle_context": ActorWriterOutput(
            followup_question="Какая машина и какого года?",
        ),
        "previous_debt_procedure": ActorWriterOutput(
            followup_question="Раньше были банкротство или реструктуризация долгов?",
        ),
        "urgency": ActorWriterOutput(
            followup_question="Насколько срочно нужна сумма?",
        ),
    }
    return outputs.get(
        slot,
        ActorWriterOutput(followup_question="Какой факт по ситуации важно уточнить следующим?"),
    )


def _concern_body(concern: str | None) -> str:
    if concern == "property_risk":
        return "Понимаю страх за жилье. Проверим только базовые параметры."
    if concern == "vehicle_retention":
        return "Понял, машину забирать не хочется - это учтем."
    if concern == "bankruptcy_fear":
        return "Понимаю, что банкротство может пугать. Сейчас смотрим на законный и посильный вариант."
    if concern in {"credit_bureau_objection", "mfo_rating_concern", "challenges_credit_bureau_claim"}:
        return "Вы правы: МФО и займы часто портят картину для банков. Поэтому сначала считаем текущую нагрузку."
    if concern == "bankruptcy_clarification_question":
        return "Не обязательно банкротство. Сначала смотрят посильный график и риски."
    return "Понял вашу позицию. Уточню один факт, чтобы двигаться аккуратно."


def recommendation_offer_output(move: ActorMove) -> ActorWriterOutput:
    """Render a pending terminal recommendation without emitting an action."""

    summary = move.recommendation_summary
    product = move.recommended_product or "следующий шаг"
    prefix = ""
    if move.direct_answer_topic == "bankruptcy_clarification" and move.action_scope == "bfl_handoff":
        prefix = (
            "Не обязательно банкротство. При стабильном доходе сначала проверяют посильный график "
            "или реструктуризацию; банкротство смотрят отдельно. Имущество нужно отдельно проверить. "
        )
    if summary:
        clean_summary = summary.rstrip(".")
        body = (
            f"{prefix}{clean_summary}. "
            f"Самый логичный следующий шаг - проверить {product}. Условия заранее не обещаю."
        )
    else:
        body = f"{prefix}По вводным картина понятна. Самый логичный следующий шаг - проверить {product}. Условия заранее не обещаю."
    return ActorWriterOutput(
        body=body,
        followup_question=move.confirmation_question or "Передать вас специалисту, чтобы он проверил детали?",
    )


def _post_terminal_body(move: ActorMove) -> str:
    if move.direct_answer_topic == "route_declined":
        return "Понял, этот вариант не рассматриваем. Тогда смотрим следующий подходящий формат по вашим вводным."
    if move.action_scope == "bfl_handoff":
        if move.direct_answer_topic == "bankruptcy_clarification":
            return (
                "Не обязательно банкротство. Сначала смотрят посильный график или "
                "реструктуризацию: доход есть, задача - снизить нагрузку. Банкротство "
                "проверяют отдельно, без назначения с ходу и без обещаний заранее."
            )
        return (
            "Дальше идет долговой разбор: специалист по долгам проверит нагрузку, "
            "платежи и риски. Те же вопросы заново проходить не нужно."
        )
    if move.action_scope == "handoff_expert":
        return (
            "Дальше с вами работает профильный специалист: он посмотрит сумму, "
            "объект или авто, документы и ограничения. Те же вопросы заново проходить не нужно."
        )
    return "Дальше уже идет выбранный разбор. Те же вопросы заново проходить не нужно."
