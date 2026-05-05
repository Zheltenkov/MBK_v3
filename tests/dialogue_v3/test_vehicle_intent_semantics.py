from __future__ import annotations

from mbk_refactor.dialogue_v3.engine import DialogueV3Engine
from mbk_refactor.dialogue_v3.facts import extract_turn
from mbk_refactor.dialogue_v3.state import DialogueV3State


def state_with_car() -> DialogueV3State:
    state = DialogueV3State(session_id="vehicle-semantics")
    state.merge_facts({"has_car": True}, source="form")
    return state


def test_natural_pts_consideration_with_retention_is_not_collateral_refusal() -> None:
    state = state_with_car()

    extracted = extract_turn(
        "Машину можно рассмотреть, но отдавать её не готов — она каждый день нужна. "
        "Если вариант с ПТС, то только чтобы машина оставалась у меня.",
        state=state,
    )

    assert extracted.facts["explicit_pts_intent"] is True
    assert extracted.facts["early_need_signal"] == "explicit_pts"
    assert extracted.facts["vehicle_requires_retention"] is True
    assert extracted.facts["vehicle_refuses_transfer"] is True
    assert extracted.facts["vehicle_refuses_collateral"] is False
    assert extracted.route_rejection != "PTS"
    assert "vehicle_retention" in extracted.customer_concerns


def test_retention_alone_with_known_car_context_is_pts_consideration_constraint() -> None:
    state = state_with_car()

    extracted = extract_turn("Она каждый день нужна, отдавать её не готов.", state=state)

    assert extracted.facts["vehicle_requires_retention"] is True
    assert extracted.facts["vehicle_refuses_transfer"] is True
    assert extracted.facts["vehicle_refuses_collateral"] is False
    assert extracted.facts["explicit_pts_intent"] is True
    assert extracted.route_rejection != "PTS"


def test_hard_vehicle_collateral_refusal_rejects_pts() -> None:
    extracted = extract_turn("ПТС не рассматриваю, машину вообще не трогаем.")

    assert extracted.facts["vehicle_refuses_collateral"] is True
    assert extracted.facts["route_rejection"] == "PTS"
    assert extracted.route_rejection == "PTS"


def test_hard_vehicle_collateral_refusal_does_not_select_pts_route() -> None:
    state = state_with_car()

    result = DialogueV3Engine().handle_turn("ПТС не рассматриваю, машину вообще не трогаем.", state)

    assert result.route_session.selected_route != "PTS"


def test_vehicle_availability_is_not_pts_intent() -> None:
    extracted = extract_turn("У меня есть машина.")

    assert extracted.facts["has_car"] is True
    assert "explicit_pts_intent" not in extracted.facts


def test_explicit_pts_without_retention_sets_pts_intent_only() -> None:
    state = state_with_car()

    extracted = extract_turn("Можно рассмотреть под ПТС.", state=state)

    assert extracted.facts["explicit_pts_intent"] is True
    assert extracted.facts.get("vehicle_requires_retention") is not True
    assert extracted.facts.get("vehicle_refuses_collateral") is not True


def test_s02_natural_pts_phrase_switches_to_pts_route() -> None:
    state = DialogueV3State(session_id="s02-natural-pts")
    state.merge_facts(
        {
            "desired_amount": 680_000,
            "has_current_loans": True,
            "has_car": True,
            "employment_type": "найм",
        },
        source="form",
    )

    result = DialogueV3Engine().handle_turn(
        "Машину можно рассмотреть, но отдавать её не готов — она каждый день нужна. "
        "Если вариант с ПТС, то только чтобы машина оставалась у меня.",
        state,
    )

    assert result.route_session.selected_route == "PTS"
    assert result.route_session.next_slot == "car_brand_model"
    assert result.route_session.terminal_action is None
    assert result.frame.vehicle_requires_retention is True
    assert result.frame.vehicle_refuses_collateral is False
