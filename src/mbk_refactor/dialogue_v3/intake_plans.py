"""Primary intake contracts per selected route."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class IntakePlan:
    route: str
    primary_slots: list[str]
    terminal_action: str
    max_questions: int
    allow_terminal_after_primary: bool = True


INTAKE_PLANS: dict[str, IntakePlan] = {
    "MORTGAGE_MAIN": IntakePlan(
        route="MORTGAGE_MAIN",
        primary_slots=[
            "property_type",
            "property_owner_or_ownership",
            "property_encumbrance_basic",
        ],
        terminal_action="HANDOFF_EXPERT",
        max_questions=4,
    ),
    "MORTGAGE_AUX": IntakePlan(
        route="MORTGAGE_AUX",
        primary_slots=[
            "property_type",
            "property_owner_or_ownership",
            "property_encumbrance_basic",
        ],
        terminal_action="SELF_SERVE_LINKS_3",
        max_questions=4,
    ),
    "PTS": IntakePlan(
        route="PTS",
        primary_slots=[
            "car_brand_model",
            "car_year",
            "car_owner",
            "car_pledge_or_restrictions",
        ],
        terminal_action="HANDOFF_EXPERT",
        max_questions=5,
    ),
    "AUTO_AUX": IntakePlan(
        route="AUTO_AUX",
        primary_slots=[
            "car_brand_model",
            "car_year",
            "car_owner",
            "car_pledge_or_restrictions",
        ],
        terminal_action="SELF_SERVE_LINKS_3",
        max_questions=5,
    ),
    "BFL_RD": IntakePlan(
        route="BFL_RD",
        primary_slots=[
            "need_type",
            "total_debt",
            "monthly_payments",
            "income_status",
            "comfortable_payment",
            "delinquency_context",
        ],
        terminal_action="HANDOFF_BFL_SPECIALIST",
        max_questions=6,
    ),
    "BFL_RI": IntakePlan(
        route="BFL_RI",
        primary_slots=[
            "total_debt",
            "income_status",
            "delinquency_context",
            "loan_types",
        ],
        terminal_action="HANDOFF_BFL_SPECIALIST",
        max_questions=6,
    ),
    "UNSECURED": IntakePlan(
        route="UNSECURED",
        primary_slots=[
            "desired_amount_or_total_debt",
            "income_status",
            "monthly_payments",
            "delinquency_context",
        ],
        terminal_action="SELF_SERVE_LINKS_3",
        max_questions=5,
    ),
    "MICRO": IntakePlan(
        route="MICRO",
        primary_slots=[
            "desired_amount_or_total_debt",
            "urgency",
        ],
        terminal_action="SELF_SERVE_LINKS_7",
        max_questions=3,
    ),
    "FRAUD_CHECK": IntakePlan(
        route="FRAUD_CHECK",
        primary_slots=[],
        terminal_action="SECURITY_FLOW",
        max_questions=0,
    ),
    "REPEAT_VISIT": IntakePlan(
        route="REPEAT_VISIT",
        primary_slots=[],
        terminal_action="REPEAT_HANDOFF",
        max_questions=1,
    ),
    "OTHER": IntakePlan(
        route="OTHER",
        primary_slots=[],
        terminal_action="MANUAL_REVIEW",
        max_questions=0,
    ),
}


def get_intake_plan(route: str) -> IntakePlan:
    """Return the intake plan for one selected route."""

    try:
        return INTAKE_PLANS[route]
    except KeyError as exc:
        raise ValueError(f"unknown route: {route}") from exc
