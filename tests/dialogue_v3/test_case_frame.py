from __future__ import annotations

from mbk_refactor.dialogue_v3.case_frame import build_case_frame
from mbk_refactor.dialogue_v3.facts import extract_turn
from mbk_refactor.dialogue_v3.state import DialogueV3State


def state_from_messages(messages: list[str]) -> DialogueV3State:
    state = DialogueV3State(session_id="test")
    for message in messages:
        state.turn_index += 1
        state.add_user_message(message)
        state.merge_extracted_turn(extract_turn(message, turn_index=state.turn_index))
    return state


def test_pts_retention_is_not_refusal() -> None:
    state = state_from_messages(
        [
            "Нужны деньги, авто есть",
            "Машину отдавать не буду, она для работы",
        ]
    )

    frame = build_case_frame(state)

    assert frame.has_car is True
    assert frame.vehicle_requires_retention is True
    assert frame.vehicle_refuses_transfer is True
    assert frame.vehicle_refuses_collateral is False


def test_property_fear_is_not_refusal() -> None:
    state = state_from_messages(["Квартира есть, но потерять ее боюсь"])

    frame = build_case_frame(state)

    assert frame.has_property is True
    assert frame.property_risk_concern is True
    assert frame.property_refuses_collateral is False


def test_fact_merge_marks_conflict_without_silent_overwrite() -> None:
    state = DialogueV3State(session_id="test")
    state.turn_index = 1
    state.merge_facts({"desired_amount": 500_000})
    state.turn_index = 2
    state.merge_facts({"desired_amount": 700_000})

    fact = state.facts["desired_amount"]
    assert fact.value == 500_000
    assert fact.quality == "conflicting"
