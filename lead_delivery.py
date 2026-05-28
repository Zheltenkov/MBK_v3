"""Доставка лида поставщику/в CRM.

Сейчас это ЗАГЛУШКА: лид пишется в logs/leads.jsonl и возвращается статус
«клиент переведён к специалисту по направлению ...». Когда появится реальный приёмник —
задай LEAD_WEBHOOK_URL в .env, и тот же лид будет POST-иться туда (JSON). Менять код не нужно.

Хендофф срабатывает только когда извлекатель уверенно определил маршрут и не осталось
недостающих фактов — поэтому преждевременной передачи «без данных по машине» не будет.
"""
from __future__ import annotations

import json
import os
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any

LOG_DIR = Path("logs")

PRODUCT_LABELS = {
    "realty_collateral": "залог недвижимости",
    "pts_loan": "залог авто (ПТС)",
    "bfl_realization": "банкротство — реализация имущества",
    "bfl_restructuring": "банкротство — реструктуризация долгов",
    "unsecured_loan": "кредит без залога",
    "partner_unsecured": "партнёрские заявки (беззалог/микро)",
}


def _product_id(state: dict, analysis: dict) -> str | None:
    pfr = analysis.get("product_fit_result") or {}
    tc = analysis.get("target_completion") or {}
    return (
        pfr.get("recommended_product_id")
        or state.get("selected_product_id")
        or tc.get("target_mode")
    )


def should_deliver(state: dict, analysis: dict) -> bool:
    """Передаём лид, только если: ещё не передавали, есть понятный продукт,
    извлекатель сигналит хендофф/целевое завершение и нет недостающих фактов."""
    if state.get("lead_delivered"):
        return False
    pfr = analysis.get("product_fit_result") or {}
    phase = analysis.get("dialog_phase")
    handoff = bool(pfr.get("handoff_required")) or phase in {"handoff", "target_completion"}
    has_product = bool(_product_id(state, analysis))
    no_gaps = not pfr.get("missing_facts")
    not_declined = _product_id(state, analysis) not in (state.get("declined_products") or [])
    return handoff and has_product and no_gaps and not_declined


def build_lead(state: dict, analysis: dict) -> dict[str, Any]:
    pid = _product_id(state, analysis)
    tc = analysis.get("target_completion") or {}
    return {
        "session_id": state.get("session_id"),
        "created_at": datetime.now().isoformat(),
        "product_id": pid,
        "product_label": PRODUCT_LABELS.get(pid, pid),
        "facts": state.get("current_facts", {}),
        "crm_note": (tc.get("crm_note") or analysis.get("internal_summary") or "").strip(),
        "links_to_send_now": tc.get("links_to_send_now", []),
    }


def deliver(lead: dict[str, Any]) -> dict[str, Any]:
    """Возвращает {delivered, channel, message}. Всегда пишет в локальный журнал лидов,
    дополнительно POST-ит в LEAD_WEBHOOK_URL, если он задан."""
    label = lead.get("product_label") or "не определён"

    try:
        LOG_DIR.mkdir(exist_ok=True)
        with (LOG_DIR / "leads.jsonl").open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(lead, ensure_ascii=False, default=str) + "\n")
    except Exception:
        pass

    webhook = os.getenv("LEAD_WEBHOOK_URL")
    if webhook:
        try:
            body = json.dumps(lead, ensure_ascii=False, default=str).encode("utf-8")
            req = urllib.request.Request(
                webhook, data=body, headers={"Content-Type": "application/json"}
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                resp.read()
            return {
                "delivered": True,
                "channel": "webhook",
                "message": f"Лид передан специалисту по направлению «{label}» (отправлено в CRM).",
            }
        except Exception as exc:  # noqa: BLE001
            return {
                "delivered": False,
                "channel": "webhook",
                "message": (
                    f"Лид сформирован по «{label}», но CRM не ответил ({exc}). "
                    "Записан в logs/leads.jsonl."
                ),
            }

    return {
        "delivered": True,
        "channel": "stub",
        "message": (
            f"Клиент переведён к специалисту по направлению «{label}». "
            "(заглушка — CRM не подключён, лид записан в logs/leads.jsonl)"
        ),
    }


def maybe_deliver(state: dict, analysis: dict) -> dict[str, Any] | None:
    """Главная точка входа из core. None, если передавать ещё рано."""
    if not should_deliver(state, analysis):
        return None
    lead = build_lead(state, analysis)
    status = deliver(lead)
    return {**status, "lead": lead}
