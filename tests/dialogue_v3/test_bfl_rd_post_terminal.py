from __future__ import annotations

from mbk_refactor.dialogue_v3.constants import BFL_RD, HANDOFF_BFL_SPECIALIST, REPEAT_VISIT
from mbk_refactor.dialogue_v3.engine import DialogueV3Engine
from mbk_refactor.dialogue_v3.state import DialogueV3State


def _sorokina_state() -> DialogueV3State:
    state = DialogueV3State(session_id="sorokina-bfl-rd")
    state.merge_facts(
        {
            "desired_amount": 1_450_000,
            "full_name": "Сорокина Елена Павловна",
            "has_current_loans": True,
            "employment_type": "найм",
            "has_car": True,
            "has_property": True,
        },
        source="form",
    )
    return state


def test_bfl_rd_terminal_explains_handoff_and_post_terminal_clarifications_do_not_duplicate_events() -> None:
    engine = DialogueV3Engine()
    state = _sorokina_state()

    first = engine.handle_turn(
        "Добрый день. Мне бы в первую очередь снизить платёж и закрыть долги, потому что сейчас уже тяжеловато тянуть.",
        state,
    )
    assert first.route_session.next_slot == "total_debt"

    second = engine.handle_turn("Примерно 1 миллион 450 тысяч.", first.state)
    assert second.state.fact_value("total_debt") == 1_450_000
    assert second.route_session.next_slot == "monthly_payments"

    third = engine.handle_turn("Около 62 тысяч в месяц.", second.state)
    assert third.state.fact_value("monthly_payments") == 62_000
    assert third.route_session.next_slot == "income_status"

    fourth = engine.handle_turn(
        "Официально получаю примерно 105 тысяч в месяц, работаю по найму.",
        third.state,
    )
    assert fourth.state.fact_value("official_income") == 105_000
    assert fourth.state.fact_value("income_status") == "stable"
    assert fourth.state.fact_value("monthly_payments") == 62_000
    assert fourth.route_session.next_slot in {"comfortable_payment", "delinquency_context"}

    fifth = engine.handle_turn(
        "Где-то 30-35 тысяч было бы нормально. Сейчас 62 тысячи уже прям тяжело.",
        fourth.state,
    )
    assert fifth.state.fact_value("comfortable_payment") == 35_000
    assert fifth.route_session.next_slot == "delinquency_context"

    sixth = engine.handle_turn(
        "Есть, но небольшая. По одной кредитке просрочка где-то недели три, меньше месяца.",
        fifth.state,
    )
    lowered = sixth.text.lower()

    assert sixth.route_session.selected_route == BFL_RD
    assert sixth.route_session.terminal_action == HANDOFF_BFL_SPECIALIST
    assert [event.action_id for event in sixth.events] == [HANDOFF_BFL_SPECIALIST]
    assert sixth.state.fact_value("total_debt") == 1_450_000
    assert "передам специалисту по долгам" in lowered
    assert "платеж" in lowered or "нагруз" in lowered
    assert "обещан" in lowered
    assert sixth.text.count("?") == 0

    seventh = engine.handle_turn("Хорошо, а что дальше?", sixth.state)
    seventh_lowered = seventh.text.lower()

    assert seventh.extracted.facts["post_terminal_topic"] == "next_step"
    assert seventh.frame.post_terminal_topic == "next_step"
    assert seventh.route_session.selected_route == BFL_RD
    assert seventh.actor_move.move_type == "post_terminal_answer"
    assert seventh.actor_move.direct_answer_topic == "post_terminal_next_step"
    assert seventh.events == []
    assert seventh.route_session.selected_route != REPEAT_VISIT
    assert "специалист по долгам" in seventh_lowered
    assert seventh.text.count("?") == 0

    eighth = engine.handle_turn(
        "Это банкротство или можно без него?",
        seventh.state,
    )
    eighth_lowered = eighth.text.lower()

    assert eighth.extracted.facts["post_terminal_topic"] == "bankruptcy_clarification"
    assert eighth.frame.post_terminal_topic == "bankruptcy_clarification"
    assert eighth.actor_move.move_type == "post_terminal_answer"
    assert eighth.actor_move.direct_answer_topic == "bankruptcy_clarification"
    assert eighth.events == []
    assert "не обязательно банкротство" in eighth_lowered
    assert "посильный график" in eighth_lowered or "реструктуризац" in eighth_lowered
    assert "обещан" in eighth_lowered
    assert eighth.text.count("?") == 0

    ninth = engine.handle_turn("Кто со мной свяжется и когда ждать звонка?", eighth.state)

    assert ninth.extracted.facts["post_terminal_topic"] == "contact_question"
    assert ninth.frame.post_terminal_topic == "contact_question"
    assert ninth.actor_move.move_type == "post_terminal_answer"
    assert ninth.actor_move.direct_answer_topic == "post_terminal_contact"
    assert ninth.events == []
    assert ninth.text.count("?") == 0
