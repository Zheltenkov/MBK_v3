from __future__ import annotations

from mbk_refactor.dialogue_v3.actions import ActionEvent
from mbk_refactor.dialogue_v3.moves import ActorMove
from mbk_refactor.dialogue_v3.response_guard import ResponseGuard
from mbk_refactor.dialogue_v3.safe_fallback import ActorWriterOutput


def validate_text(text: str, move: ActorMove):
    output = ActorWriterOutput(body=text)
    return ResponseGuard().validate(output=output, move=move)


def test_guard_rejects_internal_words() -> None:
    move = ActorMove(move_type="ask_slot", selected_route="PTS", phase="COLLECTING", next_slot="car_year")

    validation = validate_text("Сейчас route PTS проходит через validator.", move)
    pipeline_validation = validate_text("Сейчас пайплайн выбрал следующий слот.", move)

    assert not validation.accepted
    assert "internal_word" in validation.issue_codes
    assert not pipeline_validation.accepted
    assert "internal_word" in pipeline_validation.issue_codes


def test_guard_rejects_more_than_one_question() -> None:
    move = ActorMove(move_type="ask_slot", selected_route="PTS", phase="COLLECTING", next_slot="car_year")

    validation = validate_text("Какая машина? Какого года?", move)

    assert not validation.accepted
    assert "too_many_questions" in validation.issue_codes


def test_guard_rejects_forbidden_guarantees() -> None:
    move = ActorMove(
        move_type="handle_objection_then_ask",
        selected_route="MORTGAGE_MAIN",
        phase="COLLECTING",
        next_slot="property_type",
    )

    validation = validate_text("Риска нет, квартиру точно не затронет. Это квартира?", move)

    assert not validation.accepted
    assert "forbidden_claim" in validation.issue_codes


def test_guard_rejects_handoff_language_without_terminal_action() -> None:
    move = ActorMove(move_type="ask_slot", selected_route="PTS", phase="COLLECTING", next_slot="car_year")

    validation = validate_text("Передам специалисту, а пока какого года автомобиль?", move)

    assert not validation.accepted
    assert "handoff_without_action" in validation.issue_codes


def test_guard_accepts_handoff_language_with_terminal_action_and_event() -> None:
    move = ActorMove(
        move_type="terminal_action",
        selected_route="PTS",
        phase="READY_FOR_TERMINAL",
        terminal_action="HANDOFF_EXPERT",
    )
    output = ActorWriterOutput(body="Передам ситуацию специалисту для проверки без обещаний заранее.")
    events = [ActionEvent(action_id="HANDOFF_EXPERT", selected_route="PTS", payload={})]

    validation = ResponseGuard().validate(output=output, move=move, events=events)

    assert validation.accepted


def test_guard_rejects_terminal_action_without_matching_event() -> None:
    move = ActorMove(
        move_type="terminal_action",
        selected_route="PTS",
        phase="READY_FOR_TERMINAL",
        terminal_action="HANDOFF_EXPERT",
    )
    output = ActorWriterOutput(body="Передам ситуацию специалисту для проверки без обещаний заранее.")

    validation = ResponseGuard().validate(output=output, move=move, events=[])

    assert not validation.accepted
    assert "missing_action_event" in validation.issue_codes


def test_guard_rejects_terminal_action_with_non_empty_followup_question() -> None:
    move = ActorMove(
        move_type="terminal_action",
        selected_route="PTS",
        phase="READY_FOR_TERMINAL",
        terminal_action="HANDOFF_EXPERT",
    )
    output = ActorWriterOutput(
        body="Передам ситуацию специалисту для проверки без обещаний заранее.",
        followup_question="Какая у вас машина?",
    )

    validation = ResponseGuard().validate(output=output, move=move)

    assert not validation.accepted
    assert validation.repairable is True
    assert "terminal_followup_question" in validation.issue_codes


def test_guard_rejects_terminal_action_with_visible_question_mark() -> None:
    move = ActorMove(
        move_type="no_solution_manual_review",
        selected_route="OTHER",
        phase="TERMINAL",
        terminal_action="MANUAL_REVIEW",
    )
    output = ActorWriterOutput(body="Передам ситуацию на ручную проверку. Сколько сейчас всего долгов?")

    validation = ResponseGuard().validate(output=output, move=move)

    assert not validation.accepted
    assert validation.repairable is True
    assert "terminal_followup_question" in validation.issue_codes


def test_guard_rejects_internal_workflow_terms() -> None:
    move = ActorMove(move_type="ask_slot", selected_route="PTS", phase="COLLECTING", next_slot="car_year")

    branch_validation = validate_text("В этой ветке дальше нужен один факт.", move)
    collection_validation = validate_text("Сейчас идет сбор данных по заявке.", move)

    assert not branch_validation.accepted
    assert "internal_workflow_term" in branch_validation.issue_codes
    assert not collection_validation.accepted
    assert "internal_workflow_term" in collection_validation.issue_codes


def test_guard_accepts_normal_customer_facing_words() -> None:
    move = ActorMove(move_type="ask_slot", selected_route="PTS", phase="COLLECTING", next_slot="car_year")

    validation = validate_text("Проверка условий у специалиста идет по вашему варианту долга.", move)

    assert validation.accepted


def test_guard_rejects_url_invention() -> None:
    move = ActorMove(move_type="ask_slot", selected_route="PTS", phase="COLLECTING", next_slot="car_year")

    validation = validate_text("Заполните форму на https://example.com", move)

    assert not validation.accepted
    assert "url_invention" in validation.issue_codes


def test_guard_rejects_empty_response() -> None:
    move = ActorMove(move_type="ask_slot", selected_route="PTS", phase="COLLECTING", next_slot="car_year")

    validation = ResponseGuard().validate(output=ActorWriterOutput(), move=move)

    assert not validation.accepted
    assert "empty_response" in validation.issue_codes


def test_guard_rejects_offtopic_execution() -> None:
    move = ActorMove(
        move_type="handle_offtopic_then_ask",
        selected_route="BFL_RD",
        phase="COLLECTING",
        next_slot="total_debt",
    )

    validation = validate_text("def sort_items(items):\n    return items", move)

    assert not validation.accepted
    assert "offtopic_executed" in validation.issue_codes
