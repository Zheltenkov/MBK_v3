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


def test_deterministic_offtopic_does_not_use_example_name_without_known_name() -> None:
    writer = ActorWriter(mode="deterministic")
    move = ActorMove(
        move_type="handle_offtopic_then_ask",
        selected_route="BFL_RD",
        phase="COLLECTING_PRIMARY_GATES",
        next_slot="total_debt",
    )

    output = writer.write(
        move=move,
        state_summary=CompactStateSummary(
            session_id="test",
            turn_index=1,
            last_user_text="Напиши функцию на Python",
        ),
    )

    assert "python" in output.body.lower()
    assert "сергей" not in output.text.lower()
    assert "анна" not in output.text.lower()
    assert ResponseGuard().validate(output=output, move=move).accepted


def test_deterministic_offtopic_can_use_explicit_known_client_name() -> None:
    writer = ActorWriter(mode="deterministic")
    move = ActorMove(
        move_type="handle_offtopic_then_ask",
        selected_route="BFL_RD",
        phase="COLLECTING_PRIMARY_GATES",
        next_slot="total_debt",
    )

    output = writer.write(
        move=move,
        state_summary=CompactStateSummary(
            session_id="test",
            turn_index=1,
            last_user_text="Напиши функцию на Python",
            known_facts={"client_first_name": "Иван"},
        ),
    )

    assert output.body.startswith("Иван, ")
    assert "python" in output.body.lower()
    assert ResponseGuard().validate(output=output, move=move).accepted


def test_self_serve_terminal_wording_does_not_handoff_to_specialist() -> None:
    writer = ActorWriter(mode="deterministic")
    for terminal_action in ("SELF_SERVE_LINKS_3", "SELF_SERVE_LINKS_7"):
        move = ActorMove(
            move_type="terminal_action",
            selected_route="UNSECURED",
            phase="READY_FOR_TERMINAL",
            terminal_action=terminal_action,
        )

        output = writer.write(move=move)

        assert "самостоятель" in output.body.lower()
        assert "передам специалисту" not in output.body.lower()
        assert ResponseGuard().validate(output=output, move=move).accepted


def test_handoff_expert_terminal_wording_can_handoff_to_specialist() -> None:
    writer = ActorWriter(mode="deterministic")
    move = ActorMove(
        move_type="terminal_action",
        selected_route="PTS",
        phase="READY_FOR_TERMINAL",
        terminal_action="HANDOFF_EXPERT",
    )

    output = writer.write(move=move)

    assert "передам" in output.body.lower()
    assert "специалист" in output.body.lower()
    assert ResponseGuard().validate(output=output, move=move).accepted


def test_bfl_handoff_terminal_wording_mentions_debt_specialist() -> None:
    writer = ActorWriter(mode="deterministic")
    move = ActorMove(
        move_type="terminal_action",
        selected_route="BFL_RD",
        phase="READY_FOR_TERMINAL",
        terminal_action="HANDOFF_BFL_SPECIALIST",
    )

    output = writer.write(move=move)

    assert "специалисту по долгам" in output.body.lower()
    assert "базовые данные собраны" not in output.body.lower()
    assert ResponseGuard().validate(output=output, move=move).accepted


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
