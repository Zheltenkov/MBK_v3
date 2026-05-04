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


def test_stable_income_short_arrears_and_wants_to_pay_selects_bfl_rd() -> None:
    state = state_with_facts(
        {
            "has_current_loans": True,
            "has_mfo": True,
            "total_debt": 1_700_000,
            "monthly_payments": 78_000,
            "official_income": 125_000,
            "income_status": "stable",
            "comfortable_payment": 35_000,
            "has_arrears": True,
            "arrears_months": 1.0,
            "collector_pressure": False,
            "client_wants_to_pay": True,
            "high_payment_load": True,
            "payment_gap_large": True,
        }
    )

    assert select_route(build_case_frame(state), state) == "BFL_RD"


def test_mfo_collectors_and_arrears_selects_bfl_ri() -> None:
    state = state_with_facts(
        {
            "has_current_loans": True,
            "has_mfo": True,
            "has_arrears": True,
            "arrears_months": 1.0,
            "collector_pressure": True,
            "income_status": "stable",
        }
    )

    assert select_route(build_case_frame(state), state) == "BFL_RI"


def test_mfo_severe_arrears_selects_bfl_ri() -> None:
    state = state_with_facts(
        {
            "has_current_loans": True,
            "has_mfo": True,
            "has_arrears": True,
            "arrears_months": 2.0,
            "collector_pressure": False,
            "income_status": "stable",
        }
    )

    assert select_route(build_case_frame(state), state) == "BFL_RI"


def test_no_stable_income_and_severe_arrears_selects_bfl_ri() -> None:
    state = state_with_facts(
        {
            "has_current_loans": True,
            "has_arrears": True,
            "arrears_months": 3.0,
            "income_status": "unstable",
        }
    )

    assert select_route(build_case_frame(state), state) == "BFL_RI"
