#!/usr/bin/env python3
"""Routing-эвал: проверяет, ПРАВИЛЬНО ли извлекатель маршрутизирует лида.

Это другая ось, чем `run_eval.py` (тот мерит ЧЕЛОВЕЧНОСТЬ речи). Тут мы кормим
синтетические профили клиентов в извлекающий вызов и проверяем product_fit_result.

Запуск:
  OPEN_ROUTER_API_KEY=... python run_routing_eval.py
  ... --model deepseek/deepseek-v4 --extractor qwen/qwen3.6-plus     # переопределить модели
  python run_routing_eval.py --dry-run                               # без API: только показать кейсы
"""
from __future__ import annotations
import argparse
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
CASES = json.loads((HERE / "routing_cases.json").read_text(encoding="utf-8"))


def _normalize_id(value: str | None) -> str:
    return (value or "").strip().lower()


def evaluate_case(state_update: dict, expected: dict) -> tuple[bool, list[str]]:
    """Возвращает (passed, причины несоответствий)."""
    reasons: list[str] = []
    pfr = state_update.get("product_fit_result") or {}

    actual_rec = _normalize_id(pfr.get("recommended_product_id"))
    expected_rec = _normalize_id(expected.get("recommended"))
    if expected_rec:
        if actual_rec != expected_rec:
            reasons.append(f"recommended: ожидали {expected_rec!r}, получили {actual_rec!r}")
    elif actual_rec:
        # Ожидали null (жёсткий стоп) — но если модель дала допустимую альтернативу, не штрафуем.
        pass

    actual_blocked = {_normalize_id(x) for x in (pfr.get("blocked_products") or [])}
    for required in expected.get("blocked_includes", []):
        if _normalize_id(required) not in actual_blocked:
            reasons.append(f"blocked не содержит {required!r} (есть: {sorted(actual_blocked)})")

    return (len(reasons) == 0), reasons


def run_case(case: dict, model: str, extractor_model: str | None) -> dict:
    # Импортим лениво, чтобы --dry-run работал без зависимостей.
    from config import AppConfig
    from llm_agent import extract_state

    cfg = AppConfig(
        openrouter_api_key=os.environ["OPEN_ROUTER_API_KEY"],
        model=model,
        extractor_model=extractor_model,
        temperature=0.0,
        max_tokens=900,
    )
    payload = {
        "current_facts": case["facts"],
        "fact_statuses": {},
        "short_history": [],
        "latest_user_message": case["user_input"],
        "business_rules_summary": "Маршрутизируй по фактам и стоп-факторам. Не торопись с recommended, если данных мало.",
    }
    # Ответ оператора почти не влияет — это бэкенд-разбор; даём нейтральный текст.
    assistant_reply = "Понял ситуацию, посмотрю по вариантам."
    return extract_state(payload, assistant_reply, cfg)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="не звонить в API, только показать кейсы")
    ap.add_argument("--model", default=os.getenv("OPENROUTER_MODEL", "deepseek/deepseek-v4"))
    ap.add_argument("--extractor", default=os.getenv("OPENROUTER_EXTRACTOR_MODEL"))
    args = ap.parse_args()

    if args.dry_run:
        print(f"Кейсов: {len(CASES)}\n")
        for c in CASES:
            exp = c["expected"]
            print(f"[{c['id']}] {c['label']}")
            print(f"   ожидаем: rec={exp.get('recommended')!r}, blocked⊇{exp.get('blocked_includes', [])}")
        return 0

    if not os.getenv("OPEN_ROUTER_API_KEY"):
        print("!! Нужен OPEN_ROUTER_API_KEY, либо запусти с --dry-run.", file=sys.stderr)
        return 2

    print(f"Routing eval: модель-извлекатель = {args.extractor or args.model}  (кейсов: {len(CASES)})\n")
    passed = 0
    fails: list[tuple[str, list[str]]] = []

    for i, case in enumerate(CASES, 1):
        try:
            su = run_case(case, args.model, args.extractor)
        except Exception as exc:
            print(f"  [{i:2}] {case['id']:35} ОШИБКА: {exc}")
            fails.append((case["id"], [f"исключение: {exc}"]))
            continue
        ok, reasons = evaluate_case(su, case["expected"])
        pfr = su.get("product_fit_result") or {}
        rec = pfr.get("recommended_product_id")
        blocked = pfr.get("blocked_products") or []
        status = "✅ PASS" if ok else "❌ FAIL"
        print(f"  [{i:2}] {case['id']:35} {status}  rec={rec!r}  blocked={blocked}")
        if ok:
            passed += 1
        else:
            for r in reasons:
                print(f"        └─ {r}")
            fails.append((case["id"], reasons))

    total = len(CASES)
    print(f"\nИтого: {passed}/{total} ({100 * passed / total:.0f}%)")
    if fails:
        print("\nПровалы:")
        for cid, reasons in fails:
            print(f"  - {cid}: {'; '.join(reasons)}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
