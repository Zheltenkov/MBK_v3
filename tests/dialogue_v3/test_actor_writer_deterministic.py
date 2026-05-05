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

    assert len(output.body.split()) <= 15
    assert "машина" in output.followup_question.lower()
    assert output.text.count("?") == 1
    assert validation.accepted


def test_plain_car_year_question_is_short_without_repeated_justification() -> None:
    writer = ActorWriter(mode="deterministic")
    move = ActorMove(
        move_type="ask_slot",
        selected_route="PTS",
        phase="COLLECTING_PRIMARY_GATES",
        next_slot="car_year",
        question_goal="car_year",
    )

    output = writer.write(move=move)
    lowered = output.text.lower()

    assert output.body == ""
    assert output.followup_question == "Какого года автомобиль?"
    assert output.text.count("?") == 1
    assert "важно понять" not in lowered
    assert "не гадать" not in lowered
    assert "сначала нужно" not in lowered
    assert ResponseGuard().validate(output=output, move=move).accepted


def test_deterministic_plain_debt_slots_are_short_direct_questions() -> None:
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

    assert total_debt.body == ""
    assert total_debt.followup_question == "Какая сейчас общая сумма долгов по кредитам и картам?"
    assert "какой общий размер задолженности" not in total_debt.text.lower()
    assert monthly.body == ""
    assert monthly.followup_question == "Сколько примерно уходит в месяц на платежи?"
    assert "по кредитам и долгам" not in monthly.followup_question.lower()
    assert income.body == ""
    assert income.followup_question == "Какой у вас доход в месяц и он официальный?"
    assert "официальный, неофициальный" not in income.text.lower()


def test_deterministic_income_question_does_not_relabel_monthly_payment_as_income() -> None:
    writer = ActorWriter(mode="deterministic")
    move = ActorMove(
        move_type="ask_slot",
        selected_route="DISCOVERY",
        phase="DISCOVERY",
        next_slot="income_status",
        question_goal="income_status",
        known_facts={
            "monthly_payments": 58_000,
            "official_income": None,
            "other_income": None,
        },
    )

    output = writer.write(move=move)
    lowered = output.text.lower()

    assert output.body == ""
    assert output.followup_question == "Какой у вас доход в месяц и он официальный?"
    assert "58" not in lowered
    assert ResponseGuard().validate(output=output, move=move).accepted


def test_deterministic_common_plain_ask_slots_do_not_add_canned_body() -> None:
    writer = ActorWriter(mode="deterministic")
    plain_slots = [
        "total_debt",
        "monthly_payments",
        "income_status",
        "comfortable_payment",
        "car_brand_model",
        "car_year",
        "car_owner",
        "property_type",
        "property_owner_or_ownership",
        "property_encumbrance_basic",
    ]
    forbidden_phrases = (
        "чтобы не гадать",
        "важно понять",
        "без этой цифры",
        "сначала нужно",
        "по вашим данным",
        "это полезная опора",
        "дальше смотрим не",
    )

    for slot in plain_slots:
        move = ActorMove(
            move_type="ask_slot",
            selected_route="DISCOVERY",
            phase="COLLECTING_PRIMARY_GATES",
            next_slot=slot,
        )
        output = writer.write(move=move)
        lowered = output.text.lower()

        assert output.body == ""
        assert output.followup_question
        assert output.text.count("?") == 1
        assert not any(phrase in lowered for phrase in forbidden_phrases)
        assert ResponseGuard().validate(output=output, move=move).accepted


def test_collateral_preference_keeps_short_bridge_body() -> None:
    writer = ActorWriter(mode="deterministic")
    move = ActorMove(
        move_type="ask_slot",
        selected_route="DISCOVERY",
        phase="COLLECTING_PRIMARY_GATES",
        next_slot="collateral_preference",
    )

    output = writer.write(move=move)

    assert 0 < len(output.body.split()) <= 12
    assert "обычный кредит" in output.body.lower()
    assert output.text.count("?") == 1
    assert ResponseGuard().validate(output=output, move=move).accepted


def test_guard_rejects_canned_justification_for_plain_ask_slot() -> None:
    move = ActorMove(
        move_type="ask_slot",
        selected_route="DISCOVERY",
        phase="COLLECTING_PRIMARY_GATES",
        next_slot="total_debt",
        question_goal="total_debt",
    )
    from mbk_refactor.dialogue_v3.safe_fallback import ActorWriterOutput

    output = ActorWriterOutput(
        body="Чтобы не гадать вслепую, важно понять общую сумму.",
        followup_question="Какая сейчас общая сумма долгов по кредитам и картам?",
    )

    validation = ResponseGuard().validate(output=output, move=move)

    assert not validation.accepted
    assert "plain_ask_slot_canned_phrase" in validation.issue_codes


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

        assert len(output.body.split()) <= 15
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

    assert "машину забирать не хочется" in output.body.lower()
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

    assert "страх за жилье" in output.body.lower()
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


def test_recommendation_offer_summarizes_and_asks_consent_without_event_language_rejection() -> None:
    writer = ActorWriter(mode="deterministic")
    move = ActorMove(
        move_type="recommendation_offer",
        selected_route="PTS",
        phase="READY_FOR_TERMINAL",
        action_scope="handoff_expert",
        pending_route="PTS",
        pending_terminal_action="HANDOFF_EXPERT",
        recommended_product="вариант под ПТС/авто",
        recommendation_summary="Kia Sportage 2018 года, оформлена на вас, без ограничений",
        confirmation_question="Передать вас специалисту, чтобы он проверил детали?",
    )

    output = writer.write(move=move)

    assert "kia sportage" in output.body.lower()
    assert "вариант под птс/авто" in output.body.lower()
    assert output.followup_question == "Передать вас специалисту, чтобы он проверил детали?"
    assert output.text.count("?") == 1
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
    assert "передам" in output.body.lower()
    assert "специалист" in output.body.lower()
    assert "базовые данные собраны" not in output.body.lower()
    assert ResponseGuard().validate(output=output, move=move).accepted


def test_handoff_expert_post_terminal_explains_specialist_next_step_without_new_action() -> None:
    writer = ActorWriter(mode="deterministic")
    move = ActorMove(
        move_type="post_terminal_answer",
        selected_route="MORTGAGE_MAIN",
        phase="READY_FOR_TERMINAL",
        action_scope="handoff_expert",
        direct_answer_topic="post_terminal_next_step",
    )

    output = writer.write(move=move)

    assert "специалист" in output.body.lower()
    assert "передам" not in output.body.lower()
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
