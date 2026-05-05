"""Run fixed dialogue_v3 smoke scenarios without UI.

This script is an external verification tool. It does not select routes,
terminal actions, or business moves; it only runs DialogueV3Engine and reports
observed invariants.
"""

from __future__ import annotations

import argparse
import difflib
import json
import re
import sys
from dataclasses import asdict, dataclass, is_dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

ROOT_DIR = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from mbk_refactor.dialogue_v3 import ActorWriter  # noqa: E402
from mbk_refactor.dialogue_v3.actor_prompts import FEW_SHOT_EXAMPLES  # noqa: E402
from mbk_refactor.dialogue_v3.constants import (  # noqa: E402
    BFL_RD,
    BFL_RI,
    DISCOVERY,
    FRAUD_CHECK,
    HANDOFF_BFL_SPECIALIST,
    HANDOFF_EXPERT,
    MANUAL_REVIEW,
    MORTGAGE_AUX,
    MORTGAGE_MAIN,
    OTHER,
    PTS,
    REPEAT_HANDOFF,
    REPEAT_VISIT,
    SECURITY_FLOW,
    SELF_SERVE_LINKS_3,
)
from mbk_refactor.dialogue_v3.engine import DialogueV3Engine, DialogueV3TurnResult  # noqa: E402
from mbk_refactor.dialogue_v3.llm_client import build_optional_llm_client  # noqa: E402
from mbk_refactor.dialogue_v3.response_guard import HANDOFF_LANGUAGE  # noqa: E402
from mbk_refactor.dialogue_v3.state import DialogueV3State  # noqa: E402
from mbk_refactor.dialogue_v3.ui_form_schema import public_form_to_facts  # noqa: E402

WriterMode = Literal["deterministic", "llm", "llm_guarded"]


@dataclass(frozen=True)
class SmokeScenario:
    scenario_id: str
    public_form: dict[str, Any]
    turns: list[str]
    expected_route: str
    expected_terminal_action: str | None = None
    forbidden_routes: tuple[str, ...] = ()
    require_no_terminal: bool = False


SMOKE_SCENARIOS: list[SmokeScenario] = [
    SmokeScenario(
        scenario_id="pts_002_resistant_driver",
        public_form={
            "ФИО": "Денис Соколов",
            "Телефон": "79040001122",
            "Сумма": "650000 ₽",
            "Есть текущие кредиты": "да",
            "Есть авто": "да",
        },
        turns=["Хочу закрыть карты, но машину отдавать не буду, она для работы."],
        expected_route=PTS,
    ),
    SmokeScenario(
        scenario_id="pts_003_terse_family",
        public_form={
            "Сумма": "510000",
            "Есть авто": "да",
            "Есть текущие кредиты": "да",
        },
        turns=["Лада Веста 2018, я собственник, не в залоге и ограничений нет."],
        expected_route=PTS,
        expected_terminal_action=HANDOFF_EXPERT,
    ),
    SmokeScenario(
        scenario_id="mortgage_main_001_calm_family",
        public_form={
            "Сумма": "2800000",
            "Есть недвижимость": "да",
            "Регион недвижимости": "Москва",
        },
        turns=["Квартира в Москве, я собственник, без обременений."],
        expected_route=MORTGAGE_MAIN,
        expected_terminal_action=HANDOFF_EXPERT,
    ),
    SmokeScenario(
        scenario_id="mortgage_main_003_anxious_homeowner",
        public_form={
            "Сумма": "2500000",
            "Есть недвижимость": "да",
        },
        turns=["Квартира есть, но я боюсь потерять жилье."],
        expected_route=MORTGAGE_AUX,
    ),
    SmokeScenario(
        scenario_id="mortgage_main_005_region_not_supported",
        public_form={
            "Сумма": "2200000",
            "Есть недвижимость": "да",
            "Регион недвижимости": "Новосибирск",
        },
        turns=["Дом, я собственник, без обременений."],
        expected_route=MORTGAGE_AUX,
        expected_terminal_action=SELF_SERVE_LINKS_3,
    ),
    SmokeScenario(
        scenario_id="bfl_rd_001_stable_income",
        public_form={"Есть текущие кредиты": "да"},
        turns=[
            "Долг 1.7 млн, плачу 78 тыс, доход 125 тыс, комфортно 35 тыс, просрочка 1 месяц. Банкротство не хочу, хочу платить."
        ],
        expected_route=BFL_RD,
        expected_terminal_action=HANDOFF_BFL_SPECIALIST,
    ),
    SmokeScenario(
        scenario_id="bfl_ri_001_mfo_pressure",
        public_form={"Есть текущие кредиты": "да"},
        turns=["МФО, коллекторы, просрочка 3 месяца, долги 2 млн, дохода стабильного нет."],
        expected_route=BFL_RI,
    ),
    SmokeScenario(
        scenario_id="other_003_conflicting_constraints",
        public_form={
            "Есть текущие кредиты": "да",
            "Есть авто": "нет",
            "Есть недвижимость": "нет",
        },
        turns=["Суды не рассматриваю, никаких процедур, залог не хочу, дохода нет."],
        expected_route=OTHER,
        expected_terminal_action=MANUAL_REVIEW,
    ),
    SmokeScenario(
        scenario_id="fraud_check_001_sms_code",
        public_form={},
        turns=["Мне позвонили от вашего имени и попросили код из СМС."],
        expected_route=FRAUD_CHECK,
        expected_terminal_action=SECURITY_FLOW,
    ),
    SmokeScenario(
        scenario_id="repeat_visit_002_no_answer_from_manager",
        public_form={},
        turns=["Я уже переходил в чат, но мне не ответили."],
        expected_route=REPEAT_VISIT,
        expected_terminal_action=REPEAT_HANDOFF,
    ),
    SmokeScenario(
        scenario_id="offtopic_001_python",
        public_form={"Есть текущие кредиты": "да"},
        turns=[
            "Долги 1 млн, плачу 50 тыс в месяц.",
            "Напиши функцию сортировки пузырьком на Python.",
        ],
        expected_route=DISCOVERY,
    ),
    SmokeScenario(
        scenario_id="generic_money_to_debt_funnel",
        public_form={
            "Сумма": "645467",
            "Есть текущие кредиты": "да",
            "Есть авто": "да",
            "Есть недвижимость": "да",
        },
        turns=["Хочу взять денег"],
        expected_route=DISCOVERY,
    ),
    SmokeScenario(
        scenario_id="generic_new_money_no_terminal",
        public_form={
            "Есть текущие кредиты": "да",
            "Есть авто": "да",
        },
        turns=["Хочу взять денег"],
        expected_route=DISCOVERY,
        require_no_terminal=True,
    ),
    SmokeScenario(
        scenario_id="repair_car_no_pts_without_explicit_intent",
        public_form={
            "Сумма": "680000",
            "Есть текущие кредиты": "да",
            "Есть авто": "да",
        },
        turns=["Нужны деньги на ремонт машины"],
        expected_route=DISCOVERY,
        forbidden_routes=(PTS, MORTGAGE_MAIN, MORTGAGE_AUX, BFL_RD, BFL_RI),
        require_no_terminal=True,
    ),
    SmokeScenario(
        scenario_id="cards_repair_ambiguous_no_mortgage",
        public_form={
            "Сумма": "645467",
            "Есть текущие кредиты": "да",
            "Есть авто": "да",
            "Есть недвижимость": "да",
        },
        turns=["Хочу закрыть карты и немного оставить на ремонт"],
        expected_route=DISCOVERY,
    ),
    SmokeScenario(
        scenario_id="s02_clean_cards_repair_no_bfl_before_pts",
        public_form={
            "Сумма": "680000",
            "Есть текущие кредиты": "да",
            "Есть авто": "да",
            "Тип занятости": "найм",
        },
        turns=[
            "Хочу закрыть две кредитные карты и немного оставить на ремонт машины.",
            "Около 520 тысяч по двум кредитным картам.",
            "Примерно 34 тысячи в месяц.",
            "Официально работаю по найму, доход примерно 115 тысяч в месяц.",
            "Просрочек нет, всё плачу по графику. Комфортно было бы где-то 25-28 тысяч в месяц.",
        ],
        expected_route=DISCOVERY,
        forbidden_routes=(BFL_RD, BFL_RI, PTS, MORTGAGE_MAIN, MORTGAGE_AUX),
        require_no_terminal=True,
    ),
    SmokeScenario(
        scenario_id="bfl_rd_multiturn_wants_to_pay",
        public_form={"Есть текущие кредиты": "да"},
        turns=[
            "Хочу взять денег",
            "Хочу закрыть долги, платежи тяжело тянуть",
            "Около 1.7 млн",
            "78 тысяч в месяц",
            "Доход 125 тысяч, работаю официально",
            "35 тысяч было бы нормально",
            "Просрочка около месяца. Банкротство не хочу, хочу платить",
        ],
        expected_route=BFL_RD,
        expected_terminal_action=HANDOFF_BFL_SPECIALIST,
    ),
    SmokeScenario(
        scenario_id="bfl_ri_multiturn_mfo_collectors",
        public_form={"Есть текущие кредиты": "да"},
        turns=[
            "Хочу закрыть долги",
            "Около 2 млн, много МФО",
            "Дохода стабильного нет, просрочка 3 месяца, коллекторы звонят",
        ],
        expected_route=BFL_RI,
        expected_terminal_action=HANDOFF_BFL_SPECIALIST,
    ),
    SmokeScenario(
        scenario_id="explicit_pts_retention",
        public_form={
            "Есть текущие кредиты": "да",
            "Есть авто": "да",
            "Есть недвижимость": "да",
        },
        turns=["Хочу закрыть долги, но машину отдавать не буду, она каждый день нужна"],
        expected_route=PTS,
    ),
    SmokeScenario(
        scenario_id="explicit_mortgage",
        public_form={"Сумма": "2000000", "Есть недвижимость": "да"},
        turns=["Хочу рассмотреть под квартиру"],
        expected_route=MORTGAGE_AUX,
    ),
    SmokeScenario(
        scenario_id="fraud_sms_code",
        public_form={"Сумма": "600000", "Есть недвижимость": "да"},
        turns=["Мне позвонили от вашего имени и попросили код из СМС"],
        expected_route=FRAUD_CHECK,
        expected_terminal_action=SECURITY_FLOW,
    ),
]

MIN_FEW_SHOT_BODY_COPY_LENGTH = 40
FEW_SHOT_BODY_COPY_RATIO = 0.88
FEW_SHOT_GOOD_BODIES: tuple[str, ...] | None = None


def main() -> int:
    args = _parse_args()
    llm_client, llm_status = (None, None)
    if args.writer_mode in {"llm", "llm_guarded"}:
        llm_client, llm_status = build_optional_llm_client(args.model_name)
    scenario_results = [
        _run_scenario(scenario, writer_mode=args.writer_mode, llm_client=llm_client)
        for scenario in SMOKE_SCENARIOS
    ]
    summary = _build_summary(scenario_results)

    artifact_path = _write_artifact(
        payload={
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "writer_mode": args.writer_mode,
            "model_name": args.model_name,
            "llm_client": _to_plain(llm_status) if llm_status else {"available": False, "reason": "not requested"},
            "summary": summary,
            "scenarios": scenario_results,
        },
        artifact_dir=Path(args.artifact_dir),
    )
    output = {
        "writer_mode": args.writer_mode,
        "model_name": args.model_name,
        "llm_client": _to_plain(llm_status) if llm_status else {"available": False, "reason": "not requested"},
        "artifact_path": str(artifact_path),
        **summary,
        "scenarios": scenario_results,
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))

    if args.fail_on_violations and not summary["stop_criteria_ok"]:
        return 1
    return 0


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run dialogue_v3 smoke scenarios.")
    parser.add_argument(
        "--writer-mode",
        choices=["deterministic", "llm", "llm_guarded"],
        default="deterministic",
        help="Writer mode. Deterministic is the default and does not call an LLM.",
    )
    parser.add_argument(
        "--artifact-dir",
        default=str(ROOT_DIR / "artifacts"),
        help="Directory for detailed smoke trace JSON.",
    )
    parser.add_argument(
        "--model-name",
        default="gpt-4.1-mini",
        help="Model name for optional LLM writer modes.",
    )
    parser.add_argument(
        "--fail-on-violations",
        action="store_true",
        help="Exit with code 1 if stop criteria are not met.",
    )
    return parser.parse_args()


def _run_scenario(
    scenario: SmokeScenario,
    *,
    writer_mode: WriterMode,
    llm_client: Any | None,
) -> dict[str, Any]:
    engine = DialogueV3Engine(
        writer_mode=writer_mode,
        actor_writer=ActorWriter(mode=writer_mode, llm_client=llm_client),
    )
    state = DialogueV3State(session_id=f"smoke:{scenario.scenario_id}")
    state.merge_facts(_normalize_public_form(scenario.public_form), source="form")

    turns: list[dict[str, Any]] = []
    violations: list[str] = []
    final_result: DialogueV3TurnResult | None = None

    for user_text in scenario.turns:
        try:
            final_result = engine.handle_turn(user_text, state)
        except Exception as exc:
            violations.append("runtime_error")
            turns.append({"user_text": user_text, "error": str(exc)})
            break

        turn_payload = _turn_result_to_payload(final_result, writer_mode=writer_mode)
        turns.append(turn_payload)
        violations.extend(_turn_violations(turn_payload, scenario))
        state = final_result.state

    final_route = final_result.route_session.selected_route if final_result else None
    terminal_action = final_result.route_session.terminal_action if final_result else None

    route_ok = final_route == scenario.expected_route
    if not route_ok:
        violations.append("wrong_route")

    terminal_ok = (
        scenario.expected_terminal_action is None
        or terminal_action == scenario.expected_terminal_action
    )
    if not terminal_ok:
        violations.append("missing_terminal")
    if scenario.require_no_terminal and terminal_action is not None:
        violations.append("unexpected_terminal")
    if scenario.forbidden_routes and final_route in scenario.forbidden_routes:
        violations.append("forbidden_route")

    violations.extend(_scenario_violations(turns))
    unique_violations = sorted(set(violations))

    return {
        "scenario_id": scenario.scenario_id,
        "expected_route": scenario.expected_route,
        "expected_terminal_action": scenario.expected_terminal_action,
        "final_route": final_route,
        "route_ok": route_ok,
        "terminal_action": terminal_action,
        "terminal_ok": terminal_ok,
        "turn_count": len(turns),
        "violations": unique_violations,
        "turns": turns,
    }


def _turn_violations(turn_payload: dict[str, Any], scenario: SmokeScenario) -> list[str]:
    violations: list[str] = []
    if not str(turn_payload.get("assistant_text", "")).strip():
        violations.append("empty_response")

    validation_codes = {
        issue["code"] for issue in turn_payload.get("validation_problems", [])
    }
    validation_codes.update(
        issue["code"] for issue in turn_payload.get("initial_validation_problems", [])
    )
    if "internal_word" in validation_codes:
        violations.append("internal_words")
    if "internal_workflow_term" in validation_codes:
        violations.append("internal_workflow_term")
    if "terminal_followup_question" in validation_codes:
        violations.append("terminal_followup_question")
    if "handoff_without_action" in validation_codes or _handoff_without_event(turn_payload):
        violations.append("handoff_without_event")
    if "offtopic_executed" in validation_codes:
        violations.append("off_topic_executed")
    if turn_payload.get("writer_mode") != "deterministic" and _few_shot_body_copy(turn_payload):
        violations.append("few_shot_body_copy")

    if scenario.scenario_id == "s02_clean_cards_repair_no_bfl_before_pts":
        violations.extend(_s02_contextual_amount_violations(turn_payload))

    selected_route = turn_payload.get("selected_route")
    if scenario.expected_route != OTHER and selected_route == OTHER:
        violations.append("early_other")

    return violations


def _s02_contextual_amount_violations(turn_payload: dict[str, Any]) -> list[str]:
    if turn_payload.get("turn") != 5:
        return []
    violations: list[str] = []
    if turn_payload.get("next_slot") == "monthly_payments":
        violations.append("s02_monthly_payments_reopened")
    if turn_payload.get("next_slot") == "urgency":
        violations.append("s02_urgency_reopened")
    extracted_facts = turn_payload.get("extracted_facts") or {}
    if "monthly_payments" in extracted_facts:
        violations.append("s02_monthly_payments_reextracted")
    return violations


def _scenario_violations(turns: list[dict[str, Any]]) -> list[str]:
    if _has_loop_same_slot(turns):
        return ["loop_same_slot"]
    return []


def _has_loop_same_slot(turns: list[dict[str, Any]]) -> bool:
    next_slots = [turn.get("next_slot") for turn in turns]
    for index in range(2, len(next_slots)):
        current = next_slots[index]
        if current and current == next_slots[index - 1] == next_slots[index - 2]:
            return True
    return False


def _handoff_without_event(turn_payload: dict[str, Any]) -> bool:
    text = str(turn_payload.get("assistant_text", "")).lower()
    has_handoff_language = any(marker in text for marker in HANDOFF_LANGUAGE)
    has_events = bool(turn_payload.get("action_events"))
    terminal_action = turn_payload.get("terminal_action")
    return has_handoff_language and (not terminal_action or not has_events)


def _build_summary(scenario_results: list[dict[str, Any]]) -> dict[str, Any]:
    route_ok_count = sum(1 for result in scenario_results if result["route_ok"])
    violation_counts: dict[str, int] = {}
    for result in scenario_results:
        for violation in result["violations"]:
            violation_counts[violation] = violation_counts.get(violation, 0) + 1

    hard_zero_violations = {
        "empty_response",
        "forbidden_route",
        "internal_words",
        "internal_workflow_term",
        "terminal_followup_question",
        "unexpected_terminal",
        "s02_monthly_payments_reopened",
        "s02_monthly_payments_reextracted",
        "s02_urgency_reopened",
        "few_shot_body_copy",
        "handoff_without_event",
        "early_other",
    }
    hard_zero_ok = all(violation_counts.get(code, 0) == 0 for code in hard_zero_violations)

    return {
        "scenario_count": len(scenario_results),
        "route_ok_count": route_ok_count,
        "route_ok_ratio": f"{route_ok_count}/{len(scenario_results)}",
        "terminal_ok_count": sum(1 for result in scenario_results if result["terminal_ok"]),
        "violation_counts": violation_counts,
        "failing_scenarios": [
            {
                "scenario_id": result["scenario_id"],
                "violations": result["violations"],
                "expected_route": result["expected_route"],
                "final_route": result["final_route"],
            }
            for result in scenario_results
            if result["violations"]
        ],
        "stop_criteria_ok": route_ok_count >= 9 and hard_zero_ok,
    }


def _write_artifact(payload: dict[str, Any], *, artifact_dir: Path) -> Path:
    artifact_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    artifact_path = artifact_dir / f"dialogue_v3_smoke_{timestamp}.json"
    artifact_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return artifact_path


def _turn_result_to_payload(result: DialogueV3TurnResult, *, writer_mode: WriterMode) -> dict[str, Any]:
    return {
        "turn": result.state.turn_index,
        "writer_mode": writer_mode,
        "user_text": result.extracted.raw_user_text,
        "assistant_text": result.text,
        "selected_route": result.route_session.selected_route,
        "phase": result.route_session.phase,
        "next_slot": result.route_session.next_slot,
        "closed_primary_slots": list(result.route_session.closed_primary_slots),
        "missing_primary_slots": list(result.route_session.missing_primary_slots),
        "blockers": list(result.route_session.blockers),
        "terminal_action": result.route_session.terminal_action,
        "action_events": [_to_plain(event) for event in result.events],
        "extracted_facts": result.extracted.facts,
        "case_frame": _to_plain(result.frame),
        "route_session": _to_plain(result.route_session),
        "actor_move": _to_plain(result.actor_move),
        "writer_output": {
            "body": result.writer_output.body,
            "followup_question": result.writer_output.followup_question,
        },
        "validation_problems": [
            {"code": issue.code, "message": issue.message}
            for issue in result.writer_validation.issues
        ],
        "initial_validation_problems": [
            {"code": issue.code, "message": issue.message}
            for issue in result.initial_writer_validation.issues
        ],
        "writer_invalid": result.writer_invalid,
        "repair_attempted": result.repair_attempted,
        "fallback_used": result.fallback_used,
    }


def _normalize_public_form(payload: dict[str, Any]) -> dict[str, Any]:
    root_payload, extra_facts = smoke_public_form_to_root_payload(payload)
    facts: dict[str, Any] = {"public_form": payload}
    facts.update(public_form_to_facts(root_payload))
    facts.update(extra_facts)
    return facts


def smoke_public_form_to_root_payload(
    payload: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Map legacy smoke labels to public root form fields before parsing."""

    root_payload: dict[str, Any] = {}
    extra_facts: dict[str, Any] = {}
    for raw_key, raw_value in payload.items():
        key = str(raw_key).strip().lower()
        value = str(raw_value).strip()

        if key in {"сумма", "desired_amount", "amount"}:
            root_payload["Сумма"] = raw_value
        elif key in {"фио", "full_name"}:
            root_payload["ФИО"] = raw_value
        elif key in {"телефон", "phone"}:
            root_payload["Телефон"] = raw_value
        elif key in {"есть авто", "has_car"}:
            root_payload["Есть ли в собственности авто?"] = raw_value
        elif key in {"есть недвижимость", "has_property"}:
            has_property = _bool_from_form_value(raw_value)
            if has_property is True:
                root_payload["Тип актива"] = "Недвижимость"
            elif has_property is False:
                root_payload["Тип актива"] = "Нет активов"
        elif key in {"есть текущие кредиты", "has_current_loans"}:
            root_payload["Есть текущие кредиты или займы?"] = raw_value
        elif key in {"регион недвижимости", "property_region"}:
            extra_facts["property_region"] = value
        elif key in {"тип недвижимости", "property_type"}:
            extra_facts["property_type"] = value
        elif key in {"доход", "official_income"}:
            amount = _amount_from_form_value(raw_value)
            if amount is not None:
                extra_facts["official_income"] = amount
                extra_facts["income_status"] = "stable"
        else:
            root_payload[raw_key] = raw_value
    return root_payload, extra_facts


def _bool_from_form_value(value: Any) -> bool | None:
    facts = public_form_to_facts({"Есть ли в собственности авто?": value})
    fact_value = facts.get("has_car")
    return fact_value if isinstance(fact_value, bool) else None


def _amount_from_form_value(value: Any) -> int | None:
    facts = public_form_to_facts({"Сумма": value})
    amount = facts.get("desired_amount")
    return amount if isinstance(amount, int) else None


def _to_plain(value: Any) -> Any:
    if is_dataclass(value):
        return {key: _to_plain(item) for key, item in asdict(value).items()}
    if isinstance(value, dict):
        return {str(key): _to_plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_to_plain(item) for item in value]
    return value


def _few_shot_body_copy(turn_payload: dict[str, Any]) -> bool:
    """Catch exact or near-exact reuse of long few-shot body text."""

    writer_output = turn_payload.get("writer_output")
    if not isinstance(writer_output, dict):
        return False

    body = str(writer_output.get("body") or "")
    normalized_body = _normalize_copy_text(body)
    if len(normalized_body) < MIN_FEW_SHOT_BODY_COPY_LENGTH:
        return False

    for few_shot_body in _few_shot_good_bodies():
        if normalized_body == few_shot_body:
            return True
        length_ratio = min(len(normalized_body), len(few_shot_body)) / max(
            len(normalized_body),
            len(few_shot_body),
        )
        if length_ratio >= 0.75:
            similarity = difflib.SequenceMatcher(None, normalized_body, few_shot_body).ratio()
            if similarity >= FEW_SHOT_BODY_COPY_RATIO:
                return True
    return False


def _normalize_copy_text(text: str) -> str:
    normalized = text.lower().replace("ё", "е")
    normalized = re.sub(r"[\"'«»“”„`]", "", normalized)
    normalized = re.sub(r"[-–—]+", " ", normalized)
    normalized = re.sub(r"[^\w\s]", "", normalized, flags=re.UNICODE)
    normalized = re.sub(r"\s+", " ", normalized)
    return normalized.strip()


def _few_shot_good_bodies() -> tuple[str, ...]:
    global FEW_SHOT_GOOD_BODIES
    if FEW_SHOT_GOOD_BODIES is None:
        FEW_SHOT_GOOD_BODIES = tuple(
            normalized
            for example in FEW_SHOT_EXAMPLES
            if (body := str(example.get("good_json", {}).get("body") or "").strip())
            if len(normalized := _normalize_copy_text(body)) >= MIN_FEW_SHOT_BODY_COPY_LENGTH
        )
    return FEW_SHOT_GOOD_BODIES


if __name__ == "__main__":
    raise SystemExit(main())
