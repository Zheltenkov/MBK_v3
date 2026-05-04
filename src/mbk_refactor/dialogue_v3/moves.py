"""ActorMove planning without LLM ownership of business decisions."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from .case_frame import CaseFrame
from .route_session import RouteSession

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


def plan_actor_move(route_session: RouteSession, *, frame: CaseFrame) -> ActorMove:
    """Plan the next actor move from deterministic route/session state."""

    if route_session.selected_route == "FRAUD_CHECK":
        return ActorMove(
            move_type="security_action",
            selected_route=route_session.selected_route,
            phase=route_session.phase,
            terminal_action=route_session.terminal_action,
            action_scope="security_check",
            must_say=["do_not_share_codes"],
        )

    if route_session.selected_route == "REPEAT_VISIT":
        return ActorMove(
            move_type="repeat_action",
            selected_route=route_session.selected_route,
            phase=route_session.phase,
            terminal_action=route_session.terminal_action,
            action_scope="repeat_visit_restore",
        )

    if route_session.selected_route == "OTHER" or route_session.blockers:
        return ActorMove(
            move_type="no_solution_manual_review",
            selected_route=route_session.selected_route,
            phase=route_session.phase,
            terminal_action=route_session.terminal_action or "MANUAL_REVIEW",
            client_concern=_client_concern(frame),
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
            action_scope="route_terminal",
        )

    return ActorMove(
        move_type="no_solution_manual_review",
        selected_route=route_session.selected_route,
        phase=route_session.phase,
        terminal_action="MANUAL_REVIEW",
    )


def _client_concern(frame: CaseFrame) -> str | None:
    if frame.property_risk_concern:
        return "property_risk"
    if frame.vehicle_requires_retention or frame.vehicle_refuses_transfer:
        return "vehicle_retention"
    if frame.client_fears_bankruptcy:
        return "bankruptcy_fear"
    return None
