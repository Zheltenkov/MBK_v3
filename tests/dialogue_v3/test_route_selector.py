from __future__ import annotations

from mbk_refactor.dialogue_v3.case_frame import build_case_frame
from mbk_refactor.dialogue_v3.facts import extract_turn
from mbk_refactor.dialogue_v3.route_session import build_route_session
from mbk_refactor.dialogue_v3.routes import select_route
from mbk_refactor.dialogue_v3.state import DialogueV3State


def state_from_messages(messages: list[str]) -> DialogueV3State:
    state = DialogueV3State(session_id="test")
    for message in messages:
        state.turn_index += 1
        state.add_user_message(message)
        state.merge_extracted_turn(extract_turn(message, turn_index=state.turn_index))
    return state


def state_with_facts(facts: dict[str, object]) -> DialogueV3State:
    state = DialogueV3State(session_id="test")
    state.turn_index = 1
    state.merge_facts(facts)
    return state


def test_select_route_returns_exactly_one_route() -> None:
    state = state_from_messages(["Нужны деньги, авто есть"])
    route = select_route(build_case_frame(state), state)

    assert isinstance(route, str)
    assert route == "PTS"


def test_other_not_selected_when_mortgage_slot_askable() -> None:
    state = state_with_facts(
        {
            "desired_amount": 2_800_000,
            "has_property": True,
            "property_region": "Москва",
        }
    )
    frame = build_case_frame(state)

    route = select_route(frame, state)
    session = build_route_session(route, state=state, frame=frame)

    assert route == "MORTGAGE_MAIN"
    assert session.next_slot == "property_type"
    assert session.terminal_action is None


def test_pts_retention_keeps_pts_route() -> None:
    state = state_from_messages(
        [
            "Нужны деньги, авто есть",
            "Машину отдавать не буду, она для работы",
        ]
    )
    frame = build_case_frame(state)

    assert select_route(frame, state) == "PTS"
    assert frame.vehicle_refuses_collateral is False


def test_property_fear_keeps_mortgage_route_possible() -> None:
    state = state_from_messages(["Квартира есть, но потерять ее боюсь"])
    frame = build_case_frame(state)

    assert select_route(frame, state) == "MORTGAGE_AUX"
    assert frame.property_refuses_collateral is False


def test_explicit_property_refusal_blocks_mortgage() -> None:
    state = state_from_messages(["Квартиру не трогаем, залог недвижимости не рассматриваю"])
    frame = build_case_frame(state)

    assert frame.property_refuses_collateral is True
    assert select_route(frame, state) != "MORTGAGE_MAIN"


def test_fraud_sms_code_immediately_selects_fraud_check() -> None:
    state = state_from_messages(["Мне позвонили от вашего имени и попросили код из СМС."])
    frame = build_case_frame(state)

    assert select_route(frame, state) == "FRAUD_CHECK"


def test_repeat_visit_immediately_selects_repeat_visit() -> None:
    state = state_from_messages(["Я уже переходил в чат, но мне не ответили."])
    frame = build_case_frame(state)

    assert select_route(frame, state) == "REPEAT_VISIT"
