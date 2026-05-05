"""Primary intake contracts per selected route."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from .constants import (
    AUTO_AUX,
    BFL_RD,
    BFL_RI,
    DISCOVERY,
    FRAUD_CHECK,
    HANDOFF_BFL_SPECIALIST,
    HANDOFF_EXPERT,
    MANUAL_REVIEW,
    MICRO,
    MORTGAGE_AUX,
    MORTGAGE_MAIN,
    OTHER,
    PTS,
    REPEAT_HANDOFF,
    REPEAT_VISIT,
    SECURITY_FLOW,
    SELF_SERVE_LINKS_3,
    SELF_SERVE_LINKS_7,
    UNSECURED,
)

if TYPE_CHECKING:
    from .case_frame import CaseFrame
    from .state import DialogueV3State


@dataclass(frozen=True)
class IntakePlan:
    route: str
    primary_slots: list[str]
    terminal_action: str
    max_questions: int
    allow_terminal_after_primary: bool = True


INTAKE_PLANS: dict[str, IntakePlan] = {
    DISCOVERY: IntakePlan(
        route=DISCOVERY,
        primary_slots=[
            "need_type",
            "total_debt",
            "monthly_payments",
            "income_status",
            "comfortable_payment",
            "delinquency_context",
        ],
        terminal_action="",
        max_questions=6,
        allow_terminal_after_primary=False,
    ),
    MORTGAGE_MAIN: IntakePlan(
        route=MORTGAGE_MAIN,
        primary_slots=[
            "property_type",
            "property_owner_or_ownership",
            "property_encumbrance_basic",
        ],
        terminal_action=HANDOFF_EXPERT,
        max_questions=4,
    ),
    MORTGAGE_AUX: IntakePlan(
        route=MORTGAGE_AUX,
        primary_slots=[
            "property_type",
            "property_owner_or_ownership",
            "property_encumbrance_basic",
        ],
        terminal_action=SELF_SERVE_LINKS_3,
        max_questions=4,
    ),
    PTS: IntakePlan(
        route=PTS,
        primary_slots=[
            "car_brand_model",
            "car_year",
            "car_owner",
            "car_pledge_or_restrictions",
        ],
        terminal_action=HANDOFF_EXPERT,
        max_questions=5,
    ),
    # Reserved until the auxiliary car-collateral routing rule is finalized.
    AUTO_AUX: IntakePlan(
        route=AUTO_AUX,
        primary_slots=[
            "car_brand_model",
            "car_year",
            "car_owner",
            "car_pledge_or_restrictions",
        ],
        terminal_action=SELF_SERVE_LINKS_3,
        max_questions=5,
    ),
    BFL_RD: IntakePlan(
        route=BFL_RD,
        primary_slots=[
            "need_type",
            "total_debt",
            "monthly_payments",
            "income_status",
            "comfortable_payment",
            "delinquency_context",
        ],
        terminal_action=HANDOFF_BFL_SPECIALIST,
        max_questions=6,
    ),
    BFL_RI: IntakePlan(
        route=BFL_RI,
        primary_slots=[
            "total_debt",
            "income_status",
            "delinquency_context",
            "loan_types",
        ],
        terminal_action=HANDOFF_BFL_SPECIALIST,
        max_questions=6,
    ),
    UNSECURED: IntakePlan(
        route=UNSECURED,
        primary_slots=[
            "desired_amount_or_total_debt",
            "income_status",
            "monthly_payments",
            "delinquency_context",
        ],
        terminal_action=SELF_SERVE_LINKS_3,
        max_questions=5,
    ),
    MICRO: IntakePlan(
        route=MICRO,
        primary_slots=[
            "desired_amount_or_total_debt",
            "urgency",
        ],
        terminal_action=SELF_SERVE_LINKS_7,
        max_questions=3,
    ),
    FRAUD_CHECK: IntakePlan(
        route=FRAUD_CHECK,
        primary_slots=[],
        terminal_action=SECURITY_FLOW,
        max_questions=0,
    ),
    REPEAT_VISIT: IntakePlan(
        route=REPEAT_VISIT,
        primary_slots=[],
        terminal_action=REPEAT_HANDOFF,
        max_questions=1,
    ),
    OTHER: IntakePlan(
        route=OTHER,
        primary_slots=[],
        terminal_action=MANUAL_REVIEW,
        max_questions=0,
    ),
}


def get_intake_plan(route: str) -> IntakePlan:
    """Return the intake plan for one selected route."""

    try:
        return INTAKE_PLANS[route]
    except KeyError as exc:
        raise ValueError(f"unknown route: {route}") from exc


def primary_slots_for_route(
    route: str,
    frame: CaseFrame,
    state: DialogueV3State | None = None,
) -> list[str]:
    """Return route primary slots, with DISCOVERY staying router-neutral."""

    plan = get_intake_plan(route)
    if route != DISCOVERY:
        slots = list(plan.primary_slots)
        if route in {BFL_RD, BFL_RI}:
            slots.extend(_bfl_risk_slots(frame, state))
        return slots
    return discovery_primary_slots(frame)


def _bfl_risk_slots(frame: CaseFrame, state: DialogueV3State | None) -> list[str]:
    """Add short BFL risk-context slots only when root facts make them relevant."""

    slots: list[str] = []
    has_property = frame.has_property is True or _state_asset_type_is_property(state)
    has_dependents = _state_bool(state, "has_dependents") is True
    has_car = frame.has_car is True

    if has_property:
        slots.append("bfl_property_context")
    if has_dependents:
        slots.append("bfl_dependents_context")
    if has_car:
        slots.append("bfl_vehicle_context")
    if has_property or has_dependents or has_car:
        slots.append("previous_debt_procedure")
    return slots


def discovery_primary_slots(frame: CaseFrame) -> list[str]:
    """Pick DISCOVERY slots from the known need without committing to a product route."""

    if frame.need_type in {"debt_solution", "payment_reduction"}:
        slots = [
            "total_debt",
            "monthly_payments",
            "income_status",
            "comfortable_payment",
            "delinquency_context",
        ]
        if frame.has_car is True or frame.has_property is True:
            slots.append("collateral_preference")
        slots.append("loan_types")
        return slots
    if frame.early_need_signal == "repair_or_purpose":
        return ["desired_amount_or_total_debt", "income_status", "urgency"]
    if frame.need_type == "new_money":
        return [
            "desired_amount_or_total_debt",
            "income_status",
            "monthly_payments",
            "delinquency_context",
        ]
    return ["need_type"]


def _state_bool(state: DialogueV3State | None, key: str) -> bool | None:
    if state is None:
        return None
    value = state.fact_value(key)
    return value if isinstance(value, bool) else None


def _state_asset_type_is_property(state: DialogueV3State | None) -> bool:
    if state is None:
        return False
    value = state.fact_value("asset_type")
    if not isinstance(value, str):
        return False
    return "недвиж" in value.lower().replace("ё", "е")
