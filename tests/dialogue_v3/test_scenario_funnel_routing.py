from __future__ import annotations

import app_v3

from mbk_refactor.dialogue_v3.engine import DialogueV3Engine, DialogueV3TurnResult
from mbk_refactor.dialogue_v3.state import DialogueV3State


def start_state(form: dict[str, object]) -> DialogueV3State:
    state, _ = app_v3.start_chat_from_form(form, session_id="scenario-funnel")
    return state


def run_turns(state: DialogueV3State, turns: list[str]) -> DialogueV3TurnResult:
    engine = DialogueV3Engine()
    result: DialogueV3TurnResult | None = None
    for turn in turns:
        result = engine.handle_turn(turn, state)
        state = result.state
    assert result is not None
    return result


def multi_asset_form() -> dict[str, object]:
    return {
        "ФИО": "Виктор Семёнович",
        "Сумма": 645_467,
        "Есть текущие кредиты или займы?": True,
        "Есть ли в собственности авто?": True,
        "Тип актива": "Недвижимость",
    }


def credit_and_car_form() -> dict[str, object]:
    return {
        "Есть текущие кредиты или займы?": True,
        "Есть ли в собственности авто?": True,
    }


def test_generic_money_with_credit_and_car_form_stays_discovery_need_type() -> None:
    result = run_turns(start_state(credit_and_car_form()), ["Хочу взять денег"])

    assert result.route_session.selected_route == "DISCOVERY"
    assert result.route_session.next_slot == "need_type"
    assert result.route_session.terminal_action is None


def test_generic_money_request_asks_funnel_question_not_collateral_slot() -> None:
    result = run_turns(start_state(multi_asset_form()), ["Хочу взять денег"])

    assert result.route_session.selected_route == "DISCOVERY"
    assert result.route_session.phase == "DISCOVERY"
    assert result.route_session.next_slot == "need_type"
    assert result.frame.need_type == "unknown"
    assert result.route_session.terminal_action is None
    assert result.route_session.next_slot not in {"property_type", "car_brand_model", "car_year"}
    assert "квартира, дом или другой объект" not in result.text.lower()
    assert "какая у вас машина" not in result.text.lower()


def test_strong_new_money_closes_need_type_and_does_not_repeat_purpose_question() -> None:
    result = run_turns(start_state(multi_asset_form()), ["Мне нужна сумма на руки"])

    assert result.route_session.selected_route == "DISCOVERY"
    assert result.frame.need_type == "new_money"
    assert "need_type" not in result.route_session.missing_primary_slots
    assert result.route_session.next_slot in {"income_status", "desired_amount_or_total_debt"}
    assert result.route_session.next_slot != "need_type"
    assert "что сейчас главное" not in result.text.lower()


def test_new_money_flow_asks_amount_or_income_not_total_debt_without_debt_evidence() -> None:
    result = run_turns(start_state({}), ["Получить сумму на руки"])

    assert result.route_session.selected_route == "DISCOVERY"
    assert result.frame.need_type == "new_money"
    assert result.route_session.next_slot != "need_type"
    assert result.route_session.next_slot in {"desired_amount_or_total_debt", "income_status"}
    assert result.route_session.next_slot != "total_debt"
    assert result.route_session.terminal_action is None


def test_repair_purpose_without_debt_is_not_mortgage_or_bfl_discovery() -> None:
    result = run_turns(start_state(multi_asset_form()), ["Нужны деньги на ремонт"])

    assert result.route_session.selected_route == "DISCOVERY"
    assert result.frame.early_need_signal == "repair_or_purpose"
    assert result.route_session.primary_slots == [
        "desired_amount_or_total_debt",
        "income_status",
        "urgency",
    ]
    assert result.route_session.next_slot in {"income_status", "desired_amount_or_total_debt", "urgency"}
    assert result.route_session.next_slot not in {"property_type", "total_debt", "car_brand_model"}


def test_car_repair_purpose_without_pts_intent_stays_discovery_not_car_intake() -> None:
    result = run_turns(start_state(multi_asset_form()), ["Нужны деньги на ремонт машины"])

    assert result.route_session.selected_route == "DISCOVERY"
    assert result.route_session.selected_route not in {"PTS", "MORTGAGE_MAIN", "MORTGAGE_AUX"}
    assert result.route_session.terminal_action is None
    assert result.frame.early_need_signal == "repair_or_purpose"
    assert result.state.fact_value("purpose_goal") == "car_repair"
    assert result.frame.explicit_pts_intent is False
    assert result.route_session.next_slot in {"income_status", "desired_amount_or_total_debt", "urgency"}
    assert result.route_session.next_slot not in {"car_brand_model", "car_year", "property_type", "total_debt"}


def test_cards_and_repair_does_not_trigger_mortgage_from_form_asset() -> None:
    result = run_turns(
        start_state(multi_asset_form()),
        ["Хочу закрыть карты и немного оставить на ремонт"],
    )

    assert result.route_session.selected_route != "MORTGAGE_AUX"
    assert result.route_session.selected_route == "DISCOVERY"
    assert result.route_session.phase == "DISCOVERY"
    assert result.route_session.next_slot in {
        "total_debt",
        "monthly_payments",
    }
    assert result.route_session.next_slot != "property_type"
    assert result.route_session.next_slot != "car_brand_model"


def test_s02_clean_cards_and_car_repair_stays_discovery_without_premature_terminal() -> None:
    state = start_state(
        {
            "Сумма": 680_000,
            "Есть текущие кредиты или займы?": True,
            "Есть ли в собственности авто?": True,
            "Тип занятости": "найм",
        }
    )
    engine = DialogueV3Engine()

    first = engine.handle_turn(
        "Хочу закрыть две кредитные карты и немного оставить на ремонт машины.",
        state,
    )
    assert first.extracted.facts["need_type"] == "debt_solution"
    assert first.extracted.facts["purpose_goal"] == "car_repair"
    assert first.route_session.selected_route == "DISCOVERY"
    assert first.route_session.next_slot == "total_debt"
    assert first.route_session.terminal_action is None
    assert first.route_session.next_slot != "property_type"
    assert first.route_session.next_slot != "car_brand_model"
    assert "explicit_pts_intent" not in first.extracted.facts

    second = engine.handle_turn("Около 520 тысяч по двум кредитным картам.", first.state)
    assert second.extracted.facts["total_debt"] == 520_000
    assert second.route_session.next_slot == "monthly_payments"

    third = engine.handle_turn("Примерно 34 тысячи в месяц.", second.state)
    assert third.extracted.facts["monthly_payments"] == 34_000
    assert third.route_session.next_slot == "income_status"

    fourth = engine.handle_turn(
        "Официально работаю по найму, доход примерно 115 тысяч в месяц.",
        third.state,
    )
    assert fourth.extracted.facts["official_income"] == 115_000
    assert fourth.extracted.facts["income_status"] == "stable"
    assert fourth.route_session.terminal_action is None

    fifth = engine.handle_turn(
        "Просрочек нет, всё плачу по графику. Комфортно было бы где-то 25-28 тысяч в месяц.",
        fourth.state,
    )
    assert fifth.extracted.facts["comfortable_payment"] == 28_000
    assert fifth.extracted.facts["has_arrears"] is False
    assert "monthly_payments" not in fifth.extracted.facts
    assert fifth.state.fact_value("monthly_payments") == 34_000
    assert fifth.state.facts["monthly_payments"].quality != "conflicting"
    assert "monthly_payments" in fifth.route_session.closed_primary_slots
    assert fifth.route_session.next_slot != "monthly_payments"
    assert fifth.route_session.next_slot != "urgency"
    assert fifth.route_session.next_slot == "collateral_preference"
    assert "готов ли клиент рассмотреть авто" in (fifth.actor_move.question_goal or "")
    assert fifth.route_session.terminal_action is None
    assert [event.action_id for event in fifth.events] == []
    assert fifth.route_session.selected_route == "DISCOVERY"
    assert fifth.route_session.selected_route != "BFL_RD"
    assert fifth.route_session.selected_route != "BFL_RI"
    assert fifth.route_session.selected_route not in {"MORTGAGE_MAIN", "MORTGAGE_AUX"}
    assert fifth.route_session.selected_route != "PTS"
    assert "машину как вариант" in fifth.text.lower()

    sixth = engine.handle_turn(
        "Машину можно рассмотреть, но отдавать ее не готов - она каждый день нужна. "
        "Если вариант с ПТС, то только чтобы машина оставалась у меня.",
        fifth.state,
    )
    assert sixth.route_session.selected_route == "PTS"
    assert sixth.route_session.next_slot == "car_brand_model"
    assert sixth.frame.vehicle_requires_retention is True
    assert sixth.frame.vehicle_refuses_collateral is False


def test_s02_comfortable_payment_variant_does_not_reopen_monthly_payment() -> None:
    state = start_state(
        {
            "Сумма": 680_000,
            "Есть текущие кредиты или займы?": True,
            "Есть ли в собственности авто?": True,
            "Тип занятости": "найм",
        }
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
        "Просрочек нет, плачу вовремя. Но комфортнее было бы платить где-то 25-28 тысяч в месяц.",
        fourth.state,
    )

    assert third.extracted.facts["monthly_payments"] == 34_000
    assert fifth.extracted.facts["comfortable_payment"] == 28_000
    assert fifth.extracted.facts["has_arrears"] is False
    assert "monthly_payments" not in fifth.extracted.facts
    assert fifth.state.fact_value("monthly_payments") == 34_000
    assert fifth.state.facts["monthly_payments"].quality != "conflicting"
    assert "monthly_payments" in fifth.route_session.closed_primary_slots
    assert fifth.route_session.next_slot != "monthly_payments"
    assert fifth.route_session.terminal_action is None
    assert [event.action_id for event in fifth.events] == []
    assert fifth.route_session.selected_route == "DISCOVERY"
    assert fifth.route_session.selected_route not in {
        "BFL_RD",
        "BFL_RI",
        "MORTGAGE_MAIN",
        "MORTGAGE_AUX",
        "PTS",
    }


def test_debt_discovery_uses_debt_slots() -> None:
    result = run_turns(start_state(multi_asset_form()), ["Хочу закрыть долги"])

    assert result.route_session.selected_route == "DISCOVERY"
    assert result.frame.need_type == "debt_solution"
    assert result.route_session.primary_slots[0] == "total_debt"
    assert result.route_session.next_slot == "total_debt"


def test_explicit_pts_retention_beats_form_mortgage_asset() -> None:
    result = run_turns(
        start_state(multi_asset_form()),
        ["Хочу закрыть долги, но машину отдавать не буду, она каждый день нужна"],
    )

    assert result.route_session.selected_route == "PTS"
    assert result.route_session.next_slot == "car_brand_model"
    assert result.frame.vehicle_requires_retention is True
    assert result.frame.vehicle_refuses_collateral is False


def test_explicit_mortgage_can_start_property_intake() -> None:
    result = run_turns(
        start_state({"Сумма": 2_000_000, "Тип актива": "Недвижимость"}),
        ["Хочу рассмотреть под квартиру"],
    )

    assert result.route_session.selected_route in {"MORTGAGE_MAIN", "MORTGAGE_AUX"}
    assert result.route_session.next_slot == "property_type"


def test_mortgage_property_type_reply_closes_type_and_moves_to_owner() -> None:
    state = start_state(
        {
            "Сумма": 2_800_000,
            "Есть текущие кредиты или займы?": True,
            "Тип актива": "Недвижимость",
        }
    )
    engine = DialogueV3Engine()

    first = engine.handle_turn(
        "Хочу рассмотреть деньги под квартиру, чтобы закрыть часть кредитов.",
        state,
    )
    assert first.route_session.selected_route in {"MORTGAGE_MAIN", "MORTGAGE_AUX"}
    assert first.route_session.next_slot == "property_type"

    second = engine.handle_turn("Квартира в Москве.", first.state)
    second_lowered = second.text.lower()

    assert second.route_session.selected_route == "MORTGAGE_MAIN"
    assert second.state.fact_value("property_type") == "apartment"
    assert second.state.fact_value("property_region") == "Москва"
    assert second.route_session.next_slot == "property_owner_or_ownership"
    assert "это квартира, дом или другой объект" not in second_lowered

    third = engine.handle_turn("Я собственник, квартира оформлена на меня.", second.state)

    assert third.frame.property_owner_known is True
    assert third.route_session.next_slot == "property_encumbrance_basic"


def test_bfl_rd_multiturn_wants_to_pay_funnel_reaches_handoff() -> None:
    result = run_turns(
        start_state({"Есть текущие кредиты или займы?": True, "Тип занятости": "найм"}),
        [
            "Хочу взять денег",
            "Хочу закрыть долги, платежи тяжело тянуть",
            "Около 1.7 млн",
            "78 тысяч в месяц",
            "Доход 125 тысяч, работаю официально",
            "35 тысяч было бы нормально",
            "Просрочка около месяца. Банкротство не хочу, хочу платить",
        ],
    )

    assert result.route_session.selected_route == "BFL_RD"
    assert result.route_session.terminal_action == "HANDOFF_BFL_SPECIALIST"
    assert [event.action_id for event in result.events] == ["HANDOFF_BFL_SPECIALIST"]


def test_bfl_ri_multiturn_mfo_collectors_reaches_handoff() -> None:
    result = run_turns(
        start_state({"Есть текущие кредиты или займы?": True}),
        [
            "Хочу закрыть долги",
            "Около 2 млн, много МФО",
            "Дохода стабильного нет, просрочка 3 месяца, коллекторы звонят",
        ],
    )

    assert result.route_session.selected_route == "BFL_RI"
    assert result.route_session.terminal_action == "HANDOFF_BFL_SPECIALIST"
    assert [event.action_id for event in result.events] == ["HANDOFF_BFL_SPECIALIST"]


def test_mfo_credit_bureau_objection_is_handled_as_on_topic_objection() -> None:
    first = run_turns(start_state({"Есть текущие кредиты или займы?": True}), ["Хочу закрыть долги"])
    second = DialogueV3Engine().handle_turn("МФО портит рейтинг, ОКБ это видит", first.state)

    lowered = second.text.lower()

    assert second.frame.off_topic_kind is None
    assert second.frame.mfo_rating_concern is True
    assert second.actor_move.move_type == "handle_objection_then_ask"
    assert second.actor_move.client_concern == "mfo_rating_concern"
    assert second.route_session.next_slot == "total_debt"
    assert "прав" in lowered or "видит" in lowered or "мфо" in lowered
    assert second.text.count("?") == 1


def test_fraud_overrides_funnel_and_product_intake() -> None:
    result = run_turns(
        start_state({"Сумма": 600_000, "Тип актива": "Недвижимость"}),
        ["Мне позвонили от вашего имени и попросили код из СМС"],
    )

    assert result.route_session.selected_route == "FRAUD_CHECK"
    assert result.route_session.terminal_action == "SECURITY_FLOW"
    assert result.route_session.next_slot is None
    assert [event.action_id for event in result.events] == ["SECURITY_FLOW"]
