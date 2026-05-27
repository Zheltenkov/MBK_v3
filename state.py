from copy import deepcopy
from typing import Dict, Optional

ANKETA_SEED_KEYS = (
    "desired_amount",
    "asset_type",
    "has_car",
    "has_current_loans",
    "employment_type",
)


def init_dialog_state(anketa: dict) -> dict:
    """Инициализация начального состояния диалога."""
    anketa = anketa or {}
    extracted_data = {
        key: anketa[key]
        for key in ANKETA_SEED_KEYS
        if anketa.get(key) is not None
    }

    return {
        "selected_case": None,
        "anketa_summary": None,
        "extracted_data": extracted_data,
        "current_facts": {
            key: value
            for key, value in anketa.items()
            if value is not None
        },
        "fact_statuses": {},
        "chat_history": [],
        "answered_fields": sorted(extracted_data.keys()),
        "dialog_stage": "qualification",
        "message_count": 0,
        "last_objection": None,
    }


def update_dialog_state(
    current_state: dict,
    analysis: dict,
    new_facts: Optional[dict] = None,
) -> dict:
    """Обновление состояния после каждого сообщения клиента."""
    state = deepcopy(current_state or {})
    extracted_data = dict(state.get("extracted_data") or {})

    if new_facts:
        extracted_data.update(new_facts)

    state["extracted_data"] = extracted_data
    state["answered_fields"] = sorted(extracted_data.keys())
    state["message_count"] = state.get("message_count", 0) + 1

    if analysis.get("has_objection"):
        state["last_objection"] = {
            "type": analysis.get("objection_type"),
            "details": analysis.get("objection_details"),
        }

    if analysis.get("ready_for_offer"):
        state["dialog_stage"] = "offer"
    elif state["message_count"] >= 15:
        state["dialog_stage"] = "closed"

    return state


def should_close_dialog(state: dict, analysis: dict) -> bool:
    """Проверка, можно ли завершать диалог."""
    if analysis.get("ready_for_offer"):
        return True
    if state.get("message_count", 0) >= 15:
        return True
    return False
