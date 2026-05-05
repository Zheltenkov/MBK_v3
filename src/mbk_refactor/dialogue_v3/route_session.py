"""RouteSession builder: one selected route, one next business step."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from .case_frame import CaseFrame
from .constants import AUTO_AUX, DISCOVERY, MORTGAGE_AUX, MORTGAGE_MAIN, PTS
from .intake_plans import get_intake_plan, primary_slots_for_route
from .slot_resolver import resolve_primary_slots
from .state import DialogueV3State

RoutePhase = Literal[
    "DISCOVERY",
    "COLLECTING_PRIMARY_GATES",
    "READY_FOR_TERMINAL",
    "BLOCKED",
    "TERMINAL",
]


@dataclass
class RouteSession:
    selected_route: str
    phase: RoutePhase
    locked: bool = False
    lock_reason: str | None = None
    primary_slots: list[str] = field(default_factory=list)
    closed_primary_slots: list[str] = field(default_factory=list)
    missing_primary_slots: list[str] = field(default_factory=list)
    next_slot: str | None = None
    blockers: list[str] = field(default_factory=list)
    terminal_action: str | None = None
    reason_codes: list[str] = field(default_factory=list)


def build_route_session(
    selected_route: str,
    *,
    state: DialogueV3State,
    frame: CaseFrame,
) -> RouteSession:
    """Build the authoritative per-turn route session."""

    plan = get_intake_plan(selected_route)
    primary_slots = primary_slots_for_route(selected_route, frame, state=state)
    resolution = resolve_primary_slots(primary_slots, state=state, frame=frame)
    blockers = _collect_blockers(selected_route, frame)

    if blockers:
        return RouteSession(
            selected_route=selected_route,
            phase="BLOCKED",
            primary_slots=primary_slots,
            closed_primary_slots=resolution.closed_primary_slots,
            missing_primary_slots=resolution.missing_primary_slots,
            next_slot=None,
            blockers=blockers,
            terminal_action=None,
            reason_codes=blockers,
        )

    if not primary_slots:
        return RouteSession(
            selected_route=selected_route,
            phase="TERMINAL",
            primary_slots=[],
            terminal_action=plan.terminal_action,
            reason_codes=["service_or_fallback_terminal"],
        )

    if selected_route == DISCOVERY:
        return RouteSession(
            selected_route=selected_route,
            phase="DISCOVERY",
            primary_slots=primary_slots,
            closed_primary_slots=resolution.closed_primary_slots,
            missing_primary_slots=resolution.missing_primary_slots,
            next_slot=resolution.next_slot,
            terminal_action=None,
            reason_codes=["discovery_collect"] if resolution.next_slot else ["discovery_complete"],
        )

    if resolution.missing_primary_slots:
        return RouteSession(
            selected_route=selected_route,
            phase="COLLECTING_PRIMARY_GATES",
            primary_slots=primary_slots,
            closed_primary_slots=resolution.closed_primary_slots,
            missing_primary_slots=resolution.missing_primary_slots,
            next_slot=resolution.next_slot,
            terminal_action=None,
            reason_codes=["collect_primary_slots"],
        )

    return RouteSession(
        selected_route=selected_route,
        phase="READY_FOR_TERMINAL",
        primary_slots=primary_slots,
        closed_primary_slots=resolution.closed_primary_slots,
        missing_primary_slots=[],
        next_slot=None,
        terminal_action=plan.terminal_action if plan.allow_terminal_after_primary else None,
        reason_codes=["primary_slots_closed"],
    )


def _collect_blockers(selected_route: str, frame: CaseFrame) -> list[str]:
    blockers: list[str] = []
    if selected_route in {MORTGAGE_MAIN, MORTGAGE_AUX} and frame.property_refuses_collateral:
        blockers.append("property_collateral_refused")
    if selected_route in {PTS, AUTO_AUX} and (
        frame.vehicle_refuses_collateral or frame.vehicle_hard_blocker
    ):
        blockers.append("vehicle_collateral_refused")
    return blockers
