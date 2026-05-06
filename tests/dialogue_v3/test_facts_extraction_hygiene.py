from __future__ import annotations

import pytest

from mbk_refactor.dialogue_v3.engine import DialogueV3Engine
from mbk_refactor.dialogue_v3.facts import extract_turn
from mbk_refactor.dialogue_v3.understanding.amounts import get_last_asked_slot
from mbk_refactor.dialogue_v3.understanding.post_terminal import detect_post_terminal_topic
from mbk_refactor.dialogue_v3.understanding.vehicle import detect_vehicle_intent
from mbk_refactor.dialogue_v3.case_frame import build_case_frame
from mbk_refactor.dialogue_v3.constants import HANDOFF_BFL_SPECIALIST, PTS, REPEAT_HANDOFF, REPEAT_VISIT
from mbk_refactor.dialogue_v3.slot_resolver import is_slot_closed
from mbk_refactor.dialogue_v3.state import DialogueV3State


def test_debt_intent_beats_repair_purpose() -> None:
    extracted = extract_turn("Хочу закрыть карты и немного оставить на ремонт")

    assert extracted.facts["early_need_signal"] == "debt_solution"
    assert extracted.facts["need_type"] == "debt_solution"
    assert extracted.facts["purpose_goal"] == "repair"


def test_credit_card_debt_intent_with_car_repair_does_not_become_pts() -> None:
    extracted = extract_turn("Хочу закрыть две кредитные карты и немного оставить на ремонт машины.")

    assert extracted.facts["early_need_signal"] == "debt_solution"
    assert extracted.facts["need_type"] == "debt_solution"
    assert extracted.facts["purpose_goal"] == "car_repair"
    assert extracted.facts["loan_types_known"] is True
    assert extracted.facts["loan_types"] == ("credit_cards",)
    assert "explicit_pts_intent" not in extracted.facts
    assert "explicit_mortgage_intent" not in extracted.facts


@pytest.mark.parametrize(
    "text",
    [
        "Хочу закрыть две кредитные карты",
        "Нужно погасить кредитки",
        "Хочу перекрыть долги",
        "Надо объединить кредиты",
        "Хочу рефинансироваться",
        "Платежи тяжело тянуть",
        "Хочу снизить платеж",
    ],
)
def test_live_debt_phrases_set_debt_or_payment_need(text: str) -> None:
    extracted = extract_turn(text)

    assert extracted.facts["need_type"] in {"debt_solution", "payment_reduction"}
    assert extracted.facts["early_need_signal"] in {"debt_solution", "payment_reduction"}


def test_repair_alone_is_purpose_not_mortgage() -> None:
    extracted = extract_turn("Нужны деньги на ремонт")

    assert extracted.facts["early_need_signal"] == "repair_or_purpose"
    assert extracted.facts.get("need_type") != "debt_solution"
    assert "explicit_mortgage_intent" not in extracted.facts
    assert "has_property" not in extracted.facts


def test_generic_money_request_is_early_signal_not_committed_need_type() -> None:
    extracted = extract_turn("Хочу взять денег")

    assert extracted.facts["early_need_signal"] == "new_money"
    assert "need_type" not in extracted.facts


@pytest.mark.parametrize(
    "text",
    [
        "Мне нужна сумма на руки",
        "Получить сумму на руки.",
    ],
)
def test_strong_new_money_sets_need_type(text: str) -> None:
    extracted = extract_turn(text)

    assert extracted.facts["early_need_signal"] == "new_money"
    assert extracted.facts["need_type"] == "new_money"


def test_payment_reduction_sets_need_type() -> None:
    extracted = extract_turn("Хочу снизить ежемесячный платеж.")

    assert extracted.facts["early_need_signal"] == "payment_reduction"
    assert extracted.facts["need_type"] == "payment_reduction"


def test_new_money_closes_need_type_slot() -> None:
    state = DialogueV3State(session_id="new-money-slot")
    state.merge_facts({"need_type": "new_money"})
    frame = build_case_frame(state)

    assert is_slot_closed("need_type", state=state, frame=frame)


def test_post_terminal_next_step_clarification_is_extracted_as_turn_signal() -> None:
    text = "Хорошо, а что дальше? Мне нужно куда-то переходить или специалист сам посмотрит?"
    extracted = extract_turn(text)

    assert detect_post_terminal_topic(text) == "next_step"
    assert extracted.facts["post_terminal_topic"] == "next_step"


def test_post_terminal_contact_question_is_extracted_as_turn_signal() -> None:
    text = "Кто со мной свяжется и когда ждать звонка?"
    extracted = extract_turn(text)

    assert detect_post_terminal_topic(text) == "contact_question"
    assert extracted.facts["post_terminal_topic"] == "contact_question"


def test_post_terminal_bankruptcy_clarification_exact_question_is_extracted() -> None:
    extracted = extract_turn("Это банкротство или можно без него?")

    assert extracted.facts["post_terminal_topic"] == "bankruptcy_clarification"


def test_post_terminal_bankruptcy_clarification_has_priority_over_next_step() -> None:
    text = "А что значит отдельный разбор? Это банкротство или можно без него?"
    extracted = extract_turn(text)

    assert detect_post_terminal_topic(text) == "bankruptcy_clarification"
    assert extracted.facts["post_terminal_topic"] == "bankruptcy_clarification"


def test_case_frame_defaults_post_terminal_topic_to_unknown() -> None:
    frame = build_case_frame(DialogueV3State(session_id="post-terminal-unknown"))

    assert frame.post_terminal_topic == "unknown"


def test_regular_money_request_does_not_set_post_terminal_topic() -> None:
    extracted = extract_turn("Хочу взять денег на ремонт")

    assert detect_post_terminal_topic("Хочу взять денег на ремонт") is None
    assert "post_terminal_topic" not in extracted.facts


@pytest.mark.parametrize(
    "text",
    [
        "Дальше что?",
        "Куда переходить?",
        "Мне нужно куда-то переходить?",
        "Специалист сам посмотрит?",
        "Кто дальше посмотрит?",
        "Как дальше будет?",
    ],
)
def test_post_terminal_next_step_semantic_hints(text: str) -> None:
    assert detect_post_terminal_topic(text) == "next_step"


@pytest.mark.parametrize(
    "text",
    [
        "Банкротство или можно платить?",
        "Это реструктуризация?",
        "Без суда можно?",
        "Списание или платить?",
    ],
)
def test_post_terminal_bankruptcy_semantic_hints(text: str) -> None:
    assert detect_post_terminal_topic(text) == "bankruptcy_clarification"


@pytest.mark.parametrize(
    "text",
    [
        "Когда свяжется специалист?",
        "Мне позвонят?",
        "Специалист напишет?",
        "Ждать звонка?",
        "Ждать сообщения?",
    ],
)
def test_post_terminal_contact_semantic_hints(text: str) -> None:
    assert detect_post_terminal_topic(text) == "contact_question"


def test_last_user_text_is_turn_scoped_not_canonical_fact() -> None:
    from mbk_refactor.dialogue_v3.actor_writer import build_compact_state_summary

    engine = DialogueV3Engine()
    first = engine.handle_turn("Хочу взять денег")
    second = engine.handle_turn("Хочу закрыть долги", first.state)
    summary = build_compact_state_summary(second.state, second.extracted)

    assert "last_user_text" not in second.extracted.facts
    assert "last_user_text" not in second.state.facts
    assert second.extracted.raw_user_text == "Хочу закрыть долги"
    assert summary.last_user_text == "Хочу закрыть долги"


def test_mfo_rating_objection_is_on_topic_concern() -> None:
    extracted = extract_turn("МФО портит рейтинг, ОКБ это видит")

    assert extracted.off_topic is None
    assert extracted.facts["mfo_rating_concern"] is True
    assert extracted.facts["credit_bureau_objection"] is True
    assert "mfo_rating_concern" in extracted.customer_concerns


def test_explicit_mortgage_intent_without_object_type_does_not_fill_property_type() -> None:
    extracted = extract_turn("Хочу рассмотреть под залог недвижимости")

    assert extracted.facts["explicit_mortgage_intent"] is True
    assert extracted.facts["early_need_signal"] == "explicit_mortgage"
    assert "property_type" not in extracted.facts
    assert "has_property" not in extracted.facts


def test_explicit_mortgage_apartment_collateral_extracts_route_defining_facts() -> None:
    extracted = extract_turn(
        "Хочу взять около 2,8 млн под залог квартиры. "
        "Часть — закрыть кредиты, часть оставить на ремонт."
    )

    assert extracted.facts["explicit_mortgage_intent"] is True
    assert extracted.facts["early_need_signal"] == "explicit_mortgage"
    assert extracted.facts["property_type"] == "apartment"
    assert extracted.facts["need_type"] == "debt_solution"
    assert extracted.facts["purpose_goal"] == "repair"


def test_property_word_alone_does_not_set_has_property() -> None:
    extracted = extract_turn("Квартира")

    assert "has_property" not in extracted.facts
    assert "property_type" not in extracted.facts


def test_property_risk_concern_does_not_imply_possession() -> None:
    extracted = extract_turn("Боюсь потерять квартиру")

    assert extracted.facts["property_risk_concern"] is True
    assert extracted.facts["property_refuses_collateral"] is False
    assert "has_property" not in extracted.facts
    assert "property_type" not in extracted.facts


def test_property_loss_fear_is_concern_not_collateral_refusal() -> None:
    extracted = extract_turn("Квартиру потерять не хочу.")

    assert extracted.facts["property_risk_concern"] is True
    assert extracted.facts["property_refuses_collateral"] is False
    assert extracted.route_rejection != "MORTGAGE"


def test_property_loss_fear_word_order_is_concern_not_property_type() -> None:
    extracted = extract_turn("Квартиру потерять боюсь.")

    assert extracted.facts["property_risk_concern"] is True
    assert extracted.facts["property_refuses_collateral"] is False
    assert "property_type" not in extracted.facts
    assert extracted.route_rejection != "MORTGAGE"


def test_property_collateral_refusal_rejects_mortgage() -> None:
    extracted = extract_turn("Квартиру в залог не рассматриваю.")

    assert extracted.facts["property_refuses_collateral"] is True
    assert extracted.facts["route_rejection"] == "MORTGAGE"
    assert extracted.route_rejection == "MORTGAGE"


def test_mortgage_slot_context_extracts_property_type_and_region() -> None:
    state = DialogueV3State(session_id="mortgage-property-context")
    state.asked_slots.append("property_type")

    extracted = extract_turn("Квартира в Москве.", state=state)

    assert extracted.facts["property_type"] == "apartment"
    assert extracted.facts["property_region"] == "Москва"


def test_property_availability_still_sets_property_fact() -> None:
    extracted = extract_turn("Есть квартира в собственности")

    assert extracted.facts["has_property"] is True
    assert extracted.facts["property_type"] == "apartment"


def test_property_negative_sets_no_property() -> None:
    extracted = extract_turn("Квартиры нет, жилья в собственности нет")

    assert extracted.facts["has_property"] is False
    assert "property_type" not in extracted.facts


def test_property_ownership_phrase_sets_property_fact() -> None:
    extracted = extract_turn("Квартира в собственности")

    assert extracted.facts["has_property"] is True
    assert extracted.facts["property_type"] == "apartment"


def test_wants_to_pay_is_not_hard_debt_procedure_refusal() -> None:
    extracted = extract_turn("Хочу платить")

    assert extracted.facts["client_wants_to_pay"] is True
    assert "client_refuses_debt_procedure" not in extracted.facts


def test_bankruptcy_resistance_is_concern_not_hard_refusal() -> None:
    extracted = extract_turn("Банкротство не хочу, хочу платить")

    assert extracted.facts["client_wants_to_pay"] is True
    assert extracted.facts["client_fears_bankruptcy"] is True
    assert "client_refuses_debt_procedure" not in extracted.facts


def test_bankruptcy_resistance_alone_is_not_hard_refusal() -> None:
    extracted = extract_turn("Банкротство не хочу")

    assert extracted.facts["client_fears_bankruptcy"] is True
    assert "client_refuses_debt_procedure" not in extracted.facts


@pytest.mark.parametrize(
    "text",
    [
        "Никаких судов",
        "Суды не рассматриваю",
        "Юридические процедуры не хочу",
        "Никакого банкротства и реструктуризации",
        "Не хочу никакие процедуры",
    ],
)
def test_hard_debt_procedure_refusal_requires_explicit_hard_phrase(text: str) -> None:
    extracted = extract_turn(text)
    assert extracted.facts["client_refuses_debt_procedure"] is True


def test_combined_hard_debt_procedure_refusal_phrase() -> None:
    extracted = extract_turn("Никаких судов и юридических процедур не хочу")

    assert extracted.facts["client_refuses_debt_procedure"] is True


def test_vehicle_retention_pronoun_requires_vehicle_context() -> None:
    extracted = extract_turn("Она для работы")

    assert "has_car" not in extracted.facts
    assert "explicit_pts_intent" not in extracted.facts
    assert "vehicle_requires_retention" not in extracted.facts


def test_vehicle_retention_with_vehicle_context_is_retention_not_hard_refusal() -> None:
    extracted = extract_turn("Машину отдавать не буду, она для работы")

    assert extracted.facts["has_car"] is True
    assert extracted.facts["explicit_pts_intent"] is True
    assert extracted.facts["vehicle_requires_retention"] is True
    assert extracted.facts["vehicle_refuses_transfer"] is True
    assert extracted.facts["vehicle_refuses_collateral"] is False


def test_vehicle_pts_semantic_consideration_with_retention_is_not_collateral_refusal() -> None:
    text = (
        "Машину можно рассмотреть, но отдавать её не готов — она каждый день нужна. "
        "Если вариант с ПТС, то только чтобы машина оставалась у меня."
    )
    evidence = detect_vehicle_intent(text)
    extracted = extract_turn(text)

    assert evidence.has_vehicle_context is True
    assert evidence.auto_collateral_consideration is True
    assert evidence.explicit_pts_channel is True
    assert evidence.retention_required is True
    assert evidence.transfer_refusal is True
    assert evidence.hard_collateral_refusal is False
    assert extracted.facts["has_car"] is True
    assert extracted.facts["explicit_pts_intent"] is True
    assert extracted.facts["early_need_signal"] == "explicit_pts"
    assert extracted.facts["vehicle_requires_retention"] is True
    assert extracted.facts["vehicle_refuses_transfer"] is True
    assert extracted.facts["vehicle_refuses_collateral"] is False
    assert extracted.route_rejection is None


def test_pts_channel_with_retention_condition_is_positive_pts_intent() -> None:
    extracted = extract_turn("Если вариант с ПТС, то только чтобы машина оставалась у меня.")

    assert extracted.facts["has_car"] is True
    assert extracted.facts["explicit_pts_intent"] is True
    assert extracted.facts["vehicle_requires_retention"] is True
    assert extracted.facts["vehicle_refuses_transfer"] is True
    assert extracted.facts["vehicle_refuses_collateral"] is False
    assert extracted.route_rejection is None


@pytest.mark.parametrize(
    "text",
    [
        "Машину можно рассмотреть",
        "Авто можно рассмотреть",
        "Машину готов рассмотреть",
        "Можно по машине",
        "Если через машину",
    ],
)
def test_detect_vehicle_intent_soft_auto_consideration(text: str) -> None:
    evidence = detect_vehicle_intent(text)

    assert evidence.has_vehicle_context is True
    assert evidence.auto_collateral_consideration is True
    assert evidence.hard_collateral_refusal is False


@pytest.mark.parametrize(
    "text",
    [
        "Под ПТС",
        "Вариант с ПТС",
        "По ПТС",
        "Через ПТС",
        "Под авто",
        "Под машину",
    ],
)
def test_detect_vehicle_intent_explicit_pts_or_auto_channel(text: str) -> None:
    evidence = detect_vehicle_intent(text)

    assert evidence.has_vehicle_context is True
    assert evidence.explicit_pts_channel is True
    assert evidence.hard_collateral_refusal is False


@pytest.mark.parametrize(
    "text",
    [
        "Отдавать её не готов",
        "Отдавать ее не готов",
        "Отдавать машину не готов",
        "Машину отдавать не буду",
        "Она каждый день нужна",
        "Машина нужна каждый день",
        "Машина должна остаться у меня",
        "Чтобы машина оставалась у меня",
        "Пользоваться машиной нужно",
        "Машина нужна для работы",
    ],
)
def test_detect_vehicle_intent_retention_with_vehicle_context(text: str) -> None:
    state = DialogueV3State(session_id="vehicle-retention")
    state.merge_facts({"has_car": True}, source="form")

    evidence = detect_vehicle_intent(text, state)

    assert evidence.has_vehicle_context is True
    assert evidence.retention_required is True or evidence.transfer_refusal is True
    assert evidence.hard_collateral_refusal is False


@pytest.mark.parametrize(
    "text",
    [
        "ПТС не рассматриваю",
        "Залог на машину не хочу",
        "Машину вообще не трогаем",
        "Никаких автозалогов",
        "Авто не трогаем",
    ],
)
def test_detect_vehicle_intent_hard_collateral_refusal(text: str) -> None:
    evidence = detect_vehicle_intent(text)

    assert evidence.hard_collateral_refusal is True
    assert evidence.retention_required is False


def test_bare_pts_mention_is_channel_evidence_not_positive_intent() -> None:
    evidence = detect_vehicle_intent("Что такое ПТС?")
    extracted = extract_turn("Что такое ПТС?")

    assert evidence.has_vehicle_context is True
    assert evidence.explicit_pts_channel is False
    assert evidence.auto_collateral_consideration is False
    assert "explicit_pts_intent" not in extracted.facts
    assert extracted.facts["has_car"] is True
    assert extracted.route_rejection is None


def test_explicit_pts_channel_maps_to_pts_intent() -> None:
    extracted = extract_turn("По ПТС можно посмотреть?")

    assert extracted.facts["has_car"] is True
    assert extracted.facts["explicit_pts_intent"] is True
    assert extracted.facts["early_need_signal"] == "explicit_pts"


def test_explicit_pts_channel_with_hard_refusal_keeps_contradictory_facts() -> None:
    extracted = extract_turn("По ПТС не рассматриваю.")

    assert extracted.facts["has_car"] is True
    assert extracted.facts["explicit_pts_intent"] is True
    assert extracted.facts["vehicle_refuses_collateral"] is True
    assert extracted.facts["route_rejection"] == "PTS"
    assert extracted.route_rejection == "PTS"


def test_vehicle_availability_phrase_sets_car_fact_not_pts_intent() -> None:
    extracted = extract_turn("У меня есть машина")

    assert extracted.facts["has_car"] is True
    assert "explicit_pts_intent" not in extracted.facts
    assert extracted.facts.get("early_need_signal") != "explicit_pts"


def test_vehicle_retention_pronoun_uses_existing_car_context() -> None:
    state = DialogueV3State(session_id="vehicle-context")
    state.merge_facts({"has_car": True}, source="form")

    extracted = extract_turn("Она для работы", state=state)

    assert extracted.facts["explicit_pts_intent"] is True
    assert extracted.facts["vehicle_requires_retention"] is True
    assert extracted.facts["vehicle_refuses_transfer"] is True
    assert extracted.facts["vehicle_refuses_collateral"] is False


def test_get_last_asked_slot_prefers_asked_slots() -> None:
    state = DialogueV3State(session_id="last-slot")
    state.asked_slots.extend(["total_debt", "monthly_payments"])
    state.trace_history.append({"next_slot": "comfortable_payment"})

    assert get_last_asked_slot(state) == "monthly_payments"


@pytest.mark.parametrize(
    "text",
    [
        "ПТС не рассматриваю",
        "Не хочу залог на машину",
        "Машину вообще не трогаем",
        "Никаких автозалогов",
        "Авто не трогаем",
    ],
)
def test_vehicle_collateral_refusal_is_not_pts_intent(text: str) -> None:
    extracted = extract_turn(text)

    assert extracted.facts["vehicle_refuses_collateral"] is True
    assert extracted.route_rejection == "PTS"
    assert "explicit_pts_intent" not in extracted.facts


def test_vehicle_collateral_refusal_can_coexist_with_separate_pts_intent() -> None:
    extracted = extract_turn("Хочу под ПТС, но ПТС не рассматриваю")

    assert extracted.facts["explicit_pts_intent"] is True
    assert extracted.facts["vehicle_refuses_collateral"] is True


def test_amounts_follow_last_asked_slot_context() -> None:
    state = DialogueV3State(session_id="facts-context")
    state.merge_facts({"has_current_loans": True}, source="form")
    engine = DialogueV3Engine()

    first = engine.handle_turn("Хочу закрыть долги", state)
    assert first.route_session.next_slot == "total_debt"

    second = engine.handle_turn("Около 1.7 млн", first.state)
    assert second.extracted.facts["total_debt"] == 1_700_000
    assert second.route_session.next_slot == "monthly_payments"

    third = engine.handle_turn("78 тысяч", second.state)
    assert third.extracted.facts["monthly_payments"] == 78_000
    assert third.route_session.next_slot == "income_status"

    fourth = engine.handle_turn("125 тысяч, работаю официально", third.state)
    assert fourth.extracted.facts["official_income"] == 125_000
    assert fourth.extracted.facts["income_status"] == "stable"
    assert fourth.route_session.next_slot == "comfortable_payment"

    fifth = engine.handle_turn("35 тысяч", fourth.state)
    assert fifth.extracted.facts["comfortable_payment"] == 35_000


def test_income_slot_answer_with_monthly_phrase_does_not_overwrite_monthly_payments() -> None:
    state = DialogueV3State(session_id="income-context")
    state.merge_facts({"monthly_payments": 34_000})
    state.asked_slots.append("income_status")

    extracted = extract_turn("Официальный, работаю по найму. Доход примерно 115 тысяч в месяц.", state=state)

    assert extracted.facts["official_income"] == 115_000
    assert extracted.facts["income_status"] == "stable"
    assert "monthly_payments" not in extracted.facts


def test_income_phrase_without_slot_context_does_not_create_monthly_payment() -> None:
    extracted = extract_turn("Официально работаю по найму, доход примерно 115 тысяч в месяц.")

    assert extracted.facts["official_income"] == 115_000
    assert extracted.facts["income_status"] == "stable"
    assert "monthly_payments" not in extracted.facts


def test_income_slot_wins_when_income_and_monthly_contexts_both_appear() -> None:
    state = DialogueV3State(session_id="income-beats-monthly-context")
    state.merge_facts({"monthly_payments": 34_000})
    state.asked_slots.append("income_status")

    extracted = extract_turn(
        "Платеж 34 уже писал, доход примерно 115 тысяч в месяц.",
        state=state,
    )

    assert extracted.facts["official_income"] == 115_000
    assert extracted.facts["income_status"] == "stable"
    assert "monthly_payments" not in extracted.facts
    assert state.fact_value("monthly_payments") == 34_000


def test_payment_label_correction_extracts_monthly_not_total_debt() -> None:
    state = DialogueV3State(session_id="payment-label-correction")
    state.merge_facts({"total_debt": 1_100_000, "monthly_payments": 58_000})
    state.asked_slots.append("income_status")

    extracted = extract_turn("Нет, 58 тысяч — это платежи по долгам.", state=state)

    assert extracted.facts["monthly_payments"] == 58_000
    assert "total_debt" not in extracted.facts


def test_income_phrase_with_existing_payment_does_not_update_total_debt_or_monthly() -> None:
    state = DialogueV3State(session_id="income-after-payment-correction")
    state.merge_facts({"total_debt": 1_100_000, "monthly_payments": 58_000})
    state.asked_slots.append("income_status")

    extracted = extract_turn("Доход у меня около 170 тысяч в месяц, официально работаю.", state=state)

    assert extracted.facts["official_income"] == 170_000
    assert extracted.facts["income_status"] == "stable"
    assert "monthly_payments" not in extracted.facts
    assert "total_debt" not in extracted.facts


def test_explicit_total_debt_correction_can_update_total_debt() -> None:
    state = DialogueV3State(session_id="total-debt-correction")
    state.merge_facts({"total_debt": 1_100_000})
    state.asked_slots.append("income_status")

    extracted = extract_turn("Нет, долг не 1,1, а 1,3 млн.", state=state)

    assert extracted.facts["total_debt"] == 1_300_000
    assert "monthly_payments" not in extracted.facts
    assert "official_income" not in extracted.facts


@pytest.mark.parametrize(
    "text",
    [
        "Доход 115 тысяч",
        "115 тысяч в месяц",
        "официально 115",
        "работаю, получаю 115",
    ],
)
def test_income_slot_prioritizes_official_income_over_monthly_payment(text: str) -> None:
    state = DialogueV3State(session_id="income-priority")
    state.merge_facts({"monthly_payments": 34_000})
    state.asked_slots.append("income_status")

    extracted = extract_turn(text, state=state)

    assert extracted.facts["official_income"] == 115_000
    assert extracted.facts["income_status"] == "stable"
    assert "monthly_payments" not in extracted.facts
    assert state.fact_value("monthly_payments") == 34_000


def test_monthly_payment_slot_wins_when_income_and_monthly_contexts_both_appear() -> None:
    state = DialogueV3State(session_id="monthly-beats-income-context")
    state.asked_slots.append("monthly_payments")

    extracted = extract_turn("Доход 115 тысяч в месяц", state=state)

    assert extracted.facts["monthly_payments"] == 115_000
    assert "official_income" not in extracted.facts
    assert "income_status" not in extracted.facts


def test_income_answer_keeps_monthly_payments_closed_and_moves_on() -> None:
    state = DialogueV3State(session_id="income-next-slot")
    state.merge_facts(
        {
            "has_current_loans": True,
            "need_type": "debt_solution",
            "total_debt": 520_000,
            "monthly_payments": 34_000,
        },
        source="form",
    )
    state.asked_slots.append("income_status")

    result = DialogueV3Engine().handle_turn("Доход 115 тысяч в месяц", state)

    assert result.extracted.facts["official_income"] == 115_000
    assert "monthly_payments" not in result.extracted.facts
    assert result.state.fact_value("monthly_payments") == 34_000
    assert "monthly_payments" in result.route_session.closed_primary_slots
    assert result.route_session.next_slot != "monthly_payments"


def test_comfortable_payment_answer_with_monthly_word_does_not_overwrite_monthly_payments() -> None:
    state = DialogueV3State(session_id="comfortable-context")
    state.merge_facts({"monthly_payments": 34_000})
    state.asked_slots.append("comfortable_payment")

    extracted = extract_turn("35 тысяч в месяц", state=state)

    assert extracted.facts["comfortable_payment"] == 35_000
    assert "monthly_payments" not in extracted.facts


def test_comfortable_payment_range_uses_upper_bound() -> None:
    state = DialogueV3State(session_id="comfortable-range")
    state.asked_slots.append("comfortable_payment")

    extracted = extract_turn("25-28 тысяч", state=state)

    assert extracted.facts["comfortable_payment"] == 28_000
    assert "monthly_payments" not in extracted.facts


@pytest.mark.parametrize(
    "text",
    [
        "Комфортно было бы 25–28 тысяч в месяц.",
        "Комфортнее было бы платить где-то 25–28 тысяч в месяц.",
    ],
)
def test_comfortable_payment_semantics_do_not_overwrite_monthly_payment(text: str) -> None:
    state = DialogueV3State(session_id="comfortable-semantic-range")
    state.merge_facts({"monthly_payments": 34_000})
    state.asked_slots.append("comfortable_payment")

    extracted = extract_turn(text, state=state)

    assert extracted.facts["comfortable_payment"] == 28_000
    assert "monthly_payments" not in extracted.facts
    assert state.fact_value("monthly_payments") == 34_000


def test_current_monthly_payment_phrase_sets_monthly_payment() -> None:
    extracted = extract_turn("Сейчас выходит примерно 34 тысячи в месяц.")

    assert extracted.facts["monthly_payments"] == 34_000


def test_multi_amount_payment_phrase_keeps_known_monthly_and_extracts_comfortable() -> None:
    state = DialogueV3State(session_id="multi-amount-comfortable")
    state.merge_facts({"monthly_payments": 34_000})
    state.asked_slots.append("comfortable_payment")

    extracted = extract_turn("Сейчас плачу 34, но комфортнее было бы 25.", state=state)

    assert extracted.facts["comfortable_payment"] == 25_000
    assert "monthly_payments" not in extracted.facts
    assert state.fact_value("monthly_payments") == 34_000


def test_active_dialog_correction_is_not_repeat_visit_service_signal() -> None:
    state = DialogueV3State(session_id="active-correction")
    state.turn_index = 5
    state.merge_facts({"has_current_loans": True, "monthly_payments": 34_000})
    state.asked_slots.append("comfortable_payment")

    extracted = extract_turn("Я уже писал — около 34 тысяч в месяц по двум картам.", state=state)

    assert extracted.service_signal is None
    assert "service_signal" not in extracted.facts
    assert "comfortable_payment" not in extracted.facts


@pytest.mark.parametrize(
    "text",
    [
        "Я уже писал — около 34 тысяч в месяц",
        "Я уже написал выше — около 34 тысяч",
        "Я уже говорил, примерно 34 тысячи",
        "Я же сказал — 34 тысячи",
        "Я уже отвечал на это",
        "Выше написал: 34 тысячи",
        "Я это уже указал",
        "Повторяю, 34 тысячи в месяц",
    ],
)
def test_active_dialog_correction_phrases_do_not_select_repeat_visit(text: str) -> None:
    state = DialogueV3State(session_id="active-correction-route")
    state.turn_index = 3
    state.merge_facts(
        {
            "has_current_loans": True,
            "need_type": "debt_solution",
            "total_debt": 520_000,
            "monthly_payments": 34_000,
        }
    )
    state.asked_slots.append("monthly_payments")

    result = DialogueV3Engine().handle_turn(text, state)

    assert result.extracted.service_signal is None
    assert result.extracted.facts.get("service_signal") is None
    assert result.route_session.selected_route != REPEAT_VISIT
    assert result.route_session.terminal_action != REPEAT_HANDOFF
    assert result.state.fact_value("monthly_payments") == 34_000


@pytest.mark.parametrize(
    "text",
    [
        "Я уже обращался",
        "Я уже оставлял заявку",
        "Я уже переходил в чат",
        "Мне не ответили",
        "Со мной не связались",
        "По старой заявке",
        "Продолжить прошлую заявку",
        "Раньше писал вам и не ответили",
        "Я уже оставлял заявку, со мной не связались.",
    ],
)
def test_explicit_previous_company_contact_still_selects_repeat_visit(text: str) -> None:
    result = DialogueV3Engine().handle_turn(text)

    assert result.extracted.service_signal == "repeat_visit"
    assert result.route_session.selected_route == REPEAT_VISIT
    assert result.route_session.terminal_action == REPEAT_HANDOFF


def test_active_context_previous_message_reference_is_correction_not_repeat_visit() -> None:
    state = DialogueV3State(session_id="active-reference")
    state.turn_index = 3

    extracted = extract_turn("Я уже писал выше.", state=state)

    assert extracted.facts["correction_signal"] is True
    assert extracted.service_signal != "repeat_visit"
    assert extracted.facts.get("service_signal") != "repeat_visit"


def test_manual_ui_cards_repair_hotfix_flow() -> None:
    state = DialogueV3State(session_id="manual-ui-hotfix")
    state.merge_facts(
        {
            "desired_amount": 680_000,
            "full_name": "Громов Денис Андреевич",
            "has_current_loans": True,
            "employment_type": "employment",
            "has_car": True,
            "asset_type": "Недвижимость",
            "has_property": True,
        },
        source="form",
    )
    engine = DialogueV3Engine()

    first = engine.handle_turn(
        "Хочу закрыть две кредитные карты и немного оставить на ремонт машины.",
        state,
    )
    assert first.extracted.facts["need_type"] == "debt_solution"
    assert first.extracted.facts["purpose_goal"] == "car_repair"
    assert "explicit_pts_intent" not in first.extracted.facts
    assert first.route_session.next_slot == "total_debt"
    assert "need_type" not in first.route_session.missing_primary_slots

    second = engine.handle_turn(
        "В первую очередь закрыть карты. Если получится, часть суммы оставить на ремонт машины.",
        first.state,
    )
    assert second.extracted.facts["need_type"] == "debt_solution"
    assert second.route_session.next_slot == "total_debt"

    third = engine.handle_turn("Около 520 тысяч по двум кредитным картам.", second.state)
    assert third.extracted.facts["total_debt"] == 520_000
    assert third.route_session.next_slot == "monthly_payments"

    fourth = engine.handle_turn("Примерно 34 тысячи в месяц.", third.state)
    assert fourth.extracted.facts["monthly_payments"] == 34_000
    assert fourth.route_session.next_slot == "income_status"

    fifth = engine.handle_turn(
        "Официальный, работаю по найму. Доход примерно 115 тысяч в месяц.",
        fourth.state,
    )
    assert fifth.extracted.facts["official_income"] == 115_000
    assert fifth.extracted.facts["income_status"] == "stable"
    assert "monthly_payments" not in fifth.extracted.facts
    assert fifth.state.fact_value("monthly_payments") == 34_000
    assert fifth.route_session.next_slot in {"comfortable_payment", "delinquency_context"}
    assert fifth.route_session.selected_route != "REPEAT_VISIT"

    sixth = engine.handle_turn("Я уже писал — около 34 тысяч в месяц по двум картам.", fifth.state)
    assert sixth.extracted.service_signal is None
    assert "service_signal" not in sixth.extracted.facts
    assert sixth.route_session.selected_route != "REPEAT_VISIT"
    assert sixth.route_session.terminal_action is None


def test_s02_debt_repair_funnel_collects_payment_semantics_before_pts_switch() -> None:
    state = DialogueV3State(session_id="s02-debt-repair-funnel")
    state.merge_facts(
        {
            "desired_amount": 680_000,
            "has_current_loans": True,
            "has_car": True,
            "employment_type": "найм",
        },
        source="form",
    )
    engine = DialogueV3Engine()

    first = engine.handle_turn(
        "Нужно в основном закрыть две кредитки, и ещё немного оставить на ремонт авто.",
        state,
    )
    second = engine.handle_turn("Там около 520 тысяч всего, это по двум картам.", first.state)
    third = engine.handle_turn("Сейчас выходит примерно 34 тысячи в месяц.", second.state)
    fourth = engine.handle_turn(
        "Да, работаю официально по найму. Зарплата около 115 тысяч в месяц.",
        third.state,
    )
    fifth = engine.handle_turn(
        "Просрочек нет, плачу вовремя. Но комфортнее было бы платить где-то 25–28 тысяч в месяц.",
        fourth.state,
    )

    assert fifth.route_session.terminal_action is None
    assert [event.action_id for event in fifth.events] != [HANDOFF_BFL_SPECIALIST]
    assert fifth.route_session.next_slot != "monthly_payments"
    assert fifth.route_session.next_slot != "urgency"
    assert fifth.route_session.next_slot != "loan_types"
    assert fifth.route_session.next_slot == "collateral_preference"
    assert fifth.events == []
    assert fifth.state.fact_value("monthly_payments") == 34_000
    assert fifth.state.fact_value("comfortable_payment") == 28_000
    assert fifth.state.fact_value("loan_types") == ("credit_cards",)
    assert fifth.state.fact_value("has_arrears") is False

    sixth = engine.handle_turn(
        "Машину как вариант можно обсуждать, но без того, чтобы её забирать. Она нужна каждый день.",
        fifth.state,
    )

    assert sixth.route_session.selected_route == PTS
    assert sixth.route_session.next_slot == "car_brand_model"
    assert sixth.frame.vehicle_requires_retention is True
    assert sixth.frame.vehicle_refuses_collateral is False
    assert sixth.route_session.terminal_action is None


@pytest.mark.parametrize(
    ("slot", "text", "fact_key", "expected"),
    [
        ("total_debt", "1.7 млн", "total_debt", 1_700_000),
        ("monthly_payments", "78 тысяч", "monthly_payments", 78_000),
        ("comfortable_payment", "35 тысяч", "comfortable_payment", 35_000),
    ],
)
def test_short_amounts_use_asked_slot_context(
    slot: str,
    text: str,
    fact_key: str,
    expected: int,
) -> None:
    state = DialogueV3State(session_id=f"amount-{slot}")
    state.asked_slots.append(slot)

    extracted = extract_turn(text, state=state)

    assert extracted.facts[fact_key] == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Примерно 1 миллион 450 тысяч.", 1_450_000),
        ("1 млн 450 тысяч", 1_450_000),
        ("1,45 млн", 1_450_000),
    ],
)
def test_composite_million_amounts_use_full_value(text: str, expected: int) -> None:
    state = DialogueV3State(session_id="composite-amount")
    state.asked_slots.append("total_debt")

    extracted = extract_turn(text, state=state)

    assert extracted.facts["total_debt"] == expected


def test_word_million_amount_uses_total_debt_context() -> None:
    state = DialogueV3State(session_id="word-million-total-debt")
    state.asked_slots.append("total_debt")

    extracted = extract_turn("Около миллион семьсот.", state=state)

    assert extracted.facts["total_debt"] == 1_700_000


def test_month_duration_does_not_fill_contextual_payment_amount() -> None:
    state = DialogueV3State(session_id="month-duration")
    state.asked_slots.append("monthly_payments")

    extracted = extract_turn("Дохода стабильного нет, просрочка 3 месяца", state=state)

    assert "monthly_payments" not in extracted.facts
    assert extracted.facts["arrears_months"] == 3.0


def test_standalone_amount_without_context_is_not_total_debt() -> None:
    extracted = extract_turn("1.7 млн")

    assert "total_debt" not in extracted.facts


def test_monthly_payment_keyword_extracts_without_previous_context() -> None:
    extracted = extract_turn("78 тысяч в месяц")

    assert extracted.facts["monthly_payments"] == 78_000


def test_comfortable_payment_does_not_match_mfo() -> None:
    extracted = extract_turn("Мне комфортно платить 35 тысяч")

    assert extracted.facts["comfortable_payment"] == 35_000
    assert extracted.facts.get("has_mfo") is not True


def test_mfo_token_and_arrears_extract_debt_signals() -> None:
    extracted = extract_turn("Есть МФО и просрочка")

    assert extracted.facts["has_mfo"] is True
    assert extracted.facts["has_arrears"] is True


def test_income_amount_with_official_marker() -> None:
    extracted = extract_turn("125 тысяч, официально работаю")

    assert extracted.facts["official_income"] == 125_000
    assert extracted.facts["income_status"] == "stable"


def test_unofficial_income_marker_is_not_stable_official_income() -> None:
    state = DialogueV3State(session_id="unofficial-income")
    state.asked_slots.append("income_status")

    extracted = extract_turn("Неофициально.", state=state)

    assert extracted.facts["income_status"] == "no_official_income"
    assert "official_income" not in extracted.facts


def test_no_income_phrase_closes_income_status_as_none() -> None:
    state = DialogueV3State(session_id="no-income")
    state.asked_slots.append("income_status")

    extracted = extract_turn("Нет дохода.", state=state)

    assert extracted.facts["income_status"] == "none"


def test_no_stable_income_and_arrears_months_do_not_create_income_amount() -> None:
    extracted = extract_turn("Дохода стабильного нет, просрочка 3 месяца, коллекторы звонят")

    assert extracted.facts["income_status"] == "unstable"
    assert extracted.facts["has_arrears"] is True
    assert extracted.facts["arrears_months"] == 3.0
    assert extracted.facts["collector_pressure"] is True
    assert "official_income" not in extracted.facts


@pytest.mark.parametrize(
    ("text", "expected_months"),
    [
        ("Да, просрочки уже есть, примерно пару месяцев.", 2.0),
        ("Просрочка два месяца.", 2.0),
        ("Просрочки около двух месяцев.", 2.0),
        ("Месяц просрочки.", 1.0),
    ],
)
def test_arrears_duration_parser_handles_common_month_phrases(
    text: str,
    expected_months: float,
) -> None:
    extracted = extract_turn(text)

    assert extracted.facts["has_arrears"] is True
    assert extracted.facts["arrears_months"] == expected_months


def test_no_stable_income_extracts_even_when_last_slot_was_monthly_payment() -> None:
    state = DialogueV3State(session_id="unstable-income-after-payment-question")
    state.asked_slots.append("monthly_payments")

    extracted = extract_turn(
        "Дохода стабильного нет, просрочка 3 месяца, коллекторы звонят",
        state=state,
    )

    assert extracted.facts["income_status"] == "unstable"
    assert extracted.facts["has_arrears"] is True
    assert extracted.facts["arrears_months"] == 3.0
    assert extracted.facts["collector_pressure"] is True
    assert "official_income" not in extracted.facts
    assert "monthly_payments" not in extracted.facts


def test_conflicting_fact_is_not_treated_as_closed_slot() -> None:
    state = DialogueV3State(session_id="conflict")
    state.turn_index = 1
    state.merge_facts({"total_debt": 1_000_000})
    state.turn_index = 2
    state.merge_facts({"total_debt": 2_000_000})

    assert state.facts["total_debt"].quality == "conflicting"
    assert state.fact_value("total_debt") is None
    assert is_slot_closed("total_debt", state=state, frame=build_case_frame(state)) is False
