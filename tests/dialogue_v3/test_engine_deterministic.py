from __future__ import annotations

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
    assert [event.action_id for event in result.events] == ["HANDOFF_EXPERT"]
    assert result.events[0].action_id == result.actor_move.terminal_action
    assert result.events[0].selected_route == result.trace.selected_route
    assert result.actor_move.action_scope == "handoff_expert"
    assert result.actor_move.known_facts["car"] == "Kia Rio"
    assert result.actor_move.known_facts["car_year"] == 2019
    assert result.actor_move.known_facts["car_owner"] == "client"
    assert result.actor_move.known_facts["car_in_pledge"] is False
    assert result.actor_move.known_facts["car_arrest_or_restriction"] is False
    assert "has_car" not in result.actor_move.known_facts
    assert "передам" in result.text.lower()


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
    assert "специалисту по долгам" in result.text.lower()


def test_engine_bfl_rd_stable_income_smoke_text_reaches_terminal() -> None:
    result = DialogueV3Engine().handle_turn(
        "Долг 1.7 млн, плачу 78 тыс, доход 125 тыс, комфортно 35 тыс, "
        "просрочка 1 месяц. Банкротство не хочу, хочу платить."
    )

    assert result.extracted.facts.get("has_mfo") is not True
    assert result.trace.selected_route == "BFL_RD"
    assert result.trace.terminal_action == "HANDOFF_BFL_SPECIALIST"
    assert [event.action_id for event in result.events] == ["HANDOFF_BFL_SPECIALIST"]
    assert result.actor_move.action_scope == "bfl_handoff"
