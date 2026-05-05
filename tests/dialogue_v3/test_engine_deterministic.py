from __future__ import annotations

from mbk_refactor.dialogue_v3.actor_writer import ActorWriter
from mbk_refactor.dialogue_v3.constants import HANDOFF_EXPERT, SELF_SERVE_LINKS_3
from mbk_refactor.dialogue_v3.engine import DialogueV3Engine
from mbk_refactor.dialogue_v3.state import DialogueV3State


HANDOFF_LANGUAGE = ("передам", "специалисту", "отправлю")


def assert_no_handoff_language(text: str) -> None:
    lowered = text.lower()
    for phrase in HANDOFF_LANGUAGE:
        assert phrase not in lowered


def test_engine_never_returns_empty_assistant_response() -> None:
    result = DialogueV3Engine().handle_turn("")

    assert result.text.strip()
    assert result.state.messages[-1].content == result.text


def test_engine_full_one_turn_deterministic_flow_without_terminal_event() -> None:
    user_message = "Можно рассмотреть под ПТС"

    result = DialogueV3Engine().handle_turn(user_message)

    # user_message -> facts/state
    assert result.extracted.raw_user_text == user_message
    assert result.extracted.facts["has_car"] is True
    assert result.state.fact_value("has_car") is True
    assert result.state.messages[0].role == "user"
    assert result.state.messages[0].content == user_message

    # facts/state -> CaseFrame -> selected_route
    assert result.frame.has_car is True
    assert result.trace.selected_route == "PTS"

    # selected_route -> RouteSession -> ActorMove
    assert result.route_session.selected_route == "PTS"
    assert result.route_session.phase == "COLLECTING_PRIMARY_GATES"
    assert result.route_session.next_slot == "car_brand_model"
    assert result.route_session.terminal_action is None
    assert result.actor_move.move_type == "ask_slot"
    assert result.actor_move.next_slot == "car_brand_model"
    assert result.actor_move.terminal_action is None

    # ActorMove -> deterministic response -> optional ActionEvent -> trace
    assert result.text == result.writer_output.text
    assert "машина" in result.text.lower()
    assert result.events == []
    assert result.trace.next_slot == "car_brand_model"
    assert result.trace.terminal_action is None
    assert result.trace.event_action_ids == []
    assert result.state.trace_history[-1]["selected_route"] == "PTS"
    assert_no_handoff_language(result.text)


def test_engine_has_one_selected_route_per_turn() -> None:
    result = DialogueV3Engine().handle_turn("Можно рассмотреть под ПТС")

    assert result.trace.selected_route == "PTS"
    assert isinstance(result.trace.selected_route, str)
    assert result.state.route.selected_route == result.trace.selected_route


def test_engine_pts_retention_does_not_create_handoff_before_primary_slots() -> None:
    engine = DialogueV3Engine()
    first = engine.handle_turn("Можно рассмотреть под ПТС")
    second = engine.handle_turn("Машину отдавать не буду, она для работы", first.state)

    assert second.trace.selected_route == "PTS"
    assert second.route_session.terminal_action is None
    assert second.events == []
    assert_no_handoff_language(second.text)


def test_engine_non_terminal_response_has_no_handoff_language() -> None:
    result = DialogueV3Engine().handle_turn("Можно рассмотреть под ПТС")

    assert result.route_session.terminal_action is None
    assert result.events == []
    assert_no_handoff_language(result.text)


def test_engine_records_asked_slot_after_each_assistant_question() -> None:
    engine = DialogueV3Engine()
    first = engine.handle_turn("Хочу взять денег")
    second = engine.handle_turn("Хочу закрыть долги, платежи тяжело тянуть", first.state)

    assert first.state.asked_slots[0] == "need_type"
    assert second.state.asked_slots[-1] == "total_debt"
    assert [message.role for message in second.state.messages][-2:] == ["user", "assistant"]


def test_engine_grounding_context_keeps_monthly_payment_from_becoming_income() -> None:
    state = DialogueV3State(session_id="monthly-payment-grounding")
    state.turn_index = 2
    state.merge_facts(
        {
            "has_current_loans": True,
            "need_type": "debt_solution",
            "early_need_signal": "debt_solution",
            "total_debt": 720_000,
        }
    )
    state.asked_slots.append("monthly_payments")

    result = DialogueV3Engine().handle_turn("Сейчас примерно 58 тысяч в месяц.", state)
    lowered = result.text.lower()

    assert result.extracted.facts["monthly_payments"] == 58_000
    assert result.route_session.next_slot == "income_status"
    assert result.actor_move.known_facts["monthly_payments"] == 58_000
    assert result.actor_move.known_facts["official_income"] is None
    assert result.actor_move.known_facts["other_income"] is None
    assert "доход у вас" not in lowered or "58" not in lowered
    assert "58 тысяч" not in lowered
    assert "доход" in lowered


def test_engine_correction_turn_does_not_conflict_total_debt_with_income_amount() -> None:
    state = DialogueV3State(session_id="correction-income-grounding")
    state.turn_index = 3
    state.merge_facts(
        {
            "has_current_loans": True,
            "need_type": "debt_solution",
            "early_need_signal": "debt_solution",
            "total_debt": 1_100_000,
            "monthly_payments": 58_000,
        }
    )
    state.asked_slots.append("income_status")

    result = DialogueV3Engine().handle_turn(
        "Нет, 58 тысяч — это платежи по долгам. "
        "Доход у меня около 170 тысяч в месяц, официально работаю по найму.",
        state,
    )

    assert result.extracted.facts["monthly_payments"] == 58_000
    assert result.extracted.facts["official_income"] == 170_000
    assert result.extracted.facts["income_status"] == "stable"
    assert "total_debt" not in result.extracted.facts
    assert result.state.facts["total_debt"].value == 1_100_000
    assert result.state.facts["total_debt"].quality != "conflicting"
    assert result.state.fact_value("monthly_payments") == 58_000
    assert result.state.fact_value("official_income") == 170_000
    assert result.state.fact_value("income_status") == "stable"


def test_engine_writer_exception_uses_fallback_without_duplicate_user_message() -> None:
    state = DialogueV3State(session_id="writer-error-idempotent")
    state.turn_index = 3
    state.merge_facts(
        {
            "has_current_loans": True,
            "need_type": "debt_solution",
            "early_need_signal": "debt_solution",
            "total_debt": 1_100_000,
            "monthly_payments": 58_000,
        }
    )
    state.asked_slots.append("income_status")
    state.add_assistant_message("Какой у вас доход в месяц и он официальный?")

    def failing_client(messages: list[dict[str, str]]) -> str:
        raise RuntimeError("AuthenticationError 401 Incorrect API key")

    user_message = (
        "Нет, 58 тысяч — это платежи по долгам. "
        "Доход у меня около 170 тысяч в месяц, официально работаю по найму."
    )
    result = DialogueV3Engine(
        writer_mode="llm_guarded",
        actor_writer=ActorWriter(mode="llm_guarded", llm_client=failing_client),
    ).handle_turn(user_message, state)

    matching_user_messages = [
        message for message in result.state.messages
        if message.role == "user" and message.content == user_message
    ]
    assert len(matching_user_messages) == 1
    assert result.fallback_used is True
    assert result.writer_error == "RuntimeError: AuthenticationError 401 Incorrect API key"
    assert "writer_exception_fallback" in result.initial_writer_validation.issue_codes
    assert result.state.messages[-2].role == "user"
    assert result.state.messages[-1].role == "assistant"
    assert result.state.fact_value("monthly_payments") == 58_000
    assert result.state.fact_value("official_income") == 170_000
    assert result.state.asked_slots.count("income_status") == 1
    assert result.events == []


def test_engine_retry_of_unanswered_user_turn_reuses_existing_message() -> None:
    state = DialogueV3State(session_id="retry-existing-user-turn")
    state.turn_index = 4
    state.merge_facts(
        {
            "has_current_loans": True,
            "need_type": "debt_solution",
            "early_need_signal": "debt_solution",
            "total_debt": 1_100_000,
            "monthly_payments": 58_000,
        }
    )
    state.asked_slots.append("income_status")
    user_message = "Нет, 58 тысяч — это платежи. Доход 170 тысяч, официально."
    state.add_user_message(user_message)

    result = DialogueV3Engine().handle_turn(user_message, state)

    matching_user_messages = [
        message for message in result.state.messages
        if message.role == "user" and message.content == user_message
    ]
    assert len(matching_user_messages) == 1
    assert result.state.turn_index == 4
    assert result.trace.turn_index == 4
    assert result.state.messages[-2].role == "user"
    assert result.state.messages[-1].role == "assistant"
    assert result.state.fact_value("monthly_payments") == 58_000
    assert result.state.fact_value("official_income") == 170_000
    assert result.state.asked_slots.count("income_status") == 1
    assert result.events == []


def test_engine_fraud_sms_code_bypasses_intake_with_event() -> None:
    result = DialogueV3Engine().handle_turn("Мне позвонили от вашего имени и попросили код из СМС.")

    assert result.trace.selected_route == "FRAUD_CHECK"
    assert result.trace.terminal_action == "SECURITY_FLOW"
    assert [event.action_id for event in result.events] == ["SECURITY_FLOW"]
    assert result.events[0].selected_route == result.trace.selected_route
    assert result.route_session.primary_slots == []


def test_engine_repeat_visit_bypasses_intake_with_event() -> None:
    result = DialogueV3Engine().handle_turn("Я уже переходил в чат, но мне не ответили.")

    assert result.trace.selected_route == "REPEAT_VISIT"
    assert result.trace.terminal_action == "REPEAT_HANDOFF"
    assert [event.action_id for event in result.events] == ["REPEAT_HANDOFF"]
    assert result.events[0].selected_route == result.trace.selected_route
    assert result.route_session.primary_slots == []


def test_engine_terminal_action_only_after_primary_slots_for_product_flow() -> None:
    state = DialogueV3State(session_id="test")
    state.turn_index = 1
    state.merge_facts(
        {
            "has_car": True,
            "raw_car_name": "Kia Rio",
            "car_year": 2019,
            "car_owner": "client",
            "car_in_pledge": False,
            "car_arrest_or_restriction": False,
        }
    )

    result = DialogueV3Engine().handle_turn("Да, все верно", state)

    assert result.trace.selected_route == "PTS"
    assert result.trace.terminal_action == "HANDOFF_EXPERT"
    assert result.actor_move.move_type == "recommendation_offer"
    assert result.actor_move.pending_terminal_action == "HANDOFF_EXPERT"
    assert result.state.pending_route == "PTS"
    assert result.events == []
    assert result.actor_move.action_scope == "handoff_expert"
    assert result.actor_move.known_facts["car"] == "Kia Rio"
    assert result.actor_move.known_facts["car_year"] == 2019
    assert result.actor_move.known_facts["car_owner"] == "client"
    assert result.actor_move.known_facts["car_in_pledge"] is False
    assert result.actor_move.known_facts["car_arrest_or_restriction"] is False
    assert "has_car" not in result.actor_move.known_facts
    assert "передать вас специалисту" in result.text.lower()

    confirmed = DialogueV3Engine().handle_turn("да", result.state)
    assert confirmed.actor_move.move_type == "terminal_action"
    assert confirmed.actor_move.terminal_action == "HANDOFF_EXPERT"
    assert [event.action_id for event in confirmed.events] == ["HANDOFF_EXPERT"]
    assert confirmed.state.pending_route is None
    assert confirmed.state.pending_terminal_action is None


def test_engine_declines_pending_handoff_without_emitting_pending_action() -> None:
    state = DialogueV3State(session_id="decline-pts-offer")
    state.turn_index = 5
    state.merge_facts(
        {
            "need_type": "debt_solution",
            "early_need_signal": "debt_solution",
            "has_current_loans": True,
            "has_car": True,
            "total_debt": 520_000,
            "monthly_payments": 34_000,
            "income_status": "stable",
            "comfortable_payment": 28_000,
            "loan_types_known": True,
            "has_arrears": False,
            "raw_car_name": "Kia Sportage",
            "car_year": 2018,
            "car_owner": "client",
            "car_in_pledge": False,
            "car_arrest_or_restriction": False,
        }
    )
    engine = DialogueV3Engine()
    offer = engine.handle_turn("Да, все верно", state)
    assert offer.actor_move.move_type == "recommendation_offer"
    assert offer.events == []

    declined = engine.handle_turn("Нет, ПТС не рассматриваю.", offer.state)

    assert "PTS" in declined.state.rejected_routes
    assert declined.state.pending_terminal_action is None
    assert declined.events == []
    assert declined.trace.selected_route != "PTS"


def test_engine_terminal_self_serve_links_has_action_scope_and_no_handoff_wording() -> None:
    state = DialogueV3State(session_id="test")
    state.turn_index = 1
    state.merge_facts(
        {
            "desired_amount": 80_000,
            "income_status": "stable",
            "monthly_payments": 8_000,
            "has_arrears": False,
            "urgency": "today",
        }
    )

    result = DialogueV3Engine().handle_turn("Да", state)

    assert result.trace.selected_route == "UNSECURED"
    assert result.trace.terminal_action == "SELF_SERVE_LINKS_3"
    assert result.actor_move.action_scope == "self_serve_links"
    assert result.actor_move.known_facts["desired_amount_or_total_debt"] == 80_000
    assert result.actor_move.known_facts["urgency"] == "today"
    assert "передам специалисту" not in result.text.lower()


def test_engine_clean_debt_complete_without_collateral_exits_to_unsecured_self_serve() -> None:
    state = DialogueV3State(session_id="clean-debt-unsecured")
    state.turn_index = 5
    state.merge_facts(
        {
            "need_type": "debt_solution",
            "early_need_signal": "debt_solution",
            "has_current_loans": True,
            "total_debt": 400_000,
            "monthly_payments": 10_000,
            "income_status": "stable",
            "comfortable_payment": 8_000,
            "loan_types_known": True,
            "loan_types": ("credit_cards",),
        }
    )
    state.asked_slots.append("delinquency_context")

    result = DialogueV3Engine().handle_turn("Просрочек нет.", state)

    assert result.trace.selected_route == "UNSECURED"
    assert result.route_session.terminal_action == SELF_SERVE_LINKS_3
    assert result.actor_move.move_type == "terminal_action"
    assert result.actor_move.action_scope == "self_serve_links"
    assert [event.action_id for event in result.events] == [SELF_SERVE_LINKS_3]
    assert result.route_session.next_slot is None
    assert "специалисту по долгам" not in result.text.lower()
    assert "ручн" not in result.text.lower()


def test_engine_pts_red_flags_still_handoff_without_guarantee_language() -> None:
    state = DialogueV3State(session_id="pts-red-flags")
    state.turn_index = 1
    state.merge_facts(
        {
            "has_car": True,
            "raw_car_name": "Kia Rio",
            "car_year": 2005,
            "car_old_year": True,
            "car_year_red_flag": True,
            "car_owner": "third_party",
            "third_party_car_owner": True,
            "car_owner_red_flag": True,
            "car_in_pledge": True,
            "car_pledge_red_flag": True,
            "car_arrest_or_restriction": False,
        }
    )

    result = DialogueV3Engine().handle_turn("Да", state)

    assert result.trace.selected_route == "PTS"
    assert result.route_session.terminal_action == HANDOFF_EXPERT
    assert result.actor_move.known_facts["car_old_year"] is True
    assert result.actor_move.known_facts["third_party_car_owner"] is True
    assert result.actor_move.known_facts["car_pledge_red_flag"] is True
    assert "проверит" in result.text.lower()
    assert "точно" not in result.text.lower()


def test_engine_mortgage_red_flags_still_handoff_without_guarantee_language() -> None:
    state = DialogueV3State(session_id="mortgage-red-flags")
    state.turn_index = 1
    state.merge_facts(
        {
            "has_property": True,
            "property_type": "apartment",
            "property_region": "Москва",
            "property_region_supported": True,
            "property_owner": "third_party",
            "property_owner_known": True,
            "third_party_property_owner": True,
            "property_owner_red_flag": True,
            "property_encumbrance": True,
            "property_mortgage": True,
            "property_encumbrance_type": "mortgage",
            "property_encumbrance_red_flag": True,
        }
    )

    result = DialogueV3Engine().handle_turn("Да", state)

    assert result.trace.selected_route == "MORTGAGE_MAIN"
    assert result.route_session.terminal_action == HANDOFF_EXPERT
    assert result.actor_move.known_facts["third_party_property_owner"] is True
    assert result.actor_move.known_facts["property_encumbrance_red_flag"] is True
    assert "проверит" in result.text.lower()
    assert "точно" not in result.text.lower()


def test_engine_terminal_bfl_handoff_has_scope_and_compact_known_facts() -> None:
    state = DialogueV3State(session_id="test")
    state.turn_index = 1
    state.merge_facts(
        {
            "has_current_loans": True,
            "total_debt": 1_700_000,
            "monthly_payments": 78_000,
            "income_status": "stable",
            "comfortable_payment": 35_000,
            "has_arrears": False,
            "client_wants_to_pay": True,
        }
    )

    result = DialogueV3Engine().handle_turn("Хочу платить, но меньше", state)

    assert result.trace.selected_route == "BFL_RD"
    assert result.trace.terminal_action == "HANDOFF_BFL_SPECIALIST"
    assert result.actor_move.action_scope == "bfl_handoff"
    assert result.actor_move.known_facts["total_debt"] == 1_700_000
    assert result.actor_move.known_facts["monthly_payments"] == 78_000
    assert result.actor_move.known_facts["income_status"] == "stable"
    assert result.actor_move.known_facts["comfortable_payment"] == 35_000
    assert result.actor_move.known_facts["client_wants_to_pay"] is True
    assert "has_current_loans" not in result.actor_move.known_facts
    lowered = result.text.lower()
    assert "специалисту по долгам" in lowered
    assert "долг около 1,7 млн" in lowered
    assert "платеж 78 тысяч" in lowered
    assert "доход официальный" in lowered
    assert "не обещание списания" in lowered
    assert "специалист проверит применимость" in lowered


def test_engine_bfl_rd_stable_income_smoke_text_reaches_terminal() -> None:
    result = DialogueV3Engine().handle_turn(
        "Долг 1.7 млн, плачу 78 тыс, доход 125 тыс, комфортно 35 тыс, "
        "просрочка 1 месяц. Банкротство не хочу, хочу платить."
    )

    assert result.extracted.facts.get("has_mfo") is not True
    assert result.trace.selected_route == "BFL_RD"
    assert result.trace.terminal_action == "HANDOFF_BFL_SPECIALIST"
    assert result.actor_move.move_type == "recommendation_offer"
    assert result.actor_move.pending_terminal_action == "HANDOFF_BFL_SPECIALIST"
    assert result.events == []
    assert result.actor_move.action_scope == "bfl_handoff"
    lowered = result.text.lower()
    assert "не обещание списания" in lowered
    assert "реструктуризации" in lowered
    assert "передать вас специалисту по долгам" in lowered

    confirmed = DialogueV3Engine().handle_turn("давайте", result.state)
    assert [event.action_id for event in confirmed.events] == ["HANDOFF_BFL_SPECIALIST"]
    assert confirmed.state.pending_terminal_action is None
