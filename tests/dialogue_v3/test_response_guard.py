from __future__ import annotations

import pytest

from mbk_refactor.dialogue_v3.actions import ActionEvent
from mbk_refactor.dialogue_v3.constants import HANDOFF_EXPERT, PTS, SELF_SERVE_LINKS_3, UNSECURED
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


@pytest.mark.parametrize(
    "claim",
    [
        "Имущество точно не затронут.",
        "Квартиру точно сохраните.",
        "Машину точно не затронут.",
        "Долги точно спишут.",
        "Реструктуризацию точно утвердят.",
        "Одобрение гарантировано.",
    ],
)
def test_guard_rejects_bfl_asset_safety_guarantees(claim: str) -> None:
    move = ActorMove(
        move_type="recommendation_offer",
        selected_route="BFL_RD",
        phase="READY_FOR_TERMINAL",
        pending_route="BFL_RD",
        pending_terminal_action="HANDOFF_BFL_SPECIALIST",
    )

    validation = validate_text(claim, move)

    assert not validation.accepted
    assert "forbidden_claim" in validation.issue_codes


def test_guard_rejects_handoff_language_without_terminal_action() -> None:
    move = ActorMove(move_type="ask_slot", selected_route="PTS", phase="COLLECTING", next_slot="car_year")

    validation = validate_text("Передам специалисту, а пока какого года автомобиль?", move)

    assert not validation.accepted
    assert "handoff_without_action" in validation.issue_codes


def test_guard_allows_recommendation_offer_consent_question_without_event() -> None:
    move = ActorMove(
        move_type="recommendation_offer",
        selected_route="PTS",
        phase="READY_FOR_TERMINAL",
        pending_route="PTS",
        pending_terminal_action="HANDOFF_EXPERT",
    )
    output = ActorWriterOutput(
        body="По машине картина понятна. Условия заранее не обещаю.",
        followup_question="Передать вас специалисту?",
    )

    validation = ResponseGuard().validate(output=output, move=move, events=[])

    assert validation.accepted


def test_guard_rejects_followup_question_for_different_vehicle_slot() -> None:
    move = ActorMove(
        move_type="ask_slot",
        selected_route="PTS",
        phase="COLLECTING",
        next_slot="car_brand_model",
        question_goal="car_brand_model",
    )
    output = ActorWriterOutput(followup_question="Какого года автомобиль?")

    validation = ResponseGuard().validate(output=output, move=move)

    assert not validation.accepted
    assert "question_goal_mismatch" in validation.issue_codes


def test_guard_rejects_income_amount_invented_from_monthly_payment() -> None:
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
    output = ActorWriterOutput(
        body="58 тысяч в месяц - это важная цифра.",
        followup_question="Доход у вас в месяц примерно 58 тысяч - он официальный или нет?",
    )

    validation = ResponseGuard().validate(output=output, move=move)

    assert not validation.accepted
    assert "income_amount_invented_from_monthly_payment" in validation.issue_codes


@pytest.mark.parametrize(
    ("slot", "question"),
    [
        ("total_debt", "Сколько сейчас всего задолженности по картам и кредитам?"),
        ("monthly_payments", "Сколько сейчас уходит в месяц на платежи?"),
        ("income_status", "Какой у вас сейчас доход и он официальный?"),
        ("comfortable_payment", "Какой платеж был бы комфортным?"),
        ("delinquency_context", "Просрочки уже есть или пока платите без задержек?"),
        ("collateral_preference", "Можно ли рассмотреть авто или недвижимость?"),
        ("car_brand_model", "Какая у вас машина: марка и модель?"),
        ("car_year", "Какого года автомобиль?"),
        ("car_owner", "На кого оформлен автомобиль?"),
        ("car_pledge_or_restrictions", "Автомобиль в залоге, автокредите, аресте или с ограничениями?"),
        ("property_type", "Это квартира, дом или другой объект?"),
        ("property_owner_or_ownership", "На кого оформлена недвижимость?"),
        ("property_encumbrance_basic", "Есть ли ипотека, залог, арест или другие обременения?"),
        ("previous_debt_procedure", "Раньше были банкротство или реструктуризация долгов?"),
    ],
)
def test_guard_accepts_followup_question_matching_question_goal(slot: str, question: str) -> None:
    move = ActorMove(
        move_type="ask_slot",
        selected_route="DISCOVERY",
        phase="COLLECTING",
        next_slot=slot,
        question_goal=slot,
    )
    output = ActorWriterOutput(followup_question=question)

    validation = ResponseGuard().validate(output=output, move=move)

    assert validation.accepted


@pytest.mark.parametrize(
    "slot",
    [
        "total_debt",
        "monthly_payments",
        "income_status",
        "comfortable_payment",
        "delinquency_context",
        "collateral_preference",
        "car_brand_model",
        "car_year",
        "car_owner",
        "car_pledge_or_restrictions",
        "property_type",
        "property_owner_or_ownership",
        "property_encumbrance_basic",
        "previous_debt_procedure",
    ],
)
def test_guard_rejects_followup_question_not_matching_question_goal(slot: str) -> None:
    move = ActorMove(
        move_type="ask_slot",
        selected_route="DISCOVERY",
        phase="COLLECTING",
        next_slot=slot,
        question_goal=slot,
    )
    output = ActorWriterOutput(followup_question="Какого года автомобиль?")

    validation = ResponseGuard().validate(output=output, move=move)

    if slot == "car_year":
        assert validation.accepted
    else:
        assert not validation.accepted
        assert "question_goal_mismatch" in validation.issue_codes


def test_guard_rejects_previous_debt_procedure_as_vehicle_fact() -> None:
    move = ActorMove(
        move_type="ask_slot",
        selected_route="BFL_RD",
        phase="COLLECTING_PRIMARY_GATES",
        next_slot="previous_debt_procedure",
        question_goal="previous_debt_procedure",
        known_facts={"raw_car_name": "Volkswagen Polo", "car_year": 2016},
    )
    output = ActorWriterOutput(
        body=(
            "Отлично, авто уже понятно: Volkswagen Polo 2016 года. "
            "Остался один уточняющий факт по машине."
        ),
        followup_question="Были у вас раньше банкротство или реструктуризация долгов?",
    )

    validation = ResponseGuard().validate(output=output, move=move)

    assert not validation.accepted
    assert "previous_debt_procedure_linked_to_vehicle_fact" in validation.issue_codes


def test_guard_allows_previous_debt_procedure_with_clear_transition() -> None:
    move = ActorMove(
        move_type="ask_slot",
        selected_route="BFL_RD",
        phase="COLLECTING_PRIMARY_GATES",
        next_slot="previous_debt_procedure",
        question_goal="previous_debt_procedure",
        known_facts={"raw_car_name": "Volkswagen Polo", "car_year": 2016},
    )
    output = ActorWriterOutput(
        body="По машине понятно. Остался юридический момент по прошлым процедурам.",
        followup_question="Были у вас раньше банкротство или реструктуризация долгов?",
    )

    validation = ResponseGuard().validate(output=output, move=move)

    assert validation.accepted


def test_guard_allows_post_terminal_specialist_reference_without_new_action_language() -> None:
    move = ActorMove(
        move_type="post_terminal_answer",
        selected_route="BFL_RD",
        phase="READY_FOR_TERMINAL",
        action_scope="bfl_handoff",
    )

    validation = validate_text(
        "Вы уже перешли к специалисту по долгам. Те же вопросы заново проходить не нужно.",
        move,
    )
    fresh_handoff = validate_text("Передам специалисту по долгам еще раз.", move)

    assert validation.accepted
    assert not fresh_handoff.accepted
    assert "handoff_without_action" in fresh_handoff.issue_codes


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


def test_guard_rejects_handoff_expert_terminal_without_specialist_next_step() -> None:
    move = ActorMove(
        move_type="terminal_action",
        selected_route="MORTGAGE_MAIN",
        phase="READY_FOR_TERMINAL",
        terminal_action="HANDOFF_EXPERT",
    )
    output = ActorWriterOutput(
        body="Ситуация по квартире уже понятна. Для такого случая дальше нужен профильный разбор без обещаний заранее."
    )

    validation = ResponseGuard().validate(output=output, move=move)

    assert not validation.accepted
    assert "handoff_next_step_missing" in validation.issue_codes


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


def test_guard_rejects_self_serve_text_with_specialist_handoff_language() -> None:
    move = ActorMove(
        move_type="terminal_action",
        selected_route=UNSECURED,
        phase="READY_FOR_TERMINAL",
        terminal_action=SELF_SERVE_LINKS_3,
    )
    output = ActorWriterOutput(body="Передам специалисту, он посмотрит машину и документы.")
    events = [ActionEvent(action_id=SELF_SERVE_LINKS_3, selected_route=UNSECURED, payload={})]

    validation = ResponseGuard().validate(output=output, move=move, events=events)

    assert not validation.accepted
    assert "self_serve_handoff_language" in validation.issue_codes
    assert "unsecured_vehicle_handoff_language" in validation.issue_codes


def test_guard_rejects_unsecured_vehicle_specific_specialist_check() -> None:
    move = ActorMove(
        move_type="ask_slot",
        selected_route=UNSECURED,
        phase="COLLECTING",
        next_slot="income_status",
    )
    output = ActorWriterOutput(body="Профильный специалист посмотрит авто, а пока уточним доход.")

    validation = ResponseGuard().validate(output=output, move=move)

    assert not validation.accepted
    assert "unsecured_vehicle_handoff_language" in validation.issue_codes


def test_guard_allows_pts_recommendation_offer_vehicle_handoff_question() -> None:
    move = ActorMove(
        move_type="recommendation_offer",
        selected_route=PTS,
        phase="READY_FOR_TERMINAL",
        pending_route=PTS,
        pending_terminal_action=HANDOFF_EXPERT,
    )
    output = ActorWriterOutput(
        body="По машине картина понятна.",
        followup_question="Передать вас специалисту, чтобы он проверил авто и документы?",
    )

    validation = ResponseGuard().validate(output=output, move=move, events=[])

    assert validation.accepted


def test_guard_rejects_vehicle_handoff_language_when_backend_route_is_not_pts() -> None:
    move = ActorMove(
        move_type="terminal_action",
        selected_route=UNSECURED,
        phase="READY_FOR_TERMINAL",
        terminal_action=HANDOFF_EXPERT,
    )
    output = ActorWriterOutput(body="Передаю специалисту: он посмотрит машину и документы.")
    events = [ActionEvent(action_id=HANDOFF_EXPERT, selected_route=UNSECURED, payload={})]

    validation = ResponseGuard().validate(output=output, move=move, events=events)

    assert not validation.accepted
    assert "vehicle_handoff_backend_mismatch" in validation.issue_codes


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
