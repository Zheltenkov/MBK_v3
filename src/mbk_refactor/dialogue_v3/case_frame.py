"""Compact case frame used by routing and move planning."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from .state import DialogueV3State


@dataclass
class CaseFrame:
    service_intent: Literal["normal", "fraud_check", "repeat_visit"] = "normal"
    need_type: Literal["new_money", "payment_reduction", "debt_solution", "security", "unknown"] = "unknown"
    early_need_signal: Literal[
        "unknown",
        "new_money",
        "debt_solution",
        "payment_reduction",
        "repair_or_purpose",
        "explicit_pts",
        "explicit_mortgage",
        "security",
        "repeat",
    ] = "unknown"
    explicit_pts_intent: bool = False
    explicit_mortgage_intent: bool = False

    desired_amount: int | None = None
    total_debt: int | None = None
    monthly_payments: int | None = None
    comfortable_payment: int | None = None

    has_property: bool | None = None
    property_region: str | None = None
    property_type: str | None = None
    property_owner_known: bool = False
    property_encumbrance_known: bool = False
    property_refuses_collateral: bool = False
    property_risk_concern: bool = False

    has_car: bool | None = None
    car_brand_model_known: bool = False
    car_year: int | None = None
    car_owner_known: bool = False
    car_pledge_or_restrictions_known: bool = False
    vehicle_refuses_collateral: bool = False
    vehicle_requires_retention: bool = False
    vehicle_refuses_transfer: bool = False
    vehicle_hard_blocker: bool = False

    has_current_loans: bool | None = None
    has_mfo: bool | None = None
    loan_types_known: bool = False
    has_arrears: bool = False
    arrears_months: float | None = None
    collector_pressure: bool = False
    high_payment_load: bool = False
    payment_gap_large: bool = False

    official_income: int | None = None
    other_income: int | None = None
    income_status: Literal["stable", "unstable", "none", "no_official_income", "unknown"] = "unknown"

    client_wants_to_pay: bool = False
    client_fears_bankruptcy: bool = False
    client_refuses_debt_procedure: bool = False
    client_open_to_legal_debt_solution: bool = False

    direct_question: str | None = None
    off_topic_kind: str | None = None
    customer_tone: Literal["neutral", "anxious", "irritated", "resistant", "cooperative"] = "neutral"


def build_case_frame(state: DialogueV3State) -> CaseFrame:
    """Build the compact routing snapshot from canonical facts."""

    frame = CaseFrame()

    service_mode = state.service_mode
    service_signal = _str_value(state, "service_signal")
    if service_mode in {"fraud_check", "repeat_visit"}:
        frame.service_intent = service_mode  # type: ignore[assignment]
    elif service_signal in {"fraud_check", "repeat_visit"}:
        frame.service_intent = service_signal  # type: ignore[assignment]

    frame.need_type = _str_value(state, "need_type", "unknown")  # type: ignore[assignment]
    if frame.service_intent == "fraud_check":
        frame.need_type = "security"
        frame.early_need_signal = "security"
    elif frame.service_intent == "repeat_visit":
        frame.early_need_signal = "repeat"
    else:
        frame.early_need_signal = _str_value(state, "early_need_signal", "unknown")  # type: ignore[assignment]
    frame.explicit_pts_intent = _bool_value(state, "explicit_pts_intent")
    frame.explicit_mortgage_intent = _bool_value(state, "explicit_mortgage_intent")

    # Numeric facts are copied only when already normalized by extraction or tests.
    frame.desired_amount = _int_value(state, "desired_amount")
    frame.total_debt = _int_value(state, "total_debt")
    frame.monthly_payments = _int_value(state, "monthly_payments")
    frame.comfortable_payment = _int_value(state, "comfortable_payment")

    frame.has_property = _bool_or_none(state, "has_property")
    frame.property_region = _str_value(state, "property_region")
    frame.property_type = _str_value(state, "property_type")
    frame.property_owner_known = _bool_value(state, "property_owner_known") or _has_fact(
        state, "property_owner", "property_ownership"
    )
    frame.property_encumbrance_known = _property_encumbrance_known(state)
    frame.property_refuses_collateral = _bool_value(state, "property_refuses_collateral")
    frame.property_risk_concern = _bool_value(state, "property_risk_concern")

    frame.has_car = _bool_or_none(state, "has_car")
    frame.car_brand_model_known = _bool_value(state, "car_brand_model_known") or _has_fact(
        state, "car_brand", "car_model", "raw_car_name"
    )
    frame.car_year = _int_value(state, "car_year")
    frame.car_owner_known = _bool_value(state, "car_owner_known") or _has_fact(state, "car_owner")
    frame.car_pledge_or_restrictions_known = _car_pledge_or_restrictions_known(state)
    frame.vehicle_refuses_collateral = _bool_value(state, "vehicle_refuses_collateral")
    frame.vehicle_requires_retention = _bool_value(state, "vehicle_requires_retention")
    frame.vehicle_refuses_transfer = _bool_value(state, "vehicle_refuses_transfer")
    frame.vehicle_hard_blocker = _bool_value(state, "vehicle_hard_blocker")

    frame.has_current_loans = _bool_or_none(state, "has_current_loans")
    frame.has_mfo = _bool_or_none(state, "has_mfo")
    frame.loan_types_known = _bool_value(state, "loan_types_known") or _has_fact(state, "loan_types")
    frame.has_arrears = _bool_value(state, "has_arrears")
    frame.arrears_months = _float_value(state, "arrears_months")
    frame.collector_pressure = _bool_value(state, "collector_pressure")
    frame.high_payment_load = _bool_value(state, "high_payment_load")
    frame.payment_gap_large = _bool_value(state, "payment_gap_large")

    frame.official_income = _int_value(state, "official_income")
    frame.other_income = _int_value(state, "other_income")
    frame.income_status = _str_value(state, "income_status", "unknown")  # type: ignore[assignment]

    frame.client_wants_to_pay = _bool_value(state, "client_wants_to_pay")
    frame.client_fears_bankruptcy = _bool_value(state, "client_fears_bankruptcy")
    frame.client_refuses_debt_procedure = _bool_value(state, "client_refuses_debt_procedure")
    frame.client_open_to_legal_debt_solution = _bool_value(
        state, "client_open_to_legal_debt_solution"
    )

    frame.direct_question = _str_value(state, "direct_question")
    frame.off_topic_kind = _str_value(state, "off_topic_kind")
    frame.customer_tone = _infer_customer_tone(frame)
    return frame


def _has_fact(state: DialogueV3State, *keys: str) -> bool:
    return any(state.fact_value(key) is not None for key in keys)


def _bool_value(state: DialogueV3State, key: str) -> bool:
    return bool(state.fact_value(key, False))


def _bool_or_none(state: DialogueV3State, key: str) -> bool | None:
    value = state.fact_value(key)
    return value if isinstance(value, bool) else None


def _int_value(state: DialogueV3State, key: str) -> int | None:
    value = state.fact_value(key)
    return value if isinstance(value, int) else None


def _float_value(state: DialogueV3State, key: str) -> float | None:
    value = state.fact_value(key)
    if isinstance(value, (float, int)):
        return float(value)
    return None


def _str_value(state: DialogueV3State, key: str, default: str | None = None) -> str | None:
    value = state.fact_value(key)
    return value if isinstance(value, str) else default


def _property_encumbrance_known(state: DialogueV3State) -> bool:
    if state.fact_value("property_encumbrance") is False:
        return True
    if state.fact_value("property_encumbrance_type") is not None:
        return True
    return (
        state.fact_value("property_mortgage") is False
        and state.fact_value("property_pledge") is False
        and state.fact_value("property_arrest") is False
    )


def _car_pledge_or_restrictions_known(state: DialogueV3State) -> bool:
    return state.fact_value("car_in_pledge") is not None and state.fact_value(
        "car_arrest_or_restriction"
    ) is not None


def _infer_customer_tone(frame: CaseFrame) -> str:
    if frame.property_risk_concern or frame.client_fears_bankruptcy:
        return "anxious"
    if frame.vehicle_requires_retention or frame.vehicle_refuses_transfer:
        return "resistant"
    return "neutral"
