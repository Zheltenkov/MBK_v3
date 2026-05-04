from __future__ import annotations

from mbk_refactor.dialogue_v3.case_frame import build_case_frame
from mbk_refactor.dialogue_v3.constants import (
    ACTION_SCOPE_BY_ACTION_ID,
    AUTO_AUX,
    BFL_RD,
    BFL_RI,
    DISCOVERY,
    FRAUD_CHECK,
    HANDOFF_EXPERT,
    MICRO,
    MORTGAGE_AUX,
    MORTGAGE_MAIN,
    OTHER,
    PTS,
    REPEAT_HANDOFF,
    REPEAT_VISIT,
    SECURITY_FLOW,
    SELF_SERVE_LINKS_3,
    UNSECURED,
)
from mbk_refactor.dialogue_v3.intake_plans import INTAKE_PLANS
from mbk_refactor.dialogue_v3.moves import terminal_action_scope
from mbk_refactor.dialogue_v3.route_session import build_route_session
from mbk_refactor.dialogue_v3.state import DialogueV3State


def state_with_facts(facts: dict[str, object]) -> DialogueV3State:
    state = DialogueV3State(session_id="test")
    state.turn_index = 1
    state.merge_facts(facts)
    return state


def test_intake_plans_include_step_1_routes() -> None:
    assert set(INTAKE_PLANS) == {
        DISCOVERY,
        MORTGAGE_MAIN,
        MORTGAGE_AUX,
        PTS,
        AUTO_AUX,
        BFL_RD,
        BFL_RI,
        UNSECURED,
        MICRO,
        FRAUD_CHECK,
        REPEAT_VISIT,
        OTHER,
    }


def test_intake_actions_use_shared_action_scope_constants() -> None:
    for plan in INTAKE_PLANS.values():
        if plan.terminal_action:
            assert plan.terminal_action in ACTION_SCOPE_BY_ACTION_ID
            assert terminal_action_scope(plan.terminal_action) == ACTION_SCOPE_BY_ACTION_ID[plan.terminal_action]


def test_auto_aux_is_registered_but_reserved_unreachable() -> None:
    assert AUTO_AUX in INTAKE_PLANS
    assert INTAKE_PLANS[AUTO_AUX].terminal_action == SELF_SERVE_LINKS_3


def test_service_flows_bypass_primary_intake() -> None:
    for route, action in {FRAUD_CHECK: SECURITY_FLOW, REPEAT_VISIT: REPEAT_HANDOFF}.items():
        state = state_with_facts({})
        frame = build_case_frame(state)
        session = build_route_session(route, state=state, frame=frame)

        assert session.primary_slots == []
        assert session.phase == "TERMINAL"
        assert session.terminal_action == action


def test_discovery_is_non_product_collecting_phase() -> None:
    state = state_with_facts({"need_type": "new_money"})
    frame = build_case_frame(state)
    session = build_route_session(DISCOVERY, state=state, frame=frame)

    assert session.phase == "DISCOVERY"
    assert session.next_slot == "desired_amount_or_total_debt"
    assert session.terminal_action is None


def test_discovery_slots_are_dynamic_by_need_type() -> None:
    unknown_state = state_with_facts({"early_need_signal": "new_money"})
    debt_state = state_with_facts({"need_type": "debt_solution"})
    repair_state = state_with_facts({"early_need_signal": "repair_or_purpose"})

    unknown_session = build_route_session(DISCOVERY, state=unknown_state, frame=build_case_frame(unknown_state))
    debt_session = build_route_session(DISCOVERY, state=debt_state, frame=build_case_frame(debt_state))
    repair_session = build_route_session(DISCOVERY, state=repair_state, frame=build_case_frame(repair_state))

    assert unknown_session.primary_slots == ["need_type"]
    assert debt_session.primary_slots == [
        "total_debt",
        "monthly_payments",
        "income_status",
        "comfortable_payment",
        "delinquency_context",
    ]
    assert repair_session.primary_slots == ["desired_amount_or_total_debt", "income_status", "urgency"]


def test_terminal_action_is_absent_before_primary_slots_close() -> None:
    state = state_with_facts({"has_car": True})
    frame = build_case_frame(state)

    session = build_route_session(PTS, state=state, frame=frame)

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

    session = build_route_session(PTS, state=state, frame=frame)

    assert session.phase == "READY_FOR_TERMINAL"
    assert session.next_slot is None
    assert session.terminal_action == HANDOFF_EXPERT
