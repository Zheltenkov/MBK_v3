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

    assert result.route_session.next_slot in {
        "need_type",
        "total_debt",
        "monthly_payments",
        "desired_amount_or_total_debt",
        "urgency",
    }
    assert result.route_session.next_slot not in {"property_type", "car_brand_model", "car_year"}
    assert "квартира, дом или другой объект" not in result.text.lower()
    assert "какая у вас машина" not in result.text.lower()


def test_cards_and_repair_does_not_trigger_mortgage_from_form_asset() -> None:
    result = run_turns(
        start_state(multi_asset_form()),
        ["Хочу закрыть карты и немного оставить на ремонт"],
    )

    assert result.route_session.selected_route != "MORTGAGE_AUX"
    assert result.route_session.next_slot in {
        "need_type",
        "total_debt",
        "monthly_payments",
        "desired_amount_or_total_debt",
    }
    assert result.route_session.next_slot != "property_type"
    assert result.route_session.next_slot != "car_brand_model"


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


def test_fraud_overrides_funnel_and_product_intake() -> None:
    result = run_turns(
        start_state({"Сумма": 600_000, "Тип актива": "Недвижимость"}),
        ["Мне позвонили от вашего имени и попросили код из СМС"],
    )

    assert result.route_session.selected_route == "FRAUD_CHECK"
    assert result.route_session.terminal_action == "SECURITY_FLOW"
    assert result.route_session.next_slot is None
    assert [event.action_id for event in result.events] == ["SECURITY_FLOW"]
