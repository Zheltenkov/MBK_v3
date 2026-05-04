"""Deterministic route selection for dialogue_v3."""

from __future__ import annotations

from .case_frame import CaseFrame
from .constants import (
    BFL_RD,
    BFL_RI,
    DISCOVERY,
    FRAUD_CHECK,
    MICRO,
    MORTGAGE_AUX,
    MORTGAGE_MAIN,
    OTHER,
    PTS,
    REPEAT_VISIT,
    UNSECURED,
)
from .state import DialogueV3State


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

    if _explicit_vehicle_intent(frame) and _pts_possible(frame, state):
        return PTS

    if _explicit_property_collateral_intent(frame) and not _mortgage_blocked(frame, state):
        return _mortgage_route(frame)

    if _severe_debt_pressure(frame):
        return BFL_RI

    if _restructuring_debt_pressure(frame):
        return BFL_RD

    early_route = _early_funnel_route(frame, state)
    if early_route:
        return early_route

    if _property_collateral_possible(frame, state):
        return _mortgage_route(frame)

    if _pts_possible(frame, state) and _has_non_form_vehicle_evidence(state):
        return PTS

    if _unsecured_possible(frame):
        return UNSECURED

    if _micro_possible(frame):
        return MICRO

    return OTHER


def _property_collateral_possible(frame: CaseFrame, state: DialogueV3State) -> bool:
    if _mortgage_blocked(frame, state):
        return False
    return bool(
        frame.property_type
        or frame.property_region
        or _fact_is_not_from_form(state, "has_property")
    )


def _mortgage_blocked(frame: CaseFrame, state: DialogueV3State) -> bool:
    return frame.property_refuses_collateral or "MORTGAGE" in state.rejected_routes


def _mortgage_route(frame: CaseFrame) -> str:
    if _is_main_property_region(frame.property_region):
        return MORTGAGE_MAIN
    return MORTGAGE_AUX


def _pts_possible(frame: CaseFrame, state: DialogueV3State) -> bool:
    if frame.vehicle_refuses_collateral or frame.vehicle_hard_blocker or PTS in state.rejected_routes:
        return False
    return bool(frame.has_car or frame.car_brand_model_known or frame.car_year)


def _early_funnel_route(frame: CaseFrame, state: DialogueV3State) -> str | None:
    """Keep early generic turns in a safe funnel instead of form-asset collateral intake."""

    if state.turn_index > 3 and _previous_selected_route(state) != DISCOVERY:
        return None
    if _explicit_vehicle_intent(frame) or _explicit_property_collateral_intent(frame):
        return None
    if not _general_funnel_intent(frame):
        return None

    return DISCOVERY


def _previous_selected_route(state: DialogueV3State) -> str | None:
    route = state.route
    return getattr(route, "selected_route", None) if route is not None else None


def _explicit_vehicle_intent(frame: CaseFrame) -> bool:
    return frame.explicit_pts_intent or frame.early_need_signal == "explicit_pts"


def _explicit_property_collateral_intent(frame: CaseFrame) -> bool:
    return frame.explicit_mortgage_intent or frame.early_need_signal == "explicit_mortgage"


def _general_funnel_intent(frame: CaseFrame) -> bool:
    if frame.has_current_loans and (
        frame.client_wants_to_pay
        or frame.client_fears_bankruptcy
        or frame.high_payment_load
        or frame.has_arrears
        or frame.total_debt is not None
        or frame.monthly_payments is not None
    ):
        return True
    if frame.early_need_signal in {
        "new_money",
        "debt_solution",
        "payment_reduction",
        "repair_or_purpose",
    }:
        return True
    if frame.need_type in {"new_money", "debt_solution", "payment_reduction"}:
        return True
    return False


def _fact_is_not_from_form(state: DialogueV3State, key: str) -> bool:
    fact = state.facts.get(key)
    return bool(fact and fact.source != "form" and fact.value not in (None, "", False))


def _has_non_form_vehicle_evidence(state: DialogueV3State) -> bool:
    return any(
        _fact_is_not_from_form(state, key)
        for key in ("has_car", "raw_car_name", "car_brand_model_known", "car_year")
    )


def _severe_debt_pressure(frame: CaseFrame) -> bool:
    arrears_severe = frame.arrears_months is not None and frame.arrears_months >= 2
    no_stable_income = frame.income_status in {"none", "unstable"}
    debt_pressure_marker = bool(frame.has_mfo or frame.collector_pressure)
    return bool(
        debt_pressure_marker
        and no_stable_income
        and (
            arrears_severe
            or frame.collector_pressure
            or (frame.has_mfo and frame.has_arrears)
            or (frame.high_payment_load and frame.has_arrears)
        )
    )


def _restructuring_debt_pressure(frame: CaseFrame) -> bool:
    if frame.client_refuses_debt_procedure:
        return False
    if _severe_debt_pressure(frame):
        return False
    debt_intent = (
        frame.need_type in {"debt_solution", "payment_reduction"}
        or frame.early_need_signal in {
            "debt_solution",
            "payment_reduction",
        }
        or frame.has_current_loans
        or frame.high_payment_load
        or frame.payment_gap_large
    )
    debt_numbers_known = frame.total_debt is not None and frame.monthly_payments is not None
    income_known = frame.income_status != "unknown" or frame.official_income is not None or frame.other_income is not None
    payment_resolution_signal = frame.comfortable_payment is not None or frame.client_wants_to_pay
    return bool(
        debt_intent
        and debt_numbers_known
        and income_known
        and payment_resolution_signal
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
