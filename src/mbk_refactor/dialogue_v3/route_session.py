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
    warnings: list[str] = field(default_factory=list)
    risk_factors: list[str] = field(default_factory=list)
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
    warnings = _collect_warnings(selected_route, frame)
    risk_factors = _collect_risk_factors(selected_route, frame)

    if blockers:
        return RouteSession(
            selected_route=selected_route,
            phase="BLOCKED",
            primary_slots=primary_slots,
            closed_primary_slots=resolution.closed_primary_slots,
            missing_primary_slots=resolution.missing_primary_slots,
            next_slot=None,
            blockers=blockers,
            warnings=warnings,
            risk_factors=risk_factors,
            terminal_action=None,
            reason_codes=blockers,
        )

    if not primary_slots:
        return RouteSession(
            selected_route=selected_route,
            phase="TERMINAL",
            primary_slots=[],
            warnings=warnings,
            risk_factors=risk_factors,
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
            warnings=warnings,
            risk_factors=risk_factors,
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
            warnings=warnings,
            risk_factors=risk_factors,
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
        warnings=warnings,
        risk_factors=risk_factors,
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
    if selected_route in {PTS, AUTO_AUX}:
        blockers.extend(_pts_route_blockers(frame))
    if selected_route in {MORTGAGE_MAIN, MORTGAGE_AUX}:
        blockers.extend(_mortgage_route_blockers(frame))
    return blockers


def _collect_warnings(selected_route: str, frame: CaseFrame) -> list[str]:
    if selected_route in {PTS, AUTO_AUX}:
        return _pts_route_warnings(frame)
    if selected_route in {MORTGAGE_MAIN, MORTGAGE_AUX}:
        return _mortgage_route_warnings(frame)
    return []


def _collect_risk_factors(selected_route: str, frame: CaseFrame) -> list[str]:
    if selected_route in {PTS, AUTO_AUX}:
        return _pts_route_risk_factors(frame)
    if selected_route in {MORTGAGE_MAIN, MORTGAGE_AUX}:
        return _mortgage_route_risk_factors(frame)
    return []


def _pts_route_blockers(frame: CaseFrame) -> list[str]:
    blockers: list[str] = []
    if frame.vehicle_no_car_red_flag:
        blockers.append("vehicle_no_car_red_flag")
    if frame.car_arrest_red_flag:
        blockers.append("car_arrest_red_flag")
    if frame.car_restriction_red_flag:
        blockers.append("car_restriction_red_flag")
    return blockers


def _pts_route_warnings(frame: CaseFrame) -> list[str]:
    warnings: list[str] = []
    if frame.car_old_year:
        warnings.append("car_old_year")
    if frame.third_party_car_owner:
        warnings.append("third_party_car_owner")
    if frame.car_loan_red_flag:
        warnings.append("car_loan_red_flag")
    if frame.car_pledge_red_flag:
        warnings.append("car_pledge_red_flag")
    return warnings


def _pts_route_risk_factors(frame: CaseFrame) -> list[str]:
    risk_factors: list[str] = []
    if frame.vehicle_requires_retention or frame.vehicle_refuses_transfer:
        risk_factors.append("vehicle_retention_required")
    return risk_factors


def _mortgage_route_blockers(frame: CaseFrame) -> list[str]:
    blockers: list[str] = []
    if frame.property_arrest_red_flag:
        blockers.append("property_arrest_red_flag")
    return blockers


def _mortgage_route_warnings(frame: CaseFrame) -> list[str]:
    warnings: list[str] = []
    if frame.unsupported_property_region:
        warnings.append("unsupported_property_region")
    if frame.third_party_property_owner:
        warnings.append("third_party_property_owner")
    if frame.property_mortgage:
        warnings.append("property_mortgage")
    if frame.property_pledge_red_flag:
        warnings.append("property_pledge_red_flag")
    if frame.municipal_housing_red_flag:
        warnings.append("municipal_housing_red_flag")
    if frame.property_share_red_flag:
        warnings.append("property_share_red_flag")
    if frame.property_room_red_flag:
        warnings.append("property_room_red_flag")
    return warnings


def _mortgage_route_risk_factors(frame: CaseFrame) -> list[str]:
    risk_factors: list[str] = []
    if frame.property_risk_concern:
        risk_factors.append("property_risk_concern")
    return risk_factors
