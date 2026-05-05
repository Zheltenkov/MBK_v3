"""Composite slot resolution for dialogue_v3 intake."""

from __future__ import annotations

from dataclasses import dataclass

from .case_frame import CaseFrame
from .state import DialogueV3State


@dataclass(frozen=True)
class SlotResolution:
    closed_primary_slots: list[str]
    missing_primary_slots: list[str]
    next_slot: str | None


def resolve_primary_slots(
    primary_slots: list[str],
    *,
    state: DialogueV3State,
    frame: CaseFrame,
) -> SlotResolution:
    """Resolve composite slots and pick the first safe question."""

    closed: list[str] = []
    missing: list[str] = []
    for slot in primary_slots:
        if is_slot_closed(slot, state=state, frame=frame):
            closed.append(slot)
        else:
            missing.append(slot)
    return SlotResolution(
        closed_primary_slots=closed,
        missing_primary_slots=missing,
        next_slot=missing[0] if missing else None,
    )


def is_slot_closed(slot: str, *, state: DialogueV3State, frame: CaseFrame) -> bool:
    """Return whether a semantic slot group already has enough evidence."""

    if slot in state.closed_slot_groups:
        return True

    if slot == "property_owner_or_ownership":
        return frame.property_owner_known
    if slot == "property_encumbrance_basic":
        return frame.property_encumbrance_known
    if slot == "car_brand_model":
        return frame.car_brand_model_known
    if slot == "car_pledge_or_restrictions":
        return frame.car_pledge_or_restrictions_known
    if slot == "income_status":
        return (
            frame.income_status != "unknown"
            or frame.official_income is not None
            or frame.other_income is not None
        )
    if slot == "delinquency_context":
        return frame.arrears_months is not None or _fact_known(state, "has_arrears")
    if slot == "desired_amount_or_total_debt":
        return frame.desired_amount is not None or frame.total_debt is not None
    if slot == "need_type":
        return _need_type_known(frame)
    if slot == "collateral_preference":
        return (
            "collateral_preference" in state.asked_slots
            or frame.explicit_pts_intent
            or frame.explicit_mortgage_intent
            or frame.vehicle_refuses_collateral
            or frame.property_refuses_collateral
        )
    if slot == "bfl_property_context":
        return _bfl_property_context_closed(state, frame)
    if slot == "bfl_dependents_context":
        return _bfl_dependents_context_closed(state)
    if slot == "bfl_vehicle_context":
        return _bfl_vehicle_context_closed(state, frame)
    if slot == "previous_debt_procedure":
        return _fact_known(state, "previous_debt_procedure")

    # Simple slots use direct fact names plus CaseFrame fields where available.
    if slot == "property_type":
        return frame.property_type is not None
    if slot == "car_year":
        return frame.car_year is not None
    if slot == "car_owner":
        return frame.car_owner_known
    if slot == "total_debt":
        return frame.total_debt is not None
    if slot == "monthly_payments":
        return frame.monthly_payments is not None
    if slot == "comfortable_payment":
        return frame.comfortable_payment is not None
    if slot == "loan_types":
        return frame.loan_types_known or frame.has_mfo is not None
    if slot == "urgency":
        return _fact_known(state, "urgency")

    return _fact_known(state, slot)


def _fact_known(state: DialogueV3State, key: str) -> bool:
    return state.fact_value(key) is not None


def _bfl_property_context_closed(state: DialogueV3State, frame: CaseFrame) -> bool:
    if state.fact_value("bfl_property_context_known") is True:
        return True
    if frame.has_property is False:
        return True
    return bool(
        frame.property_type
        and frame.property_region
        and frame.property_owner_known
        and frame.property_encumbrance_known
        and _fact_known(state, "is_only_housing")
    )


def _bfl_dependents_context_closed(state: DialogueV3State) -> bool:
    if state.fact_value("bfl_dependents_context_known") is True:
        return True
    if state.fact_value("has_dependents") is False:
        return True
    return _fact_known(state, "dependents_count") or _fact_known(state, "dependent_relation")


def _bfl_vehicle_context_closed(state: DialogueV3State, frame: CaseFrame) -> bool:
    if state.fact_value("bfl_vehicle_context_known") is True:
        return True
    if frame.has_car is False:
        return True
    return frame.car_brand_model_known and frame.car_year is not None


def _need_type_known(frame: CaseFrame) -> bool:
    if frame.need_type in {"new_money", "debt_solution", "payment_reduction", "security"}:
        return True
    return bool(
        frame.total_debt is not None
        or frame.monthly_payments is not None
        or frame.high_payment_load
        or frame.payment_gap_large
        or frame.client_wants_to_pay
        or frame.has_mfo
        or frame.collector_pressure
    )
