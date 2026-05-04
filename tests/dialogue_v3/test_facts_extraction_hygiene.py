from __future__ import annotations

import pytest

from mbk_refactor.dialogue_v3.engine import DialogueV3Engine
from mbk_refactor.dialogue_v3.facts import extract_turn, get_last_asked_slot
from mbk_refactor.dialogue_v3.case_frame import build_case_frame
from mbk_refactor.dialogue_v3.slot_resolver import is_slot_closed
from mbk_refactor.dialogue_v3.state import DialogueV3State


def test_debt_intent_beats_repair_purpose() -> None:
    extracted = extract_turn("Хочу закрыть карты и немного оставить на ремонт")

    assert extracted.facts["early_need_signal"] == "debt_solution"
    assert extracted.facts["need_type"] == "debt_solution"
    assert extracted.facts["purpose_goal"] == "repair"


def test_repair_alone_is_purpose_not_mortgage() -> None:
    extracted = extract_turn("Нужны деньги на ремонт")

    assert extracted.facts["early_need_signal"] == "repair_or_purpose"
    assert "explicit_mortgage_intent" not in extracted.facts
    assert "has_property" not in extracted.facts


def test_explicit_mortgage_intent_does_not_fill_property_type() -> None:
    extracted = extract_turn("Хочу рассмотреть под квартиру")

    assert extracted.facts["explicit_mortgage_intent"] is True
    assert extracted.facts["early_need_signal"] == "explicit_mortgage"
    assert "property_type" not in extracted.facts
    assert "has_property" not in extracted.facts


def test_property_word_alone_does_not_set_has_property() -> None:
    extracted = extract_turn("Квартира")

    assert "has_property" not in extracted.facts
    assert "property_type" not in extracted.facts


def test_property_risk_concern_does_not_imply_possession() -> None:
    extracted = extract_turn("Боюсь потерять квартиру")

    assert extracted.facts["property_risk_concern"] is True
    assert extracted.facts["property_refuses_collateral"] is False
    assert "has_property" not in extracted.facts
    assert "property_type" not in extracted.facts


def test_property_availability_still_sets_property_fact() -> None:
    extracted = extract_turn("Есть квартира в собственности")

    assert extracted.facts["has_property"] is True
    assert extracted.facts["property_type"] == "apartment"


def test_property_negative_sets_no_property() -> None:
    extracted = extract_turn("Квартиры нет, жилья в собственности нет")

    assert extracted.facts["has_property"] is False
    assert "property_type" not in extracted.facts


def test_property_ownership_phrase_sets_property_fact() -> None:
    extracted = extract_turn("Квартира в собственности")

    assert extracted.facts["has_property"] is True
    assert extracted.facts["property_type"] == "apartment"


def test_wants_to_pay_is_not_hard_debt_procedure_refusal() -> None:
    extracted = extract_turn("Хочу платить")

    assert extracted.facts["client_wants_to_pay"] is True
    assert "client_refuses_debt_procedure" not in extracted.facts


def test_bankruptcy_resistance_is_concern_not_hard_refusal() -> None:
    extracted = extract_turn("Банкротство не хочу, хочу платить")

    assert extracted.facts["client_wants_to_pay"] is True
    assert extracted.facts["client_fears_bankruptcy"] is True
    assert "client_refuses_debt_procedure" not in extracted.facts


def test_bankruptcy_resistance_alone_is_not_hard_refusal() -> None:
    extracted = extract_turn("Банкротство не хочу")

    assert extracted.facts["client_fears_bankruptcy"] is True
    assert "client_refuses_debt_procedure" not in extracted.facts


@pytest.mark.parametrize(
    "text",
    [
        "Никаких судов",
        "Суды не рассматриваю",
        "Юридические процедуры не хочу",
        "Никакого банкротства и реструктуризации",
        "Не хочу никакие процедуры",
    ],
)
def test_hard_debt_procedure_refusal_requires_explicit_hard_phrase(text: str) -> None:
    extracted = extract_turn(text)
    assert extracted.facts["client_refuses_debt_procedure"] is True


def test_combined_hard_debt_procedure_refusal_phrase() -> None:
    extracted = extract_turn("Никаких судов и юридических процедур не хочу")

    assert extracted.facts["client_refuses_debt_procedure"] is True


def test_vehicle_retention_pronoun_requires_vehicle_context() -> None:
    extracted = extract_turn("Она для работы")

    assert "has_car" not in extracted.facts
    assert "explicit_pts_intent" not in extracted.facts
    assert "vehicle_requires_retention" not in extracted.facts


def test_vehicle_retention_with_vehicle_context_is_pts_signal() -> None:
    extracted = extract_turn("Машину отдавать не буду, она для работы")

    assert extracted.facts["has_car"] is True
    assert extracted.facts["explicit_pts_intent"] is True
    assert extracted.facts["vehicle_requires_retention"] is True
    assert extracted.facts["vehicle_refuses_transfer"] is True
    assert extracted.facts["vehicle_refuses_collateral"] is False


def test_vehicle_availability_phrase_sets_pts_signal_for_routes() -> None:
    extracted = extract_turn("Нужны деньги, авто есть")

    assert extracted.facts["has_car"] is True
    assert extracted.facts["explicit_pts_intent"] is True
    assert extracted.facts["early_need_signal"] == "explicit_pts"


def test_vehicle_retention_pronoun_uses_existing_car_context() -> None:
    state = DialogueV3State(session_id="vehicle-context")
    state.merge_facts({"has_car": True}, source="form")

    extracted = extract_turn("Она для работы", state=state)

    assert extracted.facts["explicit_pts_intent"] is True
    assert extracted.facts["vehicle_requires_retention"] is True
    assert extracted.facts["vehicle_refuses_transfer"] is True
    assert extracted.facts["vehicle_refuses_collateral"] is False


def test_get_last_asked_slot_prefers_asked_slots() -> None:
    state = DialogueV3State(session_id="last-slot")
    state.asked_slots.extend(["total_debt", "monthly_payments"])
    state.trace_history.append({"next_slot": "comfortable_payment"})

    assert get_last_asked_slot(state) == "monthly_payments"


@pytest.mark.parametrize(
    "text",
    [
        "ПТС не рассматриваю",
        "Не хочу залог на машину",
        "Машину вообще не трогаем",
        "Никаких автозалогов",
        "Авто не трогаем",
    ],
)
def test_vehicle_collateral_refusal_is_not_pts_intent(text: str) -> None:
    extracted = extract_turn(text)

    assert extracted.facts["vehicle_refuses_collateral"] is True
    assert extracted.route_rejection == "PTS"
    assert "explicit_pts_intent" not in extracted.facts


def test_vehicle_collateral_refusal_can_coexist_with_separate_pts_intent() -> None:
    extracted = extract_turn("Хочу под ПТС, но ПТС не рассматриваю")

    assert extracted.facts["explicit_pts_intent"] is True
    assert extracted.facts["vehicle_refuses_collateral"] is True


def test_amounts_follow_last_asked_slot_context() -> None:
    state = DialogueV3State(session_id="facts-context")
    state.merge_facts({"has_current_loans": True}, source="form")
    engine = DialogueV3Engine()

    first = engine.handle_turn("Хочу закрыть долги", state)
    assert first.route_session.next_slot == "total_debt"

    second = engine.handle_turn("Около 1.7 млн", first.state)
    assert second.extracted.facts["total_debt"] == 1_700_000
    assert second.route_session.next_slot == "monthly_payments"

    third = engine.handle_turn("78 тысяч", second.state)
    assert third.extracted.facts["monthly_payments"] == 78_000
    assert third.route_session.next_slot == "income_status"

    fourth = engine.handle_turn("125 тысяч, работаю официально", third.state)
    assert fourth.extracted.facts["official_income"] == 125_000
    assert fourth.extracted.facts["income_status"] == "stable"
    assert fourth.route_session.next_slot == "comfortable_payment"

    fifth = engine.handle_turn("35 тысяч", fourth.state)
    assert fifth.extracted.facts["comfortable_payment"] == 35_000


@pytest.mark.parametrize(
    ("slot", "text", "fact_key", "expected"),
    [
        ("total_debt", "1.7 млн", "total_debt", 1_700_000),
        ("monthly_payments", "78 тысяч", "monthly_payments", 78_000),
        ("comfortable_payment", "35 тысяч", "comfortable_payment", 35_000),
    ],
)
def test_short_amounts_use_asked_slot_context(
    slot: str,
    text: str,
    fact_key: str,
    expected: int,
) -> None:
    state = DialogueV3State(session_id=f"amount-{slot}")
    state.asked_slots.append(slot)

    extracted = extract_turn(text, state=state)

    assert extracted.facts[fact_key] == expected


def test_month_duration_does_not_fill_contextual_payment_amount() -> None:
    state = DialogueV3State(session_id="month-duration")
    state.asked_slots.append("monthly_payments")

    extracted = extract_turn("Дохода стабильного нет, просрочка 3 месяца", state=state)

    assert "monthly_payments" not in extracted.facts
    assert extracted.facts["arrears_months"] == 3.0


def test_standalone_amount_without_context_is_not_total_debt() -> None:
    extracted = extract_turn("1.7 млн")

    assert "total_debt" not in extracted.facts


def test_monthly_payment_keyword_extracts_without_previous_context() -> None:
    extracted = extract_turn("78 тысяч в месяц")

    assert extracted.facts["monthly_payments"] == 78_000


def test_comfortable_payment_does_not_match_mfo() -> None:
    extracted = extract_turn("Мне комфортно платить 35 тысяч")

    assert extracted.facts["comfortable_payment"] == 35_000
    assert extracted.facts.get("has_mfo") is not True


def test_mfo_token_and_arrears_extract_debt_signals() -> None:
    extracted = extract_turn("Есть МФО и просрочка")

    assert extracted.facts["has_mfo"] is True
    assert extracted.facts["has_arrears"] is True


def test_income_amount_with_official_marker() -> None:
    extracted = extract_turn("125 тысяч, официально работаю")

    assert extracted.facts["official_income"] == 125_000
    assert extracted.facts["income_status"] == "stable"


def test_no_stable_income_and_arrears_months_do_not_create_income_amount() -> None:
    extracted = extract_turn("Дохода стабильного нет, просрочка 3 месяца, коллекторы звонят")

    assert extracted.facts["income_status"] == "unstable"
    assert extracted.facts["has_arrears"] is True
    assert extracted.facts["arrears_months"] == 3.0
    assert extracted.facts["collector_pressure"] is True
    assert "official_income" not in extracted.facts


def test_conflicting_fact_is_not_treated_as_closed_slot() -> None:
    state = DialogueV3State(session_id="conflict")
    state.turn_index = 1
    state.merge_facts({"total_debt": 1_000_000})
    state.turn_index = 2
    state.merge_facts({"total_debt": 2_000_000})

    assert state.facts["total_debt"].quality == "conflicting"
    assert state.fact_value("total_debt") is None
    assert is_slot_closed("total_debt", state=state, frame=build_case_frame(state)) is False
