from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

from mbk_refactor.dialogue_v3.ui_form_schema import public_form_to_facts


def load_smoke_module() -> ModuleType:
    root = Path(__file__).resolve().parents[2]
    module_path = root / "tools" / "run_dialogue_v3_smoke.py"
    spec = importlib.util.spec_from_file_location("run_dialogue_v3_smoke", module_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_smoke_flags_exact_few_shot_body_copy() -> None:
    smoke = load_smoke_module()
    scenario = smoke.SMOKE_SCENARIOS[8]
    copied_body = next(
        example["good_json"]["body"]
        for example in smoke.FEW_SHOT_EXAMPLES
        if example.get("good_json", {}).get("body")
        and len(smoke._normalize_copy_text(example["good_json"]["body"])) >= smoke.MIN_FEW_SHOT_BODY_COPY_LENGTH
    )
    turn_payload = {
        "writer_mode": "llm_guarded",
        "assistant_text": copied_body,
        "selected_route": "FRAUD_CHECK",
        "writer_output": {
            "body": copied_body,
            "followup_question": "",
        },
        "validation_problems": [],
        "initial_validation_problems": [],
    }

    violations = smoke._turn_violations(turn_payload, scenario)

    assert "few_shot_body_copy" in violations


def test_smoke_does_not_flag_canonical_short_slot_question_copy() -> None:
    smoke = load_smoke_module()
    scenario = smoke.SMOKE_SCENARIOS[0]
    turn_payload = {
        "writer_mode": "llm_guarded",
        "assistant_text": "Какая у вас машина?",
        "selected_route": "PTS",
        "writer_output": {
            "body": "",
            "followup_question": "Какая у вас машина?",
        },
        "validation_problems": [],
        "initial_validation_problems": [],
    }

    violations = smoke._turn_violations(turn_payload, scenario)

    assert "few_shot_body_copy" not in violations


def test_smoke_form_alias_adapter_uses_public_form_parser() -> None:
    smoke = load_smoke_module()
    payload = {
        "Сумма": "645467 ₽",
        "Есть авто": "да",
        "Есть недвижимость": "да",
        "Есть текущие кредиты": "да",
        "Регион недвижимости": "Москва",
        "Доход": "125 тыс",
    }

    root_payload, extra_facts = smoke.smoke_public_form_to_root_payload(payload)
    normalized = smoke._normalize_public_form(payload)
    expected = {"public_form": payload}
    expected.update(public_form_to_facts(root_payload))
    expected.update(extra_facts)

    assert normalized == expected
    assert normalized["desired_amount"] == 645_467
    assert normalized["has_car"] is True
    assert normalized["has_property"] is True
    assert normalized["has_current_loans"] is True
    assert normalized["property_region"] == "Москва"
    assert normalized["official_income"] == 125_000


def test_smoke_custom_no_terminal_violation_is_hard_zero() -> None:
    smoke = load_smoke_module()
    result = {
        "route_ok": True,
        "terminal_ok": True,
        "violations": ["unexpected_terminal"],
        "scenario_id": "custom",
        "expected_route": "DISCOVERY",
        "final_route": "DISCOVERY",
    }

    summary = smoke._build_summary([result])

    assert summary["violation_counts"]["unexpected_terminal"] == 1
    assert summary["stop_criteria_ok"] is False


def test_smoke_custom_forbidden_route_violation_is_hard_zero() -> None:
    smoke = load_smoke_module()
    result = {
        "route_ok": True,
        "terminal_ok": True,
        "violations": ["forbidden_route"],
        "scenario_id": "custom",
        "expected_route": "DISCOVERY",
        "final_route": "BFL_RD",
    }

    summary = smoke._build_summary([result])

    assert summary["violation_counts"]["forbidden_route"] == 1
    assert summary["stop_criteria_ok"] is False
