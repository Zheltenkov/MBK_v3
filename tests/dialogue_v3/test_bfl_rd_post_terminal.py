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
    assert sixth.route_session.terminal_action is None
    assert sixth.route_session.next_slot == "bfl_property_context"
    assert sixth.events == []
    assert sixth.state.fact_value("total_debt") == 1_450_000
    assert "недвижимость" in lowered
    assert sixth.text.count("?") == 1

    seventh = engine.handle_turn(
        "Квартира в Москве, я собственник, единственное жилье, ипотеки и арестов нет.",
        sixth.state,
    )
    assert seventh.route_session.next_slot == "bfl_vehicle_context"

    eighth = engine.handle_turn("Kia Rio 2019 года.", seventh.state)
    assert eighth.route_session.next_slot == "previous_debt_procedure"

    ninth = engine.handle_turn("Раньше банкротства или реструктуризации не было.", eighth.state)
    ninth_lowered = ninth.text.lower()
    assert ninth.route_session.selected_route == BFL_RD
    assert ninth.route_session.terminal_action == HANDOFF_BFL_SPECIALIST
    assert ninth.actor_move.move_type == "recommendation_offer"
    assert ninth.actor_move.pending_terminal_action == HANDOFF_BFL_SPECIALIST
    assert ninth.events == []
    assert "передать вас специалисту по долгам" in ninth_lowered
    assert "платеж" in ninth_lowered or "нагруз" in ninth_lowered
    assert "не обещаю" in ninth_lowered
    assert ninth.text.count("?") == 1

    tenth = engine.handle_turn("Да, передавайте.", ninth.state)
    assert [event.action_id for event in tenth.events] == [HANDOFF_BFL_SPECIALIST]
    assert tenth.state.pending_terminal_action is None

    eleventh = engine.handle_turn("Хорошо, а что дальше?", tenth.state)
    eleventh_lowered = eleventh.text.lower()

    assert eleventh.extracted.facts["post_terminal_topic"] == "next_step"
    assert eleventh.frame.post_terminal_topic == "next_step"
    assert eleventh.route_session.selected_route == BFL_RD
    assert eleventh.actor_move.move_type == "post_terminal_answer"
    assert eleventh.actor_move.direct_answer_topic == "post_terminal_next_step"
    assert eleventh.events == []
    assert eleventh.route_session.selected_route != REPEAT_VISIT
    assert "специалист по долгам" in eleventh_lowered
    assert eleventh.text.count("?") == 0

    twelfth = engine.handle_turn(
        "Это банкротство или можно без него?",
        eleventh.state,
    )
    twelfth_lowered = twelfth.text.lower()

    assert twelfth.extracted.facts["post_terminal_topic"] == "bankruptcy_clarification"
    assert twelfth.frame.post_terminal_topic == "bankruptcy_clarification"
    assert twelfth.actor_move.move_type == "post_terminal_answer"
    assert twelfth.actor_move.direct_answer_topic == "bankruptcy_clarification"
    assert twelfth.events == []
    assert "не обязательно банкротство" in twelfth_lowered
    assert "посильный график" in twelfth_lowered or "реструктуризац" in twelfth_lowered
    assert "обещан" in twelfth_lowered
    assert twelfth.text.count("?") == 0

    thirteenth = engine.handle_turn("Кто со мной свяжется и когда ждать звонка?", twelfth.state)

    assert thirteenth.extracted.facts["post_terminal_topic"] == "contact_question"
    assert thirteenth.frame.post_terminal_topic == "contact_question"
    assert thirteenth.actor_move.move_type == "post_terminal_answer"
    assert thirteenth.actor_move.direct_answer_topic == "post_terminal_contact"
    assert thirteenth.events == []
    assert thirteenth.text.count("?") == 0
