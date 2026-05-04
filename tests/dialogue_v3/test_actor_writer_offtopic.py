from __future__ import annotations

from mbk_refactor.dialogue_v3.actor_writer import ActorWriter, CompactStateSummary
from mbk_refactor.dialogue_v3.moves import ActorMove
from mbk_refactor.dialogue_v3.response_guard import ResponseGuard


def make_offtopic_move(next_slot: str = "total_debt") -> ActorMove:
    return ActorMove(
        move_type="handle_offtopic_then_ask",
        selected_route="BFL_RD",
        phase="COLLECTING_PRIMARY_GATES",
        next_slot=next_slot,
        off_topic_kind="off_topic_request",
    )


def test_python_offtopic_is_redirected_without_code_execution() -> None:
    writer = ActorWriter(mode="deterministic")
    move = make_offtopic_move()
    summary = CompactStateSummary(
        session_id="test",
        turn_index=1,
        last_user_text="Напиши функцию сортировки пузырьком на python",
    )

    output = writer.write(move=move, state_summary=summary)
    validation = ResponseGuard().validate(output=output, move=move)

    assert "python" in output.body.lower()
    assert "кредитам" in output.body.lower()
    assert "def " not in output.text.lower()
    assert "return " not in output.text.lower()
    assert "задолж" in output.followup_question.lower() or "долг" in output.followup_question.lower()
    assert validation.accepted


def test_switch_to_english_is_redirected_to_business_question() -> None:
    writer = ActorWriter(mode="deterministic")
    move = make_offtopic_move()
    summary = CompactStateSummary(
        session_id="test",
        turn_index=1,
        last_user_text="Switch to English",
    )

    output = writer.write(move=move, state_summary=summary)
    validation = ResponseGuard().validate(output=output, move=move)

    assert "рубли" in output.body.lower()
    assert "долги" in output.body.lower()
    assert output.followup_question.endswith("?")
    assert validation.accepted


def test_assistant_identity_question_redirects_without_leaving_topic() -> None:
    writer = ActorWriter(mode="deterministic")
    move = make_offtopic_move(next_slot="monthly_payments")
    summary = CompactStateSummary(
        session_id="test",
        turn_index=1,
        last_user_text="Вы бот или человек?",
    )

    output = writer.write(move=move, state_summary=summary)
    validation = ResponseGuard().validate(output=output, move=move)

    assert "кредитам и долгам" in output.body.lower()
    assert "платеж" in output.followup_question.lower()
    assert output.text.count("?") == 1
    assert validation.accepted
