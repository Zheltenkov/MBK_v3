"""RouteSession builder: one selected route, one next business step."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from .case_frame import CaseFrame
from .constants import AUTO_AUX, DISCOVERY, MORTGAGE_AUX, MORTGAGE_MAIN, PTS
from .intake_plans import get_intake_plan, primary_slots_for_route
from .slot_resolver import resolve_primary_slots
from .state import DialogueV3State

DISCOVERY_COLLATERAL_BRIDGE_SLOT = "collateral_preference"

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
    primary_slots = primary_slots_for_route(selected_route, frame)
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
        bridge_slot = None if resolution.next_slot else _discovery_bridge_slot(frame)
        return RouteSession(
            selected_route=selected_route,
            phase="DISCOVERY",
            primary_slots=primary_slots,
            closed_primary_slots=resolution.closed_primary_slots,
            missing_primary_slots=resolution.missing_primary_slots,
            next_slot=resolution.next_slot or bridge_slot,
            terminal_action=None,
            reason_codes=_discovery_reason_codes(resolution.next_slot, bridge_slot),
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


def _discovery_reason_codes(next_slot: str | None, bridge_slot: str | None) -> list[str]:
    if next_slot:
        return ["discovery_collect"]
    if bridge_slot:
        return ["discovery_bridge"]
    return ["discovery_complete"]


def _discovery_bridge_slot(frame: CaseFrame) -> str | None:
    """Offer a neutral bridge after clean debt discovery, without selecting PTS."""

    if frame.need_type != "debt_solution":
        return None
    if frame.has_car is not True:
        return None
    if frame.explicit_pts_intent or frame.explicit_mortgage_intent:
        return None
    if frame.vehicle_refuses_collateral or frame.vehicle_hard_blocker:
        return None
    if frame.has_arrears or frame.has_mfo or frame.collector_pressure:
        return None
    if frame.high_payment_load or frame.payment_gap_large:
        return None
    if frame.client_wants_to_pay or frame.client_fears_bankruptcy:
        return None
    if frame.total_debt is None or frame.monthly_payments is None:
        return None
    income_known = (
        frame.income_status != "unknown"
        or frame.official_income is not None
        or frame.other_income is not None
    )
    if not income_known:
        return None
    return DISCOVERY_COLLATERAL_BRIDGE_SLOT
