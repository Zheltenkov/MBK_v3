from __future__ import annotations

from mbk_refactor.dialogue_v3.case_frame import build_case_frame
from mbk_refactor.dialogue_v3.intake_plans import INTAKE_PLANS
from mbk_refactor.dialogue_v3.route_session import build_route_session
from mbk_refactor.dialogue_v3.state import DialogueV3State


def state_with_facts(facts: dict[str, object]) -> DialogueV3State:
    state = DialogueV3State(session_id="test")
    state.turn_index = 1
    state.merge_facts(facts)
    return state


def test_intake_plans_include_step_1_routes() -> None:
    assert set(INTAKE_PLANS) == {
        "MORTGAGE_MAIN",
        "MORTGAGE_AUX",
        "PTS",
        "AUTO_AUX",
        "BFL_RD",
        "BFL_RI",
        "UNSECURED",
        "MICRO",
        "FRAUD_CHECK",
        "REPEAT_VISIT",
        "OTHER",
    }


def test_service_flows_bypass_primary_intake() -> None:
    for route, action in {"FRAUD_CHECK": "SECURITY_FLOW", "REPEAT_VISIT": "REPEAT_HANDOFF"}.items():
        state = state_with_facts({})
        frame = build_case_frame(state)
        session = build_route_session(route, state=state, frame=frame)

        assert session.primary_slots == []
        assert session.phase == "TERMINAL"
        assert session.terminal_action == action


def test_terminal_action_is_absent_before_primary_slots_close() -> None:
    state = state_with_facts({"has_car": True})
    frame = build_case_frame(state)

    session = build_route_session("PTS", state=state, frame=frame)

    assert session.phase == "COLLECTING_PRIMARY_GATES"
    assert session.next_slot == "car_brand_model"
    assert session.terminal_action is None


def test_terminal_action_appears_after_primary_slots_close() -> None:
    state = state_with_facts(
        {
            "has_car": True,
            "raw_car_name": "Kia Rio",
            "car_year": 2019,
            "car_owner": "client",
            "car_in_pledge": False,
            "car_arrest_or_restriction": False,
        }
    )
    frame = build_case_frame(state)

    session = build_route_session("PTS", state=state, frame=frame)

    assert session.phase == "READY_FOR_TERMINAL"
    assert session.next_slot is None
    assert session.terminal_action == "HANDOFF_EXPERT"
