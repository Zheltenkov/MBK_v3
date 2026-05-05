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
    assert result.route_session.next_slot in {"desired_amount_or_total_debt", "income_status"}
    assert result.route_session.next_slot != "total_debt"


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


def test_debt_discovery_uses_debt_slots() -> None:
    result = run_turns(start_state(multi_asset_form()), ["Хочу закрыть долги"])

    assert result.route_session.selected_route == "DISCOVERY"
    assert result.frame.need_type == "debt_solution"
    assert result.route_session.primary_slots[0] == "total_debt"
    assert result.route_session.next_slot == "total_debt"


def test_route_priority_explicit_mortgage_beats_debt_solution() -> None:
    result = run_turns(
        start_state({"Сумма": 2_800_000, "Тип актива": "Недвижимость"}),
        ["Хочу взять под залог квартиры, часть закрыть кредиты."],
    )

    assert result.state.fact_value("explicit_mortgage_intent") is True
    assert result.route_session.selected_route in {"MORTGAGE_MAIN", "MORTGAGE_AUX"}
    assert result.route_session.selected_route != "DISCOVERY"
    assert result.route_session.next_slot in {
        "property_type",
        "property_owner_or_ownership",
        "property_encumbrance_basic",
    }
    assert result.route_session.next_slot not in {"total_debt", "monthly_payments", "income_status"}
    assert result.route_session.terminal_action is None


def test_route_priority_debt_solution_without_explicit_collateral_stays_funnel() -> None:
    result = run_turns(
        start_state(
            {
                "Сумма": 2_800_000,
                "Есть текущие кредиты или займы?": True,
                "Тип актива": "Недвижимость",
            }
        ),
        ["Хочу закрыть кредиты и снизить платеж."],
    )

    assert result.state.fact_value("explicit_mortgage_intent") is not True
    assert result.route_session.selected_route == "DISCOVERY"
    assert result.route_session.selected_route not in {"MORTGAGE_MAIN", "MORTGAGE_AUX"}
    assert result.route_session.next_slot == "total_debt"
    assert result.route_session.terminal_action is None


def test_route_priority_explicit_pts_beats_repair_with_retention_constraint() -> None:
    result = run_turns(
        start_state({"Сумма": 680_000, "Есть ли в собственности авто?": True}),
        ["Хочу под ПТС, машину отдавать не хочу, нужна каждый день."],
    )

    assert result.route_session.selected_route == "PTS"
    assert result.route_session.next_slot == "car_brand_model"
    assert result.frame.vehicle_requires_retention is True
    assert result.frame.vehicle_refuses_collateral is False
    assert result.route_session.terminal_action is None


def test_route_priority_other_not_selected_while_safe_discovery_question_exists() -> None:
    result = run_turns(start_state({}), ["Хочу взять денег."])

    assert result.route_session.selected_route != "OTHER"
    assert result.route_session.next_slot is not None
    assert result.route_session.terminal_action is None


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
    assert result.route_session.next_slot in {
        "property_owner_or_ownership",
        "property_encumbrance_basic",
    }


def test_explicit_mortgage_apartment_collateral_beats_debt_discovery() -> None:
    result = run_turns(
        start_state(
            {
                "Сумма": 2_800_000,
                "Есть текущие кредиты или займы?": True,
                "Тип актива": "Недвижимость",
                "has_property": True,
                "Есть ли в собственности авто?": False,
            }
        ),
        [
            "Хочу взять около 2,8 млн под залог квартиры. "
            "Часть — закрыть кредиты, часть оставить на ремонт."
        ],
    )

    assert result.state.fact_value("explicit_mortgage_intent") is True
    assert result.state.fact_value("property_type") == "apartment"
    assert result.frame.need_type == "debt_solution"
    assert result.route_session.selected_route in {"MORTGAGE_MAIN", "MORTGAGE_AUX"}
    assert result.route_session.selected_route not in {"DISCOVERY", "BFL_RD", "OTHER"}
    assert result.route_session.phase == "COLLECTING_PRIMARY_GATES"
    assert result.route_session.next_slot in {
        "property_region",
        "property_owner_or_ownership",
        "property_encumbrance_basic",
        "property_type",
    }
    assert result.route_session.next_slot not in {
        "total_debt",
        "monthly_payments",
        "income_status",
    }
    assert result.route_session.terminal_action is None
    assert result.events == []


def test_debt_payment_reduction_with_form_property_stays_in_discovery_without_mortgage_words() -> None:
    result = run_turns(
        start_state(
            {
                "Сумма": 2_800_000,
                "Есть текущие кредиты или займы?": True,
                "Тип актива": "Недвижимость",
                "has_property": True,
                "Есть ли в собственности авто?": False,
            }
        ),
        [
            "Хочу закрыть кредиты и снизить ежемесячный платёж. "
            "Сейчас тяжеловато тянуть, плюс немного на ремонт."
        ],
    )

    assert result.state.fact_value("explicit_mortgage_intent") is not True
    assert result.route_session.selected_route != "MORTGAGE_MAIN"
    assert result.route_session.selected_route != "MORTGAGE_AUX"
    assert result.route_session.selected_route == "DISCOVERY"
    assert result.route_session.next_slot == "total_debt"


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
    assert first.state.fact_value("property_type") == "apartment"
    assert first.route_session.next_slot == "property_owner_or_ownership"

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
    assert result.actor_move.move_type == "recommendation_offer"
    assert result.actor_move.pending_terminal_action == "HANDOFF_BFL_SPECIALIST"
    assert result.events == []


def test_bfl_rd_collects_asset_and_family_risk_context_before_handoff() -> None:
    state = start_state(
        {
            "Сумма": 1_800_000,
            "ФИО": "Наталья Викторовна",
            "Есть текущие кредиты или займы?": True,
            "Тип занятости": "найм",
            "Есть ли в собственности авто?": True,
            "Тип актива": "Недвижимость",
            "Иждивенцы": True,
        }
    )
    engine = DialogueV3Engine()

    first = engine.handle_turn("Хочу долги закрыть в первую очередь, уже тяжело платить.", state)
    assert first.route_session.selected_route == "DISCOVERY"
    assert first.route_session.next_slot == "total_debt"

    second = engine.handle_turn("Около 1,8 млн рублей, это вся сумма долгов.", first.state)
    assert second.state.fact_value("total_debt") == 1_800_000
    assert second.route_session.next_slot == "monthly_payments"

    third = engine.handle_turn("Примерно 75 тысяч в месяц.", second.state)
    assert third.state.fact_value("monthly_payments") == 75_000
    assert third.route_session.next_slot == "income_status"

    fourth = engine.handle_turn("Официальный доход, примерно 120 тысяч рублей на руки.", third.state)
    assert fourth.state.fact_value("official_income") == 120_000
    assert fourth.state.fact_value("income_status") == "stable"
    assert fourth.route_session.next_slot == "comfortable_payment"

    fifth = engine.handle_turn("Около 30 тысяч в месяц было бы намного комфортнее.", fourth.state)
    assert fifth.state.fact_value("comfortable_payment") == 30_000
    assert fifth.route_session.next_slot == "delinquency_context"

    sixth = engine.handle_turn("Да, просрочки уже есть, примерно пару месяцев.", fifth.state)
    assert sixth.state.fact_value("has_arrears") is True
    assert sixth.state.fact_value("arrears_months") == 2.0
    assert sixth.route_session.selected_route == "BFL_RD"
    assert sixth.route_session.terminal_action is None
    assert sixth.route_session.next_slot == "bfl_property_context"
    assert sixth.events == []

    seventh = engine.handle_turn(
        "Да, это моя единственная квартира в Самаре, собственник я, ипотеки, залога и арестов нет.",
        sixth.state,
    )
    assert seventh.state.fact_value("property_type") == "apartment"
    assert seventh.state.fact_value("property_region") == "Самара"
    assert seventh.frame.property_owner_known is True
    assert seventh.frame.property_encumbrance_known is True
    assert seventh.state.fact_value("is_only_housing") is True
    assert seventh.route_session.selected_route == "BFL_RD"
    assert seventh.route_session.selected_route not in {"MORTGAGE_MAIN", "MORTGAGE_AUX"}
    assert seventh.route_session.next_slot == "bfl_dependents_context"

    eighth = engine.handle_turn("На иждивении мама.", seventh.state)
    assert eighth.state.fact_value("dependent_relation") == "mother"
    assert eighth.route_session.next_slot == "bfl_vehicle_context"

    ninth = engine.handle_turn("Машина Volkswagen Polo, 2016 года.", eighth.state)
    assert ninth.state.fact_value("raw_car_name") == "Volkswagen Polo"
    assert ninth.state.fact_value("car_year") == 2016
    assert ninth.route_session.selected_route == "BFL_RD"
    assert ninth.route_session.selected_route != "PTS"
    assert ninth.route_session.next_slot == "previous_debt_procedure"

    tenth = engine.handle_turn("Раньше банкротства или реструктуризации не было.", ninth.state)
    assert tenth.state.fact_value("previous_debt_procedure") is False
    assert tenth.route_session.selected_route == "BFL_RD"
    assert tenth.route_session.phase == "READY_FOR_TERMINAL"
    assert tenth.route_session.terminal_action == "HANDOFF_BFL_SPECIALIST"
    assert tenth.actor_move.move_type == "recommendation_offer"
    assert tenth.events == []

    eleventh = engine.handle_turn("А какие вообще есть варианты — банкротство или реструктуризация?", tenth.state)
    eleventh_lowered = eleventh.text.lower()
    assert eleventh.route_session.selected_route == "BFL_RD"
    assert eleventh.actor_move.move_type == "recommendation_offer"
    assert eleventh.actor_move.pending_terminal_action == "HANDOFF_BFL_SPECIALIST"
    assert eleventh.events == []
    assert "не обязательно банкротство" in eleventh_lowered
    assert "реструктуризац" in eleventh_lowered
    assert "имущество нужно отдельно проверить" in eleventh_lowered
    assert "передать вас специалисту по долгам" in eleventh_lowered

    twelfth = engine.handle_turn("Да, передавайте.", eleventh.state)
    assert [event.action_id for event in twelfth.events] == ["HANDOFF_BFL_SPECIALIST"]
    assert twelfth.state.pending_terminal_action is None
    assert twelfth.state.pending_route is None


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
    assert result.actor_move.move_type == "recommendation_offer"
    assert result.actor_move.pending_terminal_action == "HANDOFF_BFL_SPECIALIST"
    assert result.events == []


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
