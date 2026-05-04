"""ActorMove planning without LLM ownership of business decisions."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from .case_frame import CaseFrame
from .route_session import RouteSession
from .state import DialogueV3State

MoveType = Literal[
    "ask_slot",
    "answer_then_ask_slot",
    "handle_offtopic_then_ask",
    "handle_objection_then_ask",
    "terminal_action",
    "security_action",
    "repeat_action",
    "no_solution_manual_review",
]


@dataclass
class ActorMove:
    move_type: MoveType
    selected_route: str
    phase: str
    next_slot: str | None = None
    terminal_action: str | None = None
    direct_answer_topic: str | None = None
    client_concern: str | None = None
    off_topic_kind: str | None = None
    known_facts: dict[str, Any] = field(default_factory=dict)
    must_say: list[str] = field(default_factory=list)
    must_not_say: list[str] = field(default_factory=list)
    question_goal: str | None = None
    action_scope: str | None = None
    style_profile: str = "calm_manager"


ACTION_SCOPE_BY_TERMINAL_ACTION = {
    "HANDOFF_EXPERT": "handoff_expert",
    "HANDOFF_BFL_SPECIALIST": "bfl_handoff",
    "MANUAL_REVIEW": "manual_review",
    "SECURITY_FLOW": "security_check",
    "REPEAT_HANDOFF": "repeat_handoff",
    "SELF_SERVE_LINKS_3": "self_serve_links",
    "SELF_SERVE_LINKS_7": "self_serve_links",
}


def plan_actor_move(
    route_session: RouteSession,
    *,
    frame: CaseFrame,
    state: DialogueV3State | None = None,
) -> ActorMove:
    """Plan the next actor move from deterministic route/session state."""

    if route_session.selected_route == "FRAUD_CHECK":
        return ActorMove(
            move_type="security_action",
            selected_route=route_session.selected_route,
            phase=route_session.phase,
            terminal_action=route_session.terminal_action,
            action_scope=terminal_action_scope(route_session.terminal_action),
            known_facts=build_terminal_known_facts(route_session.selected_route, state),
            must_say=["do_not_share_codes"],
        )

    if route_session.selected_route == "REPEAT_VISIT":
        return ActorMove(
            move_type="repeat_action",
            selected_route=route_session.selected_route,
            phase=route_session.phase,
            terminal_action=route_session.terminal_action,
            action_scope=terminal_action_scope(route_session.terminal_action),
            known_facts=build_terminal_known_facts(route_session.selected_route, state),
        )

    if route_session.selected_route == "OTHER" or route_session.blockers:
        return ActorMove(
            move_type="no_solution_manual_review",
            selected_route=route_session.selected_route,
            phase=route_session.phase,
            terminal_action=route_session.terminal_action or "MANUAL_REVIEW",
            client_concern=_client_concern(frame),
            known_facts=_with_session_reasons(
                build_terminal_known_facts(route_session.selected_route, state),
                route_session,
            ),
            action_scope=terminal_action_scope(route_session.terminal_action or "MANUAL_REVIEW"),
        )

    if frame.off_topic_kind and route_session.next_slot:
        return ActorMove(
            move_type="handle_offtopic_then_ask",
            selected_route=route_session.selected_route,
            phase=route_session.phase,
            next_slot=route_session.next_slot,
            off_topic_kind=frame.off_topic_kind,
            question_goal=route_session.next_slot,
        )

    concern = _client_concern(frame)
    if concern and route_session.next_slot:
        return ActorMove(
            move_type="handle_objection_then_ask",
            selected_route=route_session.selected_route,
            phase=route_session.phase,
            next_slot=route_session.next_slot,
            client_concern=concern,
            question_goal=route_session.next_slot,
            must_not_say=["no_risk_promises"],
        )

    if frame.direct_question and route_session.next_slot:
        return ActorMove(
            move_type="answer_then_ask_slot",
            selected_route=route_session.selected_route,
            phase=route_session.phase,
            next_slot=route_session.next_slot,
            direct_answer_topic="customer_question",
            question_goal=route_session.next_slot,
        )

    if route_session.next_slot:
        return ActorMove(
            move_type="ask_slot",
            selected_route=route_session.selected_route,
            phase=route_session.phase,
            next_slot=route_session.next_slot,
            question_goal=route_session.next_slot,
        )

    if route_session.terminal_action:
        return ActorMove(
            move_type="terminal_action",
            selected_route=route_session.selected_route,
            phase=route_session.phase,
            terminal_action=route_session.terminal_action,
            known_facts=build_terminal_known_facts(route_session.selected_route, state),
            action_scope=terminal_action_scope(route_session.terminal_action),
        )

    return ActorMove(
        move_type="no_solution_manual_review",
        selected_route=route_session.selected_route,
        phase=route_session.phase,
        terminal_action="MANUAL_REVIEW",
        action_scope=terminal_action_scope("MANUAL_REVIEW"),
    )


def _client_concern(frame: CaseFrame) -> str | None:
    if frame.property_risk_concern:
        return "property_risk"
    if frame.vehicle_requires_retention or frame.vehicle_refuses_transfer:
        return "vehicle_retention"
    if frame.client_fears_bankruptcy:
        return "bankruptcy_fear"
    return None


def terminal_action_scope(terminal_action: str | None) -> str | None:
    """Describe an already selected terminal action for writer wording only."""

    if not terminal_action:
        return None
    return ACTION_SCOPE_BY_TERMINAL_ACTION.get(terminal_action)


def build_terminal_known_facts(
    route: str,
    state: DialogueV3State | None,
) -> dict[str, Any]:
    """Build compact terminal writer facts without exposing raw mutable state."""

    if state is None:
        return {}

    if route in {"PTS", "AUTO_AUX"}:
        return _known(
            state,
            {
                "raw_car_name": "car",
                "car_brand": "car_brand",
                "car_model": "car_model",
                "car_year": "car_year",
                "car_owner": "car_owner",
                "car_in_pledge": "car_in_pledge",
                "car_arrest_or_restriction": "car_arrest_or_restriction",
            },
        )
    if route in {"MORTGAGE_MAIN", "MORTGAGE_AUX"}:
        return _known(
            state,
            {
                "property_type": "property_type",
                "property_region": "property_region",
                "property_owner": "property_owner_or_ownership",
                "property_owner_known": "property_owner_known",
                "property_encumbrance": "property_encumbrance_basic",
                "property_encumbrance_type": "property_encumbrance_type",
            },
        )
    if route in {"BFL_RD", "BFL_RI"}:
        return _known(
            state,
            {
                "total_debt": "total_debt",
                "monthly_payments": "monthly_payments",
                "income_status": "income_status",
                "comfortable_payment": "comfortable_payment",
                "has_arrears": "has_arrears",
                "arrears_months": "delinquency_context",
                "loan_types": "loan_types",
                "client_wants_to_pay": "client_wants_to_pay",
            },
        )
    if route in {"UNSECURED", "MICRO"}:
        return _known(
            state,
            {
                "desired_amount": "desired_amount_or_total_debt",
                "total_debt": "desired_amount_or_total_debt",
                "income_status": "income_status",
                "monthly_payments": "monthly_payments",
                "has_arrears": "delinquency_context",
                "arrears_months": "delinquency_context",
                "urgency": "urgency",
            },
        )
    if route == "FRAUD_CHECK":
        return _known(state, {"service_signal": "service_reason"})
    if route == "REPEAT_VISIT":
        return _known(state, {"service_signal": "repeat_reason"})
    return {}


def _known(state: DialogueV3State, mapping: dict[str, str]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for fact_key, output_key in mapping.items():
        value = state.fact_value(fact_key)
        if value is not None:
            result[output_key] = value
    return result


def _with_session_reasons(facts: dict[str, Any], route_session: RouteSession) -> dict[str, Any]:
    result = dict(facts)
    if route_session.blockers:
        result["blockers"] = list(route_session.blockers)
    if route_session.reason_codes:
        result["reason_codes"] = list(route_session.reason_codes)
    return result
