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

    assert output.body
    assert "авто" in output.body.lower()
    assert "машина" in output.followup_question.lower()
    assert output.text.count("?") == 1
    assert validation.accepted


def test_deterministic_debt_slots_are_manager_like_not_bare_questionnaire() -> None:
    writer = ActorWriter(mode="deterministic")

    total_debt = writer.write(
        move=ActorMove(
            move_type="ask_slot",
            selected_route="DISCOVERY",
            phase="DISCOVERY",
            next_slot="total_debt",
        )
    )
    monthly = writer.write(
        move=ActorMove(
            move_type="ask_slot",
            selected_route="DISCOVERY",
            phase="DISCOVERY",
            next_slot="monthly_payments",
        )
    )
    income = writer.write(
        move=ActorMove(
            move_type="ask_slot",
            selected_route="DISCOVERY",
            phase="DISCOVERY",
            next_slot="income_status",
        )
    )

    assert "не добирать лишнего вслепую" in total_debt.body.lower()
    assert "сколько сейчас всего задолженности" in total_debt.followup_question.lower()
    assert "какой общий размер задолженности" not in total_debt.text.lower()
    assert "зафиксировал сумму" in monthly.body.lower()
    assert monthly.followup_question == "Сколько сейчас уходит в месяц на платежи?"
    assert "по кредитам и долгам" not in monthly.followup_question.lower()
    assert "давит на бюджет" in income.body.lower()
    assert income.followup_question == "Какой у вас сейчас доход в месяц и он официальный?"
    assert "официальный, неофициальный" not in income.text.lower()


def test_deterministic_followup_slots_cover_debt_and_car_flow() -> None:
    writer = ActorWriter(mode="deterministic")
    slots = [
        "need_type",
        "total_debt",
        "monthly_payments",
        "income_status",
        "comfortable_payment",
        "delinquency_context",
        "car_brand_model",
        "car_year",
        "car_owner",
        "car_pledge_or_restrictions",
    ]

    for slot in slots:
        move = ActorMove(
            move_type="ask_slot",
            selected_route="DISCOVERY",
            phase="COLLECTING_PRIMARY_GATES",
            next_slot=slot,
        )
        output = writer.write(move=move)

        assert output.body
        assert output.followup_question
        assert output.text.count("?") == 1
        assert ResponseGuard().validate(output=output, move=move).accepted


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
    assert "базовые данные собраны" not in output.body.lower()
    assert ResponseGuard().validate(output=output, move=move).accepted


def test_mortgage_terminal_wording_is_specific_not_generic_basic_data() -> None:
    writer = ActorWriter(mode="deterministic")
    move = ActorMove(
        move_type="terminal_action",
        selected_route="MORTGAGE_MAIN",
        phase="READY_FOR_TERMINAL",
        terminal_action="HANDOFF_EXPERT",
    )

    output = writer.write(move=move)

    assert "недвижимости" in output.body.lower()
    assert "базовые данные собраны" not in output.body.lower()
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


def test_llm_writer_payload_contains_runtime_context_for_manager_like_wording() -> None:
    calls: list[list[dict[str, str]]] = []

    def fake_client(messages: list[dict[str, str]]) -> str:
        calls.append(messages)
        return json.dumps(
            {
                "body": "Понял. Тогда сначала считаем нагрузку, а не добираем новый кредит вслепую.",
                "followup_question": "Сколько сейчас всего долгов?",
            },
            ensure_ascii=False,
        )

    from mbk_refactor.dialogue_v3.engine import DialogueV3Engine

    result = DialogueV3Engine(
        writer_mode="llm",
        actor_writer=ActorWriter(mode="llm", llm_client=fake_client),
    ).handle_turn("Хочу закрыть долги, платежи тяжело тянуть")

    payload = json.loads(calls[0][-1]["content"])
    context = payload["writer_context"]

    assert result.route_session.next_slot == "total_debt"
    assert context["latest_user_message"] == "Хочу закрыть долги, платежи тяжело тянуть"
    assert context["newly_extracted_facts"]["need_type"] == "debt_solution"
    assert context["selected_route"] == result.route_session.selected_route
    assert context["move_type"] == result.actor_move.move_type
    assert context["next_slot"] == "total_debt"
    assert context["terminal_action"] is None
    assert context["terminal_action_already_emitted"] is False
    assert "клиент хочет закрыть долги" in context["conversation_summary"]
    assert "slot_wording_hints" in payload


def test_compact_state_summary_excludes_conflicting_facts() -> None:
    from mbk_refactor.dialogue_v3.actor_writer import build_compact_state_summary
    from mbk_refactor.dialogue_v3.state import DialogueV3State

    state = DialogueV3State(session_id="conflict-summary")
    state.merge_facts({"monthly_payments": 34_000})
    state.merge_facts({"monthly_payments": 115_000})

    summary = build_compact_state_summary(state)

    assert state.facts["monthly_payments"].quality == "conflicting"
    assert "monthly_payments" not in (summary.known_facts or {})


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
