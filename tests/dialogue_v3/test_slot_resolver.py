from __future__ import annotations

from mbk_refactor.dialogue_v3.case_frame import build_case_frame
from mbk_refactor.dialogue_v3.slot_resolver import is_slot_closed
from mbk_refactor.dialogue_v3.state import DialogueV3State


def state_with_facts(facts: dict[str, object]) -> DialogueV3State:
    state = DialogueV3State(session_id="test")
    state.turn_index = 1
    state.merge_facts(facts)
    return state


def assert_slot_closed(slot: str, facts: dict[str, object]) -> None:
    state = state_with_facts(facts)
    frame = build_case_frame(state)
    assert is_slot_closed(slot, state=state, frame=frame)


def test_property_owner_or_ownership_slot() -> None:
    assert_slot_closed("property_owner_or_ownership", {"property_owner": "client"})
    assert_slot_closed("property_owner_or_ownership", {"property_owner_known": True})


def test_property_encumbrance_basic_slot() -> None:
    assert_slot_closed("property_encumbrance_basic", {"property_encumbrance": False})
    assert_slot_closed(
        "property_encumbrance_basic",
        {
            "property_mortgage": False,
            "property_pledge": False,
            "property_arrest": False,
        },
    )


def test_car_brand_model_slot() -> None:
    assert_slot_closed("car_brand_model", {"car_brand": "Kia"})
    assert_slot_closed("car_brand_model", {"raw_car_name": "Kia Rio"})


def test_car_pledge_or_restrictions_slot() -> None:
    assert_slot_closed(
        "car_pledge_or_restrictions",
        {"car_in_pledge": False, "car_arrest_or_restriction": False},
    )


def test_income_status_slot() -> None:
    assert_slot_closed("income_status", {"official_income": 120_000})
    assert_slot_closed("income_status", {"income_status": "no_official_income"})


def test_delinquency_context_slot() -> None:
    assert_slot_closed("delinquency_context", {"arrears_months": 1.0})
    assert_slot_closed("delinquency_context", {"has_arrears": False})


def test_desired_amount_or_total_debt_slot() -> None:
    assert_slot_closed("desired_amount_or_total_debt", {"desired_amount": 300_000})
    assert_slot_closed("desired_amount_or_total_debt", {"total_debt": 900_000})
