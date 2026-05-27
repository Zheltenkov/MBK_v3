from __future__ import annotations
from typing import Any


def seed_current_facts(anketa: dict[str, Any]) -> dict[str, Any]:
    """Сеем ВЛОЖЕННУЮ структуру фактов из анкеты — ту же, в которой пишет извлекатель.

    Раньше анкета садилась плоскими ключами (full_name, desired_amount), а извлекатель писал
    вложенными путями (client.full_name, request.desired_amount). Модели было сказано
    «не переспрашивай известное», но она физически не сопоставляла плоский ключ с вложенным.
    Здесь приводим всё к единой схеме.
    """
    client: dict[str, Any] = {}
    request: dict[str, Any] = {}
    assets: dict[str, Any] = {}
    employment: dict[str, Any] = {}
    household: dict[str, Any] = {}
    debts: dict[str, Any] = {}

    def put(dest: dict, key: str, value: Any) -> None:
        if value is not None and value != "":
            dest[key] = value

    put(client, "full_name", anketa.get("full_name"))
    put(client, "phone", anketa.get("phone"))
    put(client, "birth_date", anketa.get("birth_date"))
    put(client, "registration_address", anketa.get("registration_address"))
    put(client, "living_address", anketa.get("living_address"))
    if anketa.get("addresses_match") is not None:
        client["addresses_match"] = bool(anketa["addresses_match"])

    put(request, "desired_amount", anketa.get("desired_amount"))

    put(employment, "type", anketa.get("employment_type"))

    put(assets, "type", anketa.get("asset_type"))
    if anketa.get("has_car") is not None:
        assets["has_car"] = bool(anketa["has_car"])

    if anketa.get("has_current_loans") is not None:
        debts["has_current_loans"] = bool(anketa["has_current_loans"])

    put(household, "marital_status", anketa.get("marital_status"))
    if anketa.get("has_dependents") is not None:
        household["has_dependents"] = bool(anketa["has_dependents"])
    put(household, "rent_expenses", anketa.get("rent_expenses"))

    facts: dict[str, Any] = {}
    for name, group in [
        ("client", client),
        ("request", request),
        ("assets", assets),
        ("employment", employment),
        ("household", household),
        ("debts", debts),
    ]:
        if group:
            facts[name] = group
    return facts


def init_dialog_state(anketa: dict[str, Any]) -> dict[str, Any]:
    seeded = seed_current_facts(anketa or {})
    return {
        "current_facts": seeded,
        "fact_statuses": {},
        "chat_history": [],
        "message_count": 0,
        "dialog_stage": "qualification",
        "selected_case": None,
        "selected_product_id": None,
        "product_fit_result": None,
        "target_completion": None,
        "extracted_data": seeded,
        "answered_fields": sorted(seeded.keys()),
    }


# Мягкий потолок диалога. Раньше было 15 + жёсткий обрыв на ready_for_offer:
# одна классификация извлекателя — и поле ввода исчезало посреди живого разговора.
# Теперь закрываем только при явной команде (dialog_stage="closed") или на длинном лимите.
SOFT_MESSAGE_LIMIT = 30


def update_dialog_state(state: dict[str, Any], analysis: dict[str, Any]) -> dict[str, Any]:
    state["message_count"] = state.get("message_count", 0) + 1
    if analysis.get("ready_for_offer"):
        state["dialog_stage"] = "offer"  # подсказка UI «пора передавать», но НЕ закрытие
    elif state["message_count"] >= SOFT_MESSAGE_LIMIT:
        state["dialog_stage"] = "closed"
    return state


def should_close_dialog(state: dict[str, Any], analysis: dict[str, Any] | None = None) -> bool:
    """Закрываем только при явном `closed` или мягком потолке.

    `ready_for_offer` НЕ закрывает диалог автоматически — клиент может задать ещё вопросы
    после того, как извлекатель уже пометил фазу handoff. Раньше тут терялись живые лиды.
    """
    if state.get("dialog_stage") == "closed":
        return True
    return state.get("message_count", 0) >= SOFT_MESSAGE_LIMIT
