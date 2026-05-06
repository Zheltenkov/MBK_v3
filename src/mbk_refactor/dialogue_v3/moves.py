"""ActorMove planning without LLM ownership of business decisions."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from .case_frame import CaseFrame
from .constants import (
    ACTION_SCOPE_BY_ACTION_ID,
    AUTO_AUX,
    BFL_RD,
    BFL_RI,
    FRAUD_CHECK,
    HANDOFF_BFL_SPECIALIST,
    HANDOFF_EXPERT,
    MANUAL_REVIEW,
    MICRO,
    MORTGAGE_AUX,
    MORTGAGE_MAIN,
    OTHER,
    PTS,
    REPEAT_VISIT,
    UNSECURED,
)
from .route_session import RouteSession
from .state import DialogueV3State

MoveType = Literal[
    "ask_slot",
    "answer_then_ask_slot",
    "handle_offtopic_then_ask",
    "handle_objection_then_ask",
    "terminal_action",
    "security_action",
    "repeat_action",
    "no_solution_manual_review",
    "post_terminal_answer",
    "recommendation_offer",
]


@dataclass
class ActorMove:
    move_type: MoveType
    selected_route: str
    phase: str
    next_slot: str | None = None
    terminal_action: str | None = None
    direct_answer_topic: str | None = None
    client_concern: str | None = None
    off_topic_kind: str | None = None
    known_facts: dict[str, Any] = field(default_factory=dict)
    must_say: list[str] = field(default_factory=list)
    must_not_say: list[str] = field(default_factory=list)
    question_goal: str | None = None
    action_scope: str | None = None
    style_profile: str = "calm_manager"
    pending_route: str | None = None
    pending_terminal_action: str | None = None
    recommended_product: str | None = None
    recommendation_summary: str | None = None
    confirmation_question: str | None = None


def plan_actor_move(
    route_session: RouteSession,
    *,
    frame: CaseFrame,
    state: DialogueV3State | None = None,
) -> ActorMove:
    """Plan the next actor move from deterministic route/session state."""

    if route_session.selected_route == FRAUD_CHECK:
        return ActorMove(
            move_type="security_action",
            selected_route=route_session.selected_route,
            phase=route_session.phase,
            terminal_action=route_session.terminal_action,
            action_scope=terminal_action_scope(route_session.terminal_action),
            known_facts=build_terminal_known_facts(route_session.selected_route, state),
            must_say=["do_not_share_codes"],
        )

    if route_session.selected_route == REPEAT_VISIT:
        return ActorMove(
            move_type="repeat_action",
            selected_route=route_session.selected_route,
            phase=route_session.phase,
            terminal_action=route_session.terminal_action,
            action_scope=terminal_action_scope(route_session.terminal_action),
            known_facts=build_terminal_known_facts(route_session.selected_route, state),
        )

    if route_session.selected_route == OTHER or route_session.blockers:
        return ActorMove(
            move_type="no_solution_manual_review",
            selected_route=route_session.selected_route,
            phase=route_session.phase,
            terminal_action=route_session.terminal_action or MANUAL_REVIEW,
            client_concern=_client_concern(frame),
            known_facts=_with_session_reasons(
                build_terminal_known_facts(route_session.selected_route, state),
                route_session,
            ),
            action_scope=terminal_action_scope(route_session.terminal_action or MANUAL_REVIEW),
        )

    if frame.off_topic_kind and route_session.next_slot:
        return ActorMove(
            move_type="handle_offtopic_then_ask",
            selected_route=route_session.selected_route,
            phase=route_session.phase,
            next_slot=route_session.next_slot,
            off_topic_kind=frame.off_topic_kind,
            question_goal=route_session.next_slot,
            known_facts=build_grounding_known_facts(state),
        )

    concern = _client_concern(frame, state=state, next_slot=route_session.next_slot)
    if concern and route_session.next_slot:
        return ActorMove(
            move_type="handle_objection_then_ask",
            selected_route=route_session.selected_route,
            phase=route_session.phase,
            next_slot=route_session.next_slot,
            client_concern=concern,
            question_goal=route_session.next_slot,
            must_not_say=["no_risk_promises"],
            known_facts=build_grounding_known_facts(state),
        )

    if frame.direct_question and route_session.next_slot:
        return ActorMove(
            move_type="answer_then_ask_slot",
            selected_route=route_session.selected_route,
            phase=route_session.phase,
            next_slot=route_session.next_slot,
            direct_answer_topic="customer_question",
            question_goal=route_session.next_slot,
            known_facts=build_grounding_known_facts(state),
        )

    post_terminal_topic = _post_terminal_topic(route_session, frame, state)
    if post_terminal_topic:
        return ActorMove(
            move_type="post_terminal_answer",
            selected_route=route_session.selected_route,
            phase=route_session.phase,
            direct_answer_topic=post_terminal_topic,
            known_facts=build_terminal_known_facts(route_session.selected_route, state),
            action_scope=terminal_action_scope(route_session.terminal_action),
        )

    if route_session.next_slot:
        return ActorMove(
            move_type="ask_slot",
            selected_route=route_session.selected_route,
            phase=route_session.phase,
            next_slot=route_session.next_slot,
            question_goal=route_session.next_slot,
            known_facts=build_grounding_known_facts(state),
        )

    if route_session.terminal_action:
        if _requires_terminal_consent(route_session.terminal_action):
            return ActorMove(
                move_type="recommendation_offer",
                selected_route=route_session.selected_route,
                phase=route_session.phase,
                direct_answer_topic=_terminal_offer_direct_topic(frame),
                known_facts=_with_session_reasons(
                    build_terminal_known_facts(route_session.selected_route, state),
                    route_session,
                ),
                action_scope=terminal_action_scope(route_session.terminal_action),
                pending_route=route_session.selected_route,
                pending_terminal_action=route_session.terminal_action,
                recommended_product=_recommended_product_label(route_session.selected_route),
                recommendation_summary=_recommendation_summary(
                    route_session.selected_route,
                    state,
                    route_session,
                ),
                confirmation_question=_confirmation_question(route_session.terminal_action),
            )
        return ActorMove(
            move_type="terminal_action",
            selected_route=route_session.selected_route,
            phase=route_session.phase,
            terminal_action=route_session.terminal_action,
            known_facts=build_terminal_known_facts(route_session.selected_route, state),
            action_scope=terminal_action_scope(route_session.terminal_action),
        )

    return ActorMove(
        move_type="no_solution_manual_review",
        selected_route=route_session.selected_route,
        phase=route_session.phase,
        terminal_action=MANUAL_REVIEW,
        action_scope=terminal_action_scope(MANUAL_REVIEW),
    )


def _requires_terminal_consent(terminal_action: str | None) -> bool:
    return terminal_action in {HANDOFF_EXPERT, HANDOFF_BFL_SPECIALIST}


def _recommended_product_label(route: str) -> str:
    if route in {PTS, AUTO_AUX}:
        return "вариант под ПТС/авто"
    if route in {MORTGAGE_MAIN, MORTGAGE_AUX}:
        return "вариант под недвижимость"
    if route in {BFL_RD, BFL_RI}:
        return "долговой разбор"
    if route == UNSECURED:
        return "обычная заявка без залога"
    if route == MICRO:
        return "короткая заявка на небольшую сумму"
    return "профильный разбор"


def _confirmation_question(terminal_action: str | None) -> str:
    if terminal_action == HANDOFF_BFL_SPECIALIST:
        return "Передать вас специалисту по долгам, чтобы он проверил варианты?"
    return "Передать вас специалисту, чтобы он проверил детали?"


def _recommendation_summary(
    route: str,
    state: DialogueV3State | None,
    route_session: RouteSession | None = None,
) -> str | None:
    facts = build_terminal_known_facts(route, state)
    if not facts:
        return None
    risk_sentence = _route_check_sentence(route, route_session)
    if route in {PTS, AUTO_AUX}:
        vehicle_parts = _vehicle_summary_parts(facts)
        summary_parts: list[str] = []
        if vehicle_parts:
            summary_parts.append(f"По машине картина понятна: {', '.join(vehicle_parts)}")
        debt_parts = _debt_summary_parts(state)
        if debt_parts:
            summary_parts.append(f"По долгам - {', '.join(debt_parts)}")
        if risk_sentence:
            summary_parts.append(risk_sentence)
        return ". ".join(summary_parts) if summary_parts else None
    if route in {MORTGAGE_MAIN, MORTGAGE_AUX}:
        parts: list[str] = []
        if facts.get("property_type"):
            parts.append(_property_type_label(str(facts["property_type"])))
        if facts.get("property_region"):
            parts.append(str(facts["property_region"]))
        if facts.get("third_party_property_owner") is True:
            parts.append("собственник не клиент")
        elif facts.get("property_owner_known"):
            parts.append("собственник понятен")
        encumbrance = _property_encumbrance_phrase(facts)
        if encumbrance:
            parts.append(encumbrance)
        summary = f"По недвижимости картина понятна: {', '.join(parts)}" if parts else None
        if summary and risk_sentence:
            return f"{summary}. {risk_sentence}"
        if risk_sentence:
            return risk_sentence
        return summary
    if route in {BFL_RD, BFL_RI}:
        parts = _debt_summary_parts(state)
        if not parts:
            return None
        risk_parts = _bfl_risk_summary_parts(state)
        risk_sentence = f". Имущество нужно отдельно проверить; семейную нагрузку тоже: {', '.join(risk_parts)}" if risk_parts else ""
        return (
            f"По долгам картина понятна: {', '.join(parts)}{risk_sentence}. "
            "Это не обещание списания или реструктуризации; специалист проверит применимость"
        )
    return None


def _vehicle_summary_parts(facts: dict[str, Any]) -> list[str]:
    parts: list[str] = []
    car = facts.get("car")
    if car:
        if facts.get("car_year"):
            parts.append(f"{car} {facts['car_year']} года")
        else:
            parts.append(str(car))
    elif facts.get("car_year"):
        parts.append(f"авто {facts['car_year']} года")

    if facts.get("third_party_car_owner") is True or facts.get("car_owner") == "third_party":
        parts.append("оформлена не на вас")
    elif facts.get("car_owner") == "client":
        parts.append("оформлена на вас")
    elif facts.get("car_owner"):
        parts.append("собственник указан")

    restriction = _vehicle_restriction_phrase(facts)
    if restriction:
        parts.append(restriction)
    return parts


def _vehicle_restriction_phrase(facts: dict[str, Any]) -> str | None:
    positive: list[str] = []
    negative: list[str] = []

    _append_flag_phrase(facts, "car_loan_red_flag", "автокредит", "автокредита", positive, negative)
    _append_flag_phrase(facts, "car_pledge_red_flag", "залог", "залога", positive, negative)
    _append_flag_phrase(facts, "car_arrest_red_flag", "арест", "арестов", positive, negative)
    _append_flag_phrase(facts, "car_restriction_red_flag", "ограничения", "ограничений", positive, negative)

    if not positive and facts.get("car_in_pledge") is False and facts.get("car_arrest_or_restriction") is False:
        return "без автокредита, залога, арестов и ограничений"

    if not positive and not negative:
        if facts.get("car_in_pledge") is True:
            positive.append("залог или автокредит")
        if facts.get("car_arrest_or_restriction") is True:
            positive.append("арест или ограничения")

    parts: list[str] = []
    if negative:
        parts.append(f"без {_join_ru_list(negative)}")
    if positive:
        parts.append(f"есть {_join_ru_list(positive)}")
    return ", ".join(parts) if parts else None


def _route_check_sentence(route: str, route_session: RouteSession | None) -> str | None:
    if route_session is None:
        return None
    codes = list(route_session.blockers) + list(route_session.warnings)
    if not codes:
        return None

    labels = [
        label
        for code in codes
        if (label := _route_check_label(route, code)) is not None
    ]
    if not labels:
        return None

    if route in {PTS, AUTO_AUX}:
        return f"Нужно отдельно проверить по авто: {_join_ru_list(labels)}"
    if route in {MORTGAGE_MAIN, MORTGAGE_AUX}:
        return f"Нужно отдельно проверить по недвижимости: {_join_ru_list(labels)}"
    return f"Нужно отдельно проверить: {_join_ru_list(labels)}"


def _route_check_label(route: str, code: str) -> str | None:
    pts_labels = {
        "vehicle_no_car_red_flag": "наличие машины",
        "car_old_year": "возраст автомобиля",
        "third_party_car_owner": "участие собственника",
        "car_loan_red_flag": "автокредит",
        "car_pledge_red_flag": "залог",
        "car_arrest_red_flag": "арест",
        "car_restriction_red_flag": "ограничения",
    }
    mortgage_labels = {
        "unsupported_property_region": "регион объекта",
        "third_party_property_owner": "участие собственника",
        "property_mortgage": "ипотеку",
        "property_pledge_red_flag": "залог",
        "property_arrest_red_flag": "арест или ограничения",
        "municipal_housing_red_flag": "тип жилья",
        "property_share_red_flag": "долю",
        "property_room_red_flag": "комнату",
    }
    if route in {PTS, AUTO_AUX}:
        return pts_labels.get(code)
    if route in {MORTGAGE_MAIN, MORTGAGE_AUX}:
        return mortgage_labels.get(code)
    return None


def _append_flag_phrase(
    facts: dict[str, Any],
    key: str,
    positive_label: str,
    negative_label: str,
    positive: list[str],
    negative: list[str],
) -> None:
    value = facts.get(key)
    if value is True:
        positive.append(positive_label)
    elif value is False:
        negative.append(negative_label)


def _property_type_label(property_type: str) -> str:
    return {
        "apartment": "квартира",
        "house": "дом",
        "room": "комната",
        "share": "доля",
        "municipal_housing": "муниципальное жилье",
    }.get(property_type, property_type)


def _property_encumbrance_phrase(facts: dict[str, Any]) -> str | None:
    if facts.get("property_encumbrance_basic") is False:
        return "без ипотеки, залога, ареста и других обременений"
    encumbrance_type = facts.get("property_encumbrance_type")
    if encumbrance_type == "mortgage":
        return "есть ипотека"
    if encumbrance_type == "pledge":
        return "есть залог"
    if encumbrance_type == "arrest_or_restriction":
        return "есть арест или ограничения"
    if facts.get("property_encumbrance_red_flag") is True:
        return "есть обременение"
    return None


def _debt_summary_parts(state: DialogueV3State | None) -> list[str]:
    if state is None:
        return []
    parts: list[str] = []
    total_debt = state.fact_value("total_debt")
    monthly_payments = state.fact_value("monthly_payments")
    comfortable_payment = state.fact_value("comfortable_payment")
    official_income = state.fact_value("official_income")
    income_status = state.fact_value("income_status")
    has_arrears = state.fact_value("has_arrears")
    arrears_months = state.fact_value("arrears_months")
    has_mfo = state.fact_value("has_mfo")
    collector_pressure = state.fact_value("collector_pressure")
    if total_debt is not None:
        parts.append(f"долг около {_format_money(total_debt)}")
    if monthly_payments is not None:
        parts.append(f"платеж {_format_money(monthly_payments)} в месяц")
    if comfortable_payment is not None:
        parts.append(f"комфортный платеж {_format_money(comfortable_payment)}")
    if official_income is not None:
        parts.append(f"официальный доход около {_format_money(official_income)}")
    else:
        income_phrase = _income_status_phrase(income_status)
        if income_phrase:
            parts.append(income_phrase)
    if has_arrears is False:
        parts.append("просрочек нет")
    elif has_arrears is True:
        if arrears_months is not None:
            parts.append(f"просрочка около {_format_month_count(arrears_months)}")
        else:
            parts.append("есть просрочка")
    if has_mfo is True:
        parts.append("есть МФО")
    if collector_pressure is True:
        parts.append("есть давление коллекторов")
    return parts


def _bfl_risk_summary_parts(state: DialogueV3State | None) -> list[str]:
    if state is None:
        return []
    parts: list[str] = []
    property_type = state.fact_value("property_type")
    property_region = state.fact_value("property_region")
    if property_type or property_region:
        label = _property_type_label(str(property_type)) if property_type else "недвижимость"
        if property_region:
            label = f"{label} в {property_region}"
        if state.fact_value("is_only_housing") is True:
            label = f"{label}, единственное жилье"
        parts.append(label)
    if state.fact_value("dependent_relation") is not None or state.fact_value("dependents_count") is not None:
        relation = state.fact_value("dependent_relation")
        count = state.fact_value("dependents_count")
        if count is not None:
            parts.append(f"иждивенцев {count}")
        elif relation is not None:
            parts.append("есть иждивенцы")
    car = state.fact_value("raw_car_name")
    car_year = state.fact_value("car_year")
    if car:
        parts.append(f"авто {car}" + (f" {car_year} года" if car_year else ""))
    if state.fact_value("previous_debt_procedure") is False:
        parts.append("раньше процедур не было")
    elif state.fact_value("previous_debt_procedure") is True:
        parts.append("раньше была долговая процедура")
    return parts


def _format_money(value: Any) -> str:
    if not isinstance(value, (int, float)):
        return str(value)
    amount = int(value)
    if amount >= 1_000_000:
        millions = amount / 1_000_000
        if amount % 1_000_000 == 0:
            return f"{amount // 1_000_000} млн"
        return f"{millions:.1f}".replace(".", ",").rstrip("0").rstrip(",") + " млн"
    if amount >= 1_000 and amount % 1_000 == 0:
        thousands = amount // 1_000
        return f"{thousands} {_thousand_word(thousands)}"
    return f"{amount:,}".replace(",", " ")


def _income_status_phrase(income_status: Any) -> str | None:
    return {
        "stable": "доход официальный",
        "no_official_income": "официального дохода нет",
        "unstable": "доход нестабильный",
        "none": "дохода нет",
    }.get(income_status)


def _format_month_count(value: Any) -> str:
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    return f"{value} мес"


def _thousand_word(value: int) -> str:
    if 10 < value % 100 < 20:
        return "тысяч"
    if value % 10 == 1:
        return "тысяча"
    if value % 10 in {2, 3, 4}:
        return "тысячи"
    return "тысяч"


def _join_ru_list(items: list[str]) -> str:
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + " и " + items[-1]


def _client_concern(
    frame: CaseFrame,
    *,
    state: DialogueV3State | None = None,
    next_slot: str | None = None,
) -> str | None:
    if frame.property_risk_concern:
        return "property_risk"
    if frame.vehicle_requires_retention or frame.vehicle_refuses_transfer:
        if not _should_acknowledge_vehicle_retention(state=state, next_slot=next_slot):
            return None
        return "vehicle_retention"
    if frame.client_fears_bankruptcy:
        return "bankruptcy_fear"
    if frame.bankruptcy_clarification_question:
        return "bankruptcy_clarification_question"
    if frame.mfo_rating_concern:
        return "mfo_rating_concern"
    if frame.credit_bureau_objection:
        return "credit_bureau_objection"
    return None


def _should_acknowledge_vehicle_retention(
    *,
    state: DialogueV3State | None,
    next_slot: str | None,
) -> bool:
    """Avoid repeating the same vehicle-retention acknowledgement on every car slot."""

    if state is None:
        return True
    if next_slot in {"car_year", "car_owner", "car_pledge_or_restrictions"}:
        return "car_brand_model" not in state.asked_slots
    return True


def terminal_action_scope(terminal_action: str | None) -> str | None:
    """Describe an already selected terminal action for writer wording only."""

    if not terminal_action:
        return None
    return ACTION_SCOPE_BY_ACTION_ID.get(terminal_action)


POST_TERMINAL_DIRECT_TOPIC_BY_FRAME_TOPIC = {
    "next_step": "post_terminal_next_step",
    "bankruptcy_clarification": "bankruptcy_clarification",
    "contact_question": "post_terminal_contact",
}


def _post_terminal_topic(
    route_session: RouteSession,
    frame: CaseFrame,
    state: DialogueV3State | None,
) -> str | None:
    """Return a clarification topic after the already emitted terminal action."""

    if state is None or not route_session.terminal_action:
        return None
    action_key = f"{route_session.selected_route}:{route_session.terminal_action}"
    if action_key not in state.emitted_terminal_actions:
        return None

    return POST_TERMINAL_DIRECT_TOPIC_BY_FRAME_TOPIC.get(frame.post_terminal_topic)


def _terminal_offer_direct_topic(frame: CaseFrame) -> str | None:
    if frame.bankruptcy_clarification_question:
        return "bankruptcy_clarification"
    return None


def build_terminal_known_facts(
    route: str,
    state: DialogueV3State | None,
) -> dict[str, Any]:
    """Build compact terminal writer facts without exposing raw mutable state."""

    if state is None:
        return {}

    if route in {PTS, AUTO_AUX}:
        return _known(
            state,
            {
                "raw_car_name": "car",
                "car_brand": "car_brand",
                "car_model": "car_model",
                "car_year": "car_year",
                "car_owner": "car_owner",
                "car_in_pledge": "car_in_pledge",
                "car_arrest_or_restriction": "car_arrest_or_restriction",
                "car_old_year": "car_old_year",
                "car_year_red_flag": "car_year_red_flag",
                "third_party_car_owner": "third_party_car_owner",
                "car_owner_red_flag": "car_owner_red_flag",
                "car_loan_red_flag": "car_loan_red_flag",
                "car_pledge_red_flag": "car_pledge_red_flag",
                "car_arrest_red_flag": "car_arrest_red_flag",
                "car_restriction_red_flag": "car_restriction_red_flag",
            },
        )
    if route in {MORTGAGE_MAIN, MORTGAGE_AUX}:
        return _known(
            state,
            {
                "property_type": "property_type",
                "property_region": "property_region",
                "property_owner": "property_owner_or_ownership",
                "property_owner_known": "property_owner_known",
                "property_encumbrance": "property_encumbrance_basic",
                "property_encumbrance_type": "property_encumbrance_type",
                "property_region_supported": "property_region_supported",
                "property_region_red_flag": "property_region_red_flag",
                "third_party_property_owner": "third_party_property_owner",
                "property_owner_red_flag": "property_owner_red_flag",
                "property_encumbrance_red_flag": "property_encumbrance_red_flag",
                "property_pledge_red_flag": "property_pledge_red_flag",
                "property_arrest_red_flag": "property_arrest_red_flag",
                "municipal_housing_red_flag": "municipal_housing_red_flag",
                "property_share_red_flag": "property_share_red_flag",
                "property_room_red_flag": "property_room_red_flag",
                "property_municipal_housing": "property_municipal_housing",
                "property_share": "property_share",
                "property_arrest": "property_arrest",
                "property_pledge": "property_pledge",
                "property_object_red_flag": "property_object_red_flag",
            },
        )
    if route in {BFL_RD, BFL_RI}:
        return _known(
            state,
            {
                "total_debt": "total_debt",
                "monthly_payments": "monthly_payments",
                "income_status": "income_status",
                "official_income": "official_income",
                "comfortable_payment": "comfortable_payment",
                "has_arrears": "has_arrears",
                "arrears_months": "delinquency_context",
                "has_mfo": "has_mfo",
                "collector_pressure": "collector_pressure",
                "loan_types": "loan_types",
                "client_wants_to_pay": "client_wants_to_pay",
                "property_type": "property_type",
                "property_region": "property_region",
                "property_owner": "property_owner",
                "property_owner_known": "property_owner_known",
                "property_encumbrance": "property_encumbrance_basic",
                "is_only_housing": "is_only_housing",
                "raw_car_name": "car",
                "car_year": "car_year",
                "dependents_count": "dependents_count",
                "dependent_relation": "dependent_relation",
                "previous_debt_procedure": "previous_debt_procedure",
            },
        )
    if route in {UNSECURED, MICRO}:
        return _known(
            state,
            {
                "desired_amount": "desired_amount_or_total_debt",
                "total_debt": "desired_amount_or_total_debt",
                "income_status": "income_status",
                "monthly_payments": "monthly_payments",
                "has_arrears": "delinquency_context",
                "arrears_months": "delinquency_context",
                "urgency": "urgency",
            },
        )
    if route == FRAUD_CHECK:
        return _known(state, {"service_signal": "service_reason"})
    if route == REPEAT_VISIT:
        return _known(state, {"service_signal": "repeat_reason"})
    return {}


def build_grounding_known_facts(state: DialogueV3State | None) -> dict[str, Any]:
    """Build compact numeric/object grounding facts for non-terminal writer moves."""

    if state is None:
        return {}
    car_brand_model = (
        state.fact_value("car_brand_model")
        or state.fact_value("raw_car_name")
        or _join_present(
            state.fact_value("car_brand"),
            state.fact_value("car_model"),
        )
    )
    return {
        "total_debt": state.fact_value("total_debt"),
        "monthly_payments": state.fact_value("monthly_payments"),
        "comfortable_payment": state.fact_value("comfortable_payment"),
        "official_income": state.fact_value("official_income"),
        "other_income": state.fact_value("other_income"),
        "income_status": state.fact_value("income_status"),
        "desired_amount": state.fact_value("desired_amount"),
        "property_type": state.fact_value("property_type"),
        "property_region": state.fact_value("property_region"),
        "car_brand_model": car_brand_model,
        "car_year": state.fact_value("car_year"),
    }


def _join_present(*values: Any) -> str | None:
    parts = [str(value).strip() for value in values if value not in (None, "")]
    return " ".join(parts) if parts else None


def _known(state: DialogueV3State, mapping: dict[str, str]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for fact_key, output_key in mapping.items():
        value = state.fact_value(fact_key)
        if value is not None:
            result[output_key] = value
    return result


def _with_session_reasons(facts: dict[str, Any], route_session: RouteSession) -> dict[str, Any]:
    result = dict(facts)
    if route_session.blockers:
        result["blockers"] = list(route_session.blockers)
    if route_session.warnings:
        result["warnings"] = list(route_session.warnings)
    if route_session.risk_factors:
        result["risk_factors"] = list(route_session.risk_factors)
    if route_session.reason_codes:
        result["reason_codes"] = list(route_session.reason_codes)
    return result
