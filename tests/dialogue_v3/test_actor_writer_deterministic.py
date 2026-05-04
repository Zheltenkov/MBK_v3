from __future__ import annotations

import json

from mbk_refactor.dialogue_v3.actor_writer import (
    ActorWriter,
    CompactStateSummary,
)
from mbk_refactor.dialogue_v3.moves import ActorMove
from mbk_refactor.dialogue_v3.response_guard import ResponseGuard


def test_deterministic_ask_slot_returns_short_single_question_without_api_key() -> None:
    writer = ActorWriter(mode="deterministic")
    move = ActorMove(
        move_type="ask_slot",
        selected_route="PTS",
        phase="COLLECTING_PRIMARY_GATES",
        next_slot="car_brand_model",
    )

    output = writer.write(move=move)
    validation = ResponseGuard().validate(output=output, move=move)

    assert output.body == ""
    assert "машина" in output.followup_question.lower()
    assert output.text.count("?") == 1
    assert validation.accepted


def test_vehicle_retention_response_does_not_guarantee_car_retention() -> None:
    writer = ActorWriter(mode="deterministic")
    move = ActorMove(
        move_type="handle_objection_then_ask",
        selected_route="PTS",
        phase="COLLECTING_PRIMARY_GATES",
        next_slot="car_year",
        client_concern="vehicle_retention",
    )

    output = writer.write(move=move)
    validation = ResponseGuard().validate(output=output, move=move)

    assert "машина нужна" in output.body.lower()
    assert "точно останется" not in output.text.lower()
    assert output.text.count("?") == 1
    assert validation.accepted


def test_property_fear_response_does_not_promise_no_risk() -> None:
    writer = ActorWriter(mode="deterministic")
    move = ActorMove(
        move_type="handle_objection_then_ask",
        selected_route="MORTGAGE_MAIN",
        phase="COLLECTING_PRIMARY_GATES",
        next_slot="property_type",
        client_concern="property_risk",
    )

    output = writer.write(move=move)
    validation = ResponseGuard().validate(output=output, move=move)

    assert "риск" in output.body.lower()
    assert "риска нет" not in output.text.lower()
    assert "без риска" not in output.text.lower()
    assert output.text.count("?") == 1
    assert validation.accepted


def test_terminal_action_explains_next_step_without_intake_question() -> None:
    writer = ActorWriter(mode="deterministic")
    move = ActorMove(
        move_type="terminal_action",
        selected_route="BFL_RD",
        phase="READY_FOR_TERMINAL",
        terminal_action="HANDOFF_BFL_SPECIALIST",
    )

    output = writer.write(move=move)
    validation = ResponseGuard().validate(output=output, move=move)

    assert "передам" in output.body.lower()
    assert output.followup_question == ""
    assert output.text.count("?") == 0
    assert validation.accepted


def test_llm_mode_uses_injected_client_without_route_ownership() -> None:
    def fake_client(messages: list[dict[str, str]]) -> str:
        assert "actor_move" in messages[-1]["content"]
        return json.dumps(
            {"body": "", "followup_question": "Какая у вас машина?"},
            ensure_ascii=False,
        )

    writer = ActorWriter(mode="llm", llm_client=fake_client)
    move = ActorMove(
        move_type="ask_slot",
        selected_route="PTS",
        phase="COLLECTING_PRIMARY_GATES",
        next_slot="car_brand_model",
    )

    output = writer.write(
        move=move,
        state_summary=CompactStateSummary(session_id="test", turn_index=1),
    )

    assert output.followup_question == "Какая у вас машина?"
    assert move.selected_route == "PTS"
    assert move.terminal_action is None
