from __future__ import annotations

from pathlib import Path

from mbk_refactor.dialogue_v3.case_frame import build_case_frame
from mbk_refactor.dialogue_v3.constants import (
    AUTO_AUX,
    BFL_RD,
    BFL_RI,
    DISCOVERY,
    FRAUD_CHECK,
    MORTGAGE_AUX,
    MORTGAGE_MAIN,
    PTS,
    REPEAT_VISIT,
)
from mbk_refactor.dialogue_v3.route_session import build_route_session
from mbk_refactor.dialogue_v3.routes import select_route
from mbk_refactor.dialogue_v3.state import DialogueV3State


def state_with_facts(facts: dict[str, object]) -> DialogueV3State:
    state = DialogueV3State(session_id="test")
    state.turn_index = 1
    state.merge_facts(facts)
    return state


def test_select_route_returns_exactly_one_route() -> None:
    state = state_with_facts({"has_car": True, "explicit_pts_intent": True})
    route = select_route(build_case_frame(state), state)

    assert isinstance(route, str)
    assert route == PTS


def test_routes_module_does_not_match_raw_product_phrases() -> None:
    source = Path("src/mbk_refactor/dialogue_v3/routes.py").read_text(encoding="utf-8").lower()

    assert "_last_user_text" not in source
    for phrase in (
        "под птс",
        "под авто",
        "машину отдавать",
        "под квартиру",
        "под дом",
        "закрыть карты",
        "закрыть долги",
        "нужны деньги",
    ):
        assert phrase not in source


def test_generic_money_request_selects_discovery_not_product_route() -> None:
    state = state_with_facts(
        {
            "has_current_loans": True,
            "has_car": True,
            "has_property": True,
            "need_type": "new_money",
            "early_need_signal": "new_money",
        }
    )
    frame = build_case_frame(state)
    route = select_route(frame, state)
    session = build_route_session(route, state=state, frame=frame)

    assert route == DISCOVERY
    assert session.phase == "DISCOVERY"
    assert session.next_slot == "desired_amount_or_total_debt"
    assert session.terminal_action is None


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

    assert route == MORTGAGE_MAIN
    assert session.next_slot == "property_type"
    assert session.terminal_action is None


def test_pts_retention_keeps_pts_route() -> None:
    state = state_with_facts(
        {
            "has_car": True,
            "explicit_pts_intent": True,
            "vehicle_requires_retention": True,
            "vehicle_refuses_collateral": False,
        }
    )
    frame = build_case_frame(state)

    assert select_route(frame, state) == PTS
    assert frame.vehicle_refuses_collateral is False


def test_auto_aux_registered_but_not_selected_by_current_selector() -> None:
    state = state_with_facts(
        {
            "has_car": True,
            "explicit_pts_intent": True,
            "vehicle_refuses_collateral": False,
        }
    )

    route = select_route(build_case_frame(state), state)

    assert route == PTS
    assert route != AUTO_AUX


def test_property_fear_keeps_mortgage_route_possible() -> None:
    state = state_with_facts(
        {
            "has_property": True,
            "property_type": "apartment",
            "property_risk_concern": True,
            "property_refuses_collateral": False,
        }
    )
    frame = build_case_frame(state)

    assert select_route(frame, state) == MORTGAGE_AUX
    assert frame.property_refuses_collateral is False


def test_explicit_property_refusal_blocks_mortgage() -> None:
    state = state_with_facts(
        {
            "property_refuses_collateral": True,
            "explicit_mortgage_intent": True,
        }
    )
    frame = build_case_frame(state)

    assert frame.property_refuses_collateral is True
    assert select_route(frame, state) != MORTGAGE_MAIN


def test_fraud_sms_code_immediately_selects_fraud_check() -> None:
    state = state_with_facts({"service_signal": "fraud_check"})
    frame = build_case_frame(state)

    assert select_route(frame, state) == FRAUD_CHECK


def test_repeat_visit_immediately_selects_repeat_visit() -> None:
    state = state_with_facts({"service_signal": "repeat_visit"})
    frame = build_case_frame(state)

    assert select_route(frame, state) == REPEAT_VISIT


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

    assert select_route(build_case_frame(state), state) == BFL_RD


def test_mfo_collectors_and_arrears_selects_bfl_ri() -> None:
    state = state_with_facts(
        {
            "has_current_loans": True,
            "has_mfo": True,
            "has_arrears": True,
            "arrears_months": 1.0,
            "collector_pressure": True,
            "income_status": "unstable",
        }
    )

    assert select_route(build_case_frame(state), state) == BFL_RI


def test_mfo_severe_arrears_selects_bfl_ri() -> None:
    state = state_with_facts(
        {
            "has_current_loans": True,
            "has_mfo": True,
            "has_arrears": True,
            "arrears_months": 2.0,
            "collector_pressure": False,
            "income_status": "unstable",
        }
    )

    assert select_route(build_case_frame(state), state) == BFL_RI


def test_no_stable_income_and_severe_arrears_selects_bfl_ri() -> None:
    state = state_with_facts(
        {
            "has_current_loans": True,
            "collector_pressure": True,
            "has_arrears": True,
            "arrears_months": 3.0,
            "income_status": "unstable",
        }
    )

    assert select_route(build_case_frame(state), state) == BFL_RI
