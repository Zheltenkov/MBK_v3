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
    user_message = "Нужны деньги, авто есть"

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
    result = DialogueV3Engine().handle_turn("Нужны деньги, авто есть")

    assert result.trace.selected_route == "PTS"
    assert isinstance(result.trace.selected_route, str)
    assert result.state.route.selected_route == result.trace.selected_route


def test_engine_pts_retention_does_not_create_handoff_before_primary_slots() -> None:
    engine = DialogueV3Engine()
    first = engine.handle_turn("Нужны деньги, авто есть")
    second = engine.handle_turn("Машину отдавать не буду, она для работы", first.state)

    assert second.trace.selected_route == "PTS"
    assert second.route_session.terminal_action is None
    assert second.events == []
    assert_no_handoff_language(second.text)


def test_engine_non_terminal_response_has_no_handoff_language() -> None:
    result = DialogueV3Engine().handle_turn("Нужны деньги, авто есть")

    assert result.route_session.terminal_action is None
    assert result.events == []
    assert_no_handoff_language(result.text)


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
    assert "передам" in result.text.lower()
