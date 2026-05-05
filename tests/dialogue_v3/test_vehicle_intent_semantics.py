from __future__ import annotations

import pytest

from mbk_refactor.dialogue_v3.constants import HANDOFF_EXPERT, PTS, SELF_SERVE_LINKS_3
from mbk_refactor.dialogue_v3.engine import DialogueV3Engine
from mbk_refactor.dialogue_v3.facts import extract_turn
from mbk_refactor.dialogue_v3.state import DialogueV3State


def state_with_car() -> DialogueV3State:
    state = DialogueV3State(session_id="vehicle-semantics")
    state.merge_facts({"has_car": True}, source="form")
    return state


def pts_pending_handoff_state() -> DialogueV3State:
    state = DialogueV3State(session_id="pts-pending-handoff")
    state.turn_index = 10
    state.pending_route = PTS
    state.pending_terminal_action = HANDOFF_EXPERT
    state.merge_facts(
        {
            "need_type": "debt_solution",
            "early_need_signal": "debt_solution",
            "has_current_loans": True,
            "has_car": True,
            "explicit_pts_intent": True,
            "vehicle_requires_retention": True,
            "vehicle_refuses_transfer": True,
            "vehicle_refuses_collateral": False,
            "total_debt": 520_000,
            "monthly_payments": 34_000,
            "official_income": 115_000,
            "income_status": "stable",
            "comfortable_payment": 28_000,
            "loan_types_known": True,
            "has_arrears": False,
            "raw_car_name": "Kia Sportage",
            "car_year": 2018,
            "car_owner": "client",
            "car_in_pledge": False,
            "car_arrest_or_restriction": False,
            "car_loan_red_flag": False,
            "car_pledge_red_flag": False,
            "car_arrest_red_flag": False,
            "car_restriction_red_flag": False,
        }
    )
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


def test_vehicle_retention_with_explicit_vehicle_word_is_not_collateral_refusal() -> None:
    extracted = extract_turn("Машина нужна каждый день, отдавать не готов.")

    assert extracted.facts["vehicle_requires_retention"] is True
    assert extracted.facts["vehicle_refuses_transfer"] is True
    assert extracted.facts["vehicle_refuses_collateral"] is False
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


@pytest.mark.parametrize(
    "phrase",
    [
        "только если машину не забирают",
        "без варианта, где машину забирают",
        "готов рассмотреть, но только если я продолжаю пользоваться машиной",
        "передавайте, но машину не забираем",
        "машина нужна каждый день, поэтому только формат без изъятия",
    ],
)
def test_conditional_retention_phrases_are_not_pts_rejection(phrase: str) -> None:
    extracted = extract_turn(phrase, state=state_with_car())

    assert extracted.facts["vehicle_requires_retention"] is True
    assert extracted.facts["vehicle_refuses_transfer"] is True
    assert extracted.facts.get("vehicle_refuses_collateral") is not True
    assert extracted.route_rejection != PTS


@pytest.mark.parametrize(
    "phrase",
    [
        "ПТС не рассматриваю",
        "под машину не хочу",
        "машину не трогаем вообще",
        "никакого варианта с авто",
        "авто в залог не дам",
        "машину как обеспечение не рассматриваю",
    ],
)
def test_hard_pts_refusal_phrases_reject_pts(phrase: str) -> None:
    extracted = extract_turn(phrase, state=state_with_car())

    assert extracted.facts["vehicle_refuses_collateral"] is True
    assert extracted.facts["route_rejection"] == PTS
    assert extracted.route_rejection == PTS


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


def test_s02_pts_continuation_closes_vehicle_slots_without_model_dictionary() -> None:
    state = DialogueV3State(session_id="s02-pts-continuation")
    state.merge_facts(
        {
            "desired_amount": 680_000,
            "has_current_loans": True,
            "has_car": True,
            "employment_type": "найм",
            "total_debt": 520_000,
            "monthly_payments": 34_000,
            "income_status": "stable",
            "comfortable_payment": 28_000,
            "loan_types_known": True,
            "has_arrears": False,
        },
        source="form",
    )
    engine = DialogueV3Engine()

    first = engine.handle_turn(
        "Машину как вариант можно обсуждать, но без того, чтобы её забирать. Она нужна каждый день.",
        state,
    )
    assert first.route_session.selected_route == "PTS"
    assert first.route_session.next_slot == "car_brand_model"

    second = engine.handle_turn("Kia Sportage.", first.state)
    assert second.state.fact_value("raw_car_name") == "Kia Sportage"
    assert second.frame.car_brand_model_known is True
    assert second.route_session.next_slot == "car_year"

    third = engine.handle_turn("2018 года.", second.state)
    assert third.state.fact_value("car_year") == 2018
    assert third.state.fact_value("raw_car_name") == "Kia Sportage"
    assert third.route_session.next_slot == "car_owner"

    fourth = engine.handle_turn("На мне оформлена.", third.state)
    assert fourth.frame.car_owner_known is True
    assert fourth.route_session.next_slot == "car_pledge_or_restrictions"

    fifth = engine.handle_turn(
        "Автокредита нет, в залоге не была, арестов и ограничений тоже нет.",
        fourth.state,
    )

    assert fifth.route_session.selected_route == "PTS"
    assert fifth.route_session.phase == "READY_FOR_TERMINAL"
    assert fifth.route_session.terminal_action == HANDOFF_EXPERT
    assert fifth.actor_move.move_type == "recommendation_offer"
    assert fifth.actor_move.pending_terminal_action == HANDOFF_EXPERT
    assert fifth.events == []
    assert fifth.frame.car_pledge_or_restrictions_known is True
    assert fifth.state.fact_value("car_in_pledge") is False
    assert fifth.state.fact_value("car_arrest_or_restriction") is False
    assert fifth.state.fact_value("car_loan_red_flag") is False
    assert fifth.state.fact_value("car_pledge_red_flag") is False
    assert fifth.state.fact_value("car_arrest_red_flag") is False
    assert fifth.state.fact_value("car_restriction_red_flag") is False
    lowered_text = fifth.text.lower()
    assert "есть ограничение" not in lowered_text
    assert "есть ограничения" not in lowered_text
    assert "есть залог" not in lowered_text
    assert "есть арест" not in lowered_text
    assert "kia sportage 2018 года" in lowered_text
    assert "оформлена на вас" in lowered_text
    assert "без автокредита, залога, арестов и ограничений" in lowered_text
    assert "долг около 520 тысяч" in lowered_text
    assert "платеж 34 тысячи" in lowered_text
    assert "доход официальный" in lowered_text
    assert "просрочек нет" in lowered_text
    assert "передать вас специалисту" in lowered_text

    confirmed = engine.handle_turn("Да, передавайте.", fifth.state)
    assert [event.action_id for event in confirmed.events] == [HANDOFF_EXPERT]
    assert confirmed.state.pending_terminal_action is None


def test_pts_pending_consent_with_retention_condition_emits_handoff_expert() -> None:
    state = pts_pending_handoff_state()

    result = DialogueV3Engine().handle_turn(
        "Да, передавайте. Только важно, чтобы без варианта, где машину забирают, я такое не рассматриваю.",
        state,
    )

    event_action_ids = [event.action_id for event in result.events]
    assert result.route_session.selected_route == PTS
    assert result.actor_move.move_type == "terminal_action"
    assert result.actor_move.terminal_action == HANDOFF_EXPERT
    assert event_action_ids == [HANDOFF_EXPERT]
    assert SELF_SERVE_LINKS_3 not in event_action_ids
    assert result.state.pending_terminal_action is None
    assert result.state.pending_route is None
    assert PTS not in result.state.rejected_routes
    assert result.state.fact_value("vehicle_requires_retention") is True
    assert result.state.fact_value("vehicle_refuses_transfer") is True
    assert result.state.fact_value("vehicle_refuses_collateral") is not True
    assert result.state.fact_value("route_rejection") != PTS
    assert result.route_session.selected_route != "UNSECURED"


def test_pending_terminal_acceptance_has_priority_before_route_reselection() -> None:
    state = pts_pending_handoff_state()

    result = DialogueV3Engine().handle_turn("Да, передавайте.", state)

    assert result.route_session.selected_route == PTS
    assert [event.action_id for event in result.events] == [HANDOFF_EXPERT]
    assert result.state.pending_terminal_action is None
    assert result.state.pending_route is None
    assert PTS not in result.state.rejected_routes


def test_pending_pts_hard_refusal_clears_pending_without_handoff_event() -> None:
    state = pts_pending_handoff_state()

    result = DialogueV3Engine().handle_turn("Нет, машину как обеспечение не рассматриваю.", state)

    assert [event.action_id for event in result.events] == []
    assert result.state.pending_terminal_action is None
    assert result.state.pending_route is None
    assert PTS in result.state.rejected_routes
    assert result.route_session.selected_route != PTS


def test_repeated_pending_terminal_acceptance_does_not_duplicate_action() -> None:
    state = pts_pending_handoff_state()
    state.emitted_terminal_actions.add(f"{PTS}:{HANDOFF_EXPERT}")

    result = DialogueV3Engine().handle_turn("Да, передавайте.", state)

    assert result.events == []
    assert result.state.pending_terminal_action is None
    assert result.state.pending_route is None
