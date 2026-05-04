"""Deterministic route selection for dialogue_v3."""

from __future__ import annotations

from .case_frame import CaseFrame
from .state import DialogueV3State

MORTGAGE_MAIN = "MORTGAGE_MAIN"
MORTGAGE_AUX = "MORTGAGE_AUX"
PTS = "PTS"
AUTO_AUX = "AUTO_AUX"
UNSECURED = "UNSECURED"
MICRO = "MICRO"
BFL_RI = "BFL_RI"
BFL_RD = "BFL_RD"
OTHER = "OTHER"
FRAUD_CHECK = "FRAUD_CHECK"
REPEAT_VISIT = "REPEAT_VISIT"

ALIASES = {
    "AUTO_COLLATERAL_AUX": AUTO_AUX,
    AUTO_AUX: AUTO_AUX,
}


def select_route(frame: CaseFrame, state: DialogueV3State) -> str:
    """Return exactly one route; LLMs and planners do not participate."""

    # Service overrides bypass ordinary product intake.
    if frame.service_intent == "fraud_check":
        return FRAUD_CHECK
    if frame.service_intent == "repeat_visit":
        return REPEAT_VISIT

    # OTHER is only a terminal fallback, never a scored candidate.
    if _hard_conflicting_constraints(frame, state):
        return OTHER

    if _property_collateral_possible(frame, state):
        if _is_main_property_region(frame.property_region):
            return MORTGAGE_MAIN
        return MORTGAGE_AUX

    if _pts_possible(frame, state):
        return PTS

    if _severe_debt_pressure(frame):
        return BFL_RI

    if _restructuring_debt_pressure(frame):
        return BFL_RD

    if _unsecured_possible(frame):
        return UNSECURED

    if _micro_possible(frame):
        return MICRO

    return OTHER


def normalize_route(route: str) -> str:
    """Normalize legacy ids at the v3 boundary."""

    return ALIASES.get(route, route)


def _property_collateral_possible(frame: CaseFrame, state: DialogueV3State) -> bool:
    if frame.property_refuses_collateral or "MORTGAGE" in state.rejected_routes:
        return False
    return bool(frame.has_property or frame.property_type or frame.property_region)


def _pts_possible(frame: CaseFrame, state: DialogueV3State) -> bool:
    if frame.vehicle_refuses_collateral or frame.vehicle_hard_blocker or PTS in state.rejected_routes:
        return False
    return bool(frame.has_car or frame.car_brand_model_known or frame.car_year)


def _severe_debt_pressure(frame: CaseFrame) -> bool:
    arrears_severe = frame.arrears_months is not None and frame.arrears_months >= 2
    no_stable_income = frame.income_status in {"none", "unstable"}
    return bool(
        (frame.has_mfo and (frame.collector_pressure or frame.has_arrears))
        or (frame.collector_pressure and frame.has_arrears)
        or (arrears_severe and no_stable_income)
    )


def _restructuring_debt_pressure(frame: CaseFrame) -> bool:
    if frame.client_refuses_debt_procedure:
        return False
    return bool(
        frame.client_wants_to_pay
        or frame.high_payment_load
        or frame.payment_gap_large
        or (
            frame.has_current_loans
            and frame.total_debt is not None
            and frame.monthly_payments is not None
        )
    )


def _unsecured_possible(frame: CaseFrame) -> bool:
    if frame.has_arrears or frame.collector_pressure or frame.has_mfo:
        return False
    return bool(
        frame.desired_amount is not None
        and frame.income_status in {"stable", "no_official_income", "unknown"}
    )


def _micro_possible(frame: CaseFrame) -> bool:
    if frame.has_arrears or frame.collector_pressure:
        return False
    return bool(frame.desired_amount is not None and frame.desired_amount <= 100_000)


def _hard_conflicting_constraints(frame: CaseFrame, state: DialogueV3State) -> bool:
    product_rejections = {"MORTGAGE", PTS, BFL_RD, BFL_RI, UNSECURED, MICRO}
    if product_rejections.issubset(state.rejected_routes):
        return True
    if frame.client_refuses_debt_procedure and frame.has_current_loans and not frame.has_property and not frame.has_car:
        return True
    return False


def _is_main_property_region(region: str | None) -> bool:
    if not region:
        return False
    normalized = region.lower().replace("ё", "е")
    return any(marker in normalized for marker in ("москва", "москов", "санкт", "спб", "петербург"))
