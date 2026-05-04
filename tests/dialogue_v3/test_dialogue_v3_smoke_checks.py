from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType


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
