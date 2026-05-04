from __future__ import annotations

import app_v3

from mbk_refactor.dialogue_v3.engine import DialogueV3Engine


def started_multi_direction_state():
    state, _ = app_v3.start_chat_from_form(
        {
            "ФИО": "Виктор Семёнович",
            "Сумма": 645_467,
            "Есть текущие кредиты или займы?": True,
            "Есть ли в собственности авто?": True,
            "Тип актива": "Недвижимость",
        },
        session_id="multi-direction",
    )
    assert state.messages[-1].role == "assistant"
    assert "что для вас сейчас в первую очередь" in state.messages[-1].content.lower()
    assert state.turn_index == 0
    return state


def test_answer_to_opening_goal_question_does_not_start_property_type_intake() -> None:
    result = DialogueV3Engine().handle_turn(
        "Закрыть карты, и немного на ремонт.",
        started_multi_direction_state(),
    )

    assert result.route_session.next_slot != "property_type"
    assert result.route_session.selected_route == "DISCOVERY"
    assert result.route_session.phase == "DISCOVERY"
    assert result.route_session.next_slot in {
        "need_type",
        "total_debt",
        "monthly_payments",
        "urgency",
        "desired_amount_or_total_debt",
    }
    assert "квартира, дом или другой объект" not in result.text.lower()


def test_explicit_vehicle_retention_first_turn_selects_pts_before_property() -> None:
    result = DialogueV3Engine().handle_turn(
        "Машину отдавать не буду, она каждый день нужна",
        started_multi_direction_state(),
    )

    assert result.route_session.selected_route == "PTS"
    assert result.route_session.next_slot == "car_brand_model"
    assert result.frame.vehicle_requires_retention is True
    assert result.frame.vehicle_refuses_collateral is False


def test_explicit_mortgage_first_turn_can_start_property_intake() -> None:
    result = DialogueV3Engine().handle_turn(
        "Хочу рассмотреть под квартиру",
        started_multi_direction_state(),
    )

    assert result.route_session.selected_route in {"MORTGAGE_MAIN", "MORTGAGE_AUX"}
    assert result.route_session.next_slot == "property_type"
