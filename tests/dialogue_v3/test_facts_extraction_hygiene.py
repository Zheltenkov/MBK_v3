from __future__ import annotations

import pytest

from mbk_refactor.dialogue_v3.engine import DialogueV3Engine
from mbk_refactor.dialogue_v3.facts import extract_turn, get_last_asked_slot
from mbk_refactor.dialogue_v3.case_frame import build_case_frame
from mbk_refactor.dialogue_v3.constants import REPEAT_HANDOFF, REPEAT_VISIT
from mbk_refactor.dialogue_v3.slot_resolver import is_slot_closed
from mbk_refactor.dialogue_v3.state import DialogueV3State


def test_debt_intent_beats_repair_purpose() -> None:
    extracted = extract_turn("Хочу закрыть карты и немного оставить на ремонт")

    assert extracted.facts["early_need_signal"] == "debt_solution"
    assert extracted.facts["need_type"] == "debt_solution"
    assert extracted.facts["purpose_goal"] == "repair"


def test_credit_card_debt_intent_with_car_repair_does_not_become_pts() -> None:
    extracted = extract_turn("Хочу закрыть две кредитные карты и немного оставить на ремонт машины.")

    assert extracted.facts["early_need_signal"] == "debt_solution"
    assert extracted.facts["need_type"] == "debt_solution"
    assert extracted.facts["purpose_goal"] == "car_repair"
    assert "explicit_pts_intent" not in extracted.facts
    assert "explicit_mortgage_intent" not in extracted.facts


@pytest.mark.parametrize(
    "text",
    [
        "Хочу закрыть две кредитные карты",
        "Нужно погасить кредитки",
        "Хочу перекрыть долги",
        "Надо объединить кредиты",
        "Хочу рефинансироваться",
        "Платежи тяжело тянуть",
        "Хочу снизить платеж",
    ],
)
def test_live_debt_phrases_set_debt_or_payment_need(text: str) -> None:
    extracted = extract_turn(text)

    assert extracted.facts["need_type"] in {"debt_solution", "payment_reduction"}
    assert extracted.facts["early_need_signal"] in {"debt_solution", "payment_reduction"}


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


def test_income_slot_answer_with_monthly_phrase_does_not_overwrite_monthly_payments() -> None:
    state = DialogueV3State(session_id="income-context")
    state.merge_facts({"monthly_payments": 34_000})
    state.asked_slots.append("income_status")

    extracted = extract_turn("Официальный, работаю по найму. Доход примерно 115 тысяч в месяц.", state=state)

    assert extracted.facts["official_income"] == 115_000
    assert extracted.facts["income_status"] == "stable"
    assert "monthly_payments" not in extracted.facts


def test_income_slot_wins_when_income_and_monthly_contexts_both_appear() -> None:
    state = DialogueV3State(session_id="income-beats-monthly-context")
    state.merge_facts({"monthly_payments": 34_000})
    state.asked_slots.append("income_status")

    extracted = extract_turn(
        "Платеж 34 уже писал, доход примерно 115 тысяч в месяц.",
        state=state,
    )

    assert extracted.facts["official_income"] == 115_000
    assert extracted.facts["income_status"] == "stable"
    assert "monthly_payments" not in extracted.facts
    assert state.fact_value("monthly_payments") == 34_000


@pytest.mark.parametrize(
    "text",
    [
        "Доход 115 тысяч",
        "115 тысяч в месяц",
        "официально 115",
        "работаю, получаю 115",
    ],
)
def test_income_slot_prioritizes_official_income_over_monthly_payment(text: str) -> None:
    state = DialogueV3State(session_id="income-priority")
    state.merge_facts({"monthly_payments": 34_000})
    state.asked_slots.append("income_status")

    extracted = extract_turn(text, state=state)

    assert extracted.facts["official_income"] == 115_000
    assert extracted.facts["income_status"] == "stable"
    assert "monthly_payments" not in extracted.facts
    assert state.fact_value("monthly_payments") == 34_000


def test_monthly_payment_slot_wins_when_income_and_monthly_contexts_both_appear() -> None:
    state = DialogueV3State(session_id="monthly-beats-income-context")
    state.asked_slots.append("monthly_payments")

    extracted = extract_turn("Доход 115 тысяч в месяц", state=state)

    assert extracted.facts["monthly_payments"] == 115_000
    assert "official_income" not in extracted.facts
    assert "income_status" not in extracted.facts


def test_income_answer_keeps_monthly_payments_closed_and_moves_on() -> None:
    state = DialogueV3State(session_id="income-next-slot")
    state.merge_facts(
        {
            "has_current_loans": True,
            "need_type": "debt_solution",
            "total_debt": 520_000,
            "monthly_payments": 34_000,
        },
        source="form",
    )
    state.asked_slots.append("income_status")

    result = DialogueV3Engine().handle_turn("Доход 115 тысяч в месяц", state)

    assert result.extracted.facts["official_income"] == 115_000
    assert "monthly_payments" not in result.extracted.facts
    assert result.state.fact_value("monthly_payments") == 34_000
    assert "monthly_payments" in result.route_session.closed_primary_slots
    assert result.route_session.next_slot != "monthly_payments"


def test_comfortable_payment_answer_with_monthly_word_does_not_overwrite_monthly_payments() -> None:
    state = DialogueV3State(session_id="comfortable-context")
    state.merge_facts({"monthly_payments": 34_000})
    state.asked_slots.append("comfortable_payment")

    extracted = extract_turn("35 тысяч в месяц", state=state)

    assert extracted.facts["comfortable_payment"] == 35_000
    assert "monthly_payments" not in extracted.facts


def test_comfortable_payment_range_uses_upper_bound() -> None:
    state = DialogueV3State(session_id="comfortable-range")
    state.asked_slots.append("comfortable_payment")

    extracted = extract_turn("25-28 тысяч", state=state)

    assert extracted.facts["comfortable_payment"] == 28_000
    assert "monthly_payments" not in extracted.facts


def test_active_dialog_correction_is_not_repeat_visit_service_signal() -> None:
    state = DialogueV3State(session_id="active-correction")
    state.turn_index = 5
    state.merge_facts({"has_current_loans": True, "monthly_payments": 34_000})
    state.asked_slots.append("comfortable_payment")

    extracted = extract_turn("Я уже писал — около 34 тысяч в месяц по двум картам.", state=state)

    assert extracted.service_signal is None
    assert "service_signal" not in extracted.facts
    assert "comfortable_payment" not in extracted.facts


@pytest.mark.parametrize(
    "text",
    [
        "Я уже писал — около 34 тысяч в месяц",
        "Я уже написал выше — около 34 тысяч",
        "Я уже говорил, примерно 34 тысячи",
        "Я же сказал — 34 тысячи",
        "Я уже отвечал на это",
        "Выше написал: 34 тысячи",
        "Я это уже указал",
        "Повторяю, 34 тысячи в месяц",
    ],
)
def test_active_dialog_correction_phrases_do_not_select_repeat_visit(text: str) -> None:
    state = DialogueV3State(session_id="active-correction-route")
    state.turn_index = 3
    state.merge_facts(
        {
            "has_current_loans": True,
            "need_type": "debt_solution",
            "total_debt": 520_000,
            "monthly_payments": 34_000,
        }
    )
    state.asked_slots.append("monthly_payments")

    result = DialogueV3Engine().handle_turn(text, state)

    assert result.extracted.service_signal is None
    assert result.extracted.facts.get("service_signal") is None
    assert result.route_session.selected_route != REPEAT_VISIT
    assert result.route_session.terminal_action != REPEAT_HANDOFF
    assert result.state.fact_value("monthly_payments") == 34_000


@pytest.mark.parametrize(
    "text",
    [
        "Я уже обращался",
        "Я уже оставлял заявку",
        "Я уже переходил в чат",
        "Мне не ответили",
        "Со мной не связались",
        "По старой заявке",
        "Продолжить прошлую заявку",
        "Раньше писал вам и не ответили",
    ],
)
def test_explicit_previous_company_contact_still_selects_repeat_visit(text: str) -> None:
    result = DialogueV3Engine().handle_turn(text)

    assert result.extracted.service_signal == "repeat_visit"
    assert result.route_session.selected_route == REPEAT_VISIT
    assert result.route_session.terminal_action == REPEAT_HANDOFF


def test_manual_ui_cards_repair_hotfix_flow() -> None:
    state = DialogueV3State(session_id="manual-ui-hotfix")
    state.merge_facts(
        {
            "desired_amount": 680_000,
            "full_name": "Громов Денис Андреевич",
            "has_current_loans": True,
            "employment_type": "employment",
            "has_car": True,
            "asset_type": "Недвижимость",
            "has_property": True,
        },
        source="form",
    )
    engine = DialogueV3Engine()

    first = engine.handle_turn(
        "Хочу закрыть две кредитные карты и немного оставить на ремонт машины.",
        state,
    )
    assert first.extracted.facts["need_type"] == "debt_solution"
    assert first.extracted.facts["purpose_goal"] == "car_repair"
    assert "explicit_pts_intent" not in first.extracted.facts
    assert first.route_session.next_slot == "total_debt"
    assert "need_type" in first.route_session.closed_primary_slots

    second = engine.handle_turn(
        "В первую очередь закрыть карты. Если получится, часть суммы оставить на ремонт машины.",
        first.state,
    )
    assert second.extracted.facts["need_type"] == "debt_solution"
    assert second.route_session.next_slot == "total_debt"

    third = engine.handle_turn("Около 520 тысяч по двум кредитным картам.", second.state)
    assert third.extracted.facts["total_debt"] == 520_000
    assert third.route_session.next_slot == "monthly_payments"

    fourth = engine.handle_turn("Примерно 34 тысячи в месяц.", third.state)
    assert fourth.extracted.facts["monthly_payments"] == 34_000
    assert fourth.route_session.next_slot == "income_status"

    fifth = engine.handle_turn(
        "Официальный, работаю по найму. Доход примерно 115 тысяч в месяц.",
        fourth.state,
    )
    assert fifth.extracted.facts["official_income"] == 115_000
    assert fifth.extracted.facts["income_status"] == "stable"
    assert "monthly_payments" not in fifth.extracted.facts
    assert fifth.state.fact_value("monthly_payments") == 34_000
    assert fifth.route_session.next_slot in {"comfortable_payment", "delinquency_context"}
    assert fifth.route_session.selected_route != "REPEAT_VISIT"

    sixth = engine.handle_turn("Я уже писал — около 34 тысяч в месяц по двум картам.", fifth.state)
    assert sixth.extracted.service_signal is None
    assert "service_signal" not in sixth.extracted.facts
    assert sixth.route_session.selected_route != "REPEAT_VISIT"
    assert sixth.route_session.terminal_action is None


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


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Примерно 1 миллион 450 тысяч.", 1_450_000),
        ("1 млн 450 тысяч", 1_450_000),
        ("1,45 млн", 1_450_000),
    ],
)
def test_composite_million_amounts_use_full_value(text: str, expected: int) -> None:
    state = DialogueV3State(session_id="composite-amount")
    state.asked_slots.append("total_debt")

    extracted = extract_turn(text, state=state)

    assert extracted.facts["total_debt"] == expected


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


def test_no_stable_income_extracts_even_when_last_slot_was_monthly_payment() -> None:
    state = DialogueV3State(session_id="unstable-income-after-payment-question")
    state.asked_slots.append("monthly_payments")

    extracted = extract_turn(
        "Дохода стабильного нет, просрочка 3 месяца, коллекторы звонят",
        state=state,
    )

    assert extracted.facts["income_status"] == "unstable"
    assert extracted.facts["has_arrears"] is True
    assert extracted.facts["arrears_months"] == 3.0
    assert extracted.facts["collector_pressure"] is True
    assert "official_income" not in extracted.facts
    assert "monthly_payments" not in extracted.facts


def test_conflicting_fact_is_not_treated_as_closed_slot() -> None:
    state = DialogueV3State(session_id="conflict")
    state.turn_index = 1
    state.merge_facts({"total_debt": 1_000_000})
    state.turn_index = 2
    state.merge_facts({"total_debt": 2_000_000})

    assert state.facts["total_debt"].quality == "conflicting"
    assert state.fact_value("total_debt") is None
    assert is_slot_closed("total_debt", state=state, frame=build_case_frame(state)) is False
