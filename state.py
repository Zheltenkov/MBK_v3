from __future__ import annotations
from typing import Any


def seed_current_facts(anketa: dict[str, Any]) -> dict[str, Any]:
    """Сеем ВЛОЖЕННУЮ структуру фактов из анкеты — ту же, в которой пишет извлекатель.

    Принимает либо плоский, либо вложенный JSON анкеты (форма фронта шлёт вложенные
    vehicle/realty/credit_types — это всё корректно перекладывается в factsmap).
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

    # === Клиент ===
    put(client, "full_name", anketa.get("full_name"))
    put(client, "phone", anketa.get("phone"))
    put(client, "birth_date", anketa.get("birth_date"))
    put(client, "registration_address", anketa.get("registration_address"))
    put(client, "living_address", anketa.get("living_address"))
    if anketa.get("addresses_match") is not None:
        client["addresses_match"] = bool(anketa["addresses_match"])

    # === Запрос ===
    put(request, "desired_amount", anketa.get("desired_amount"))

    # === Занятость ===
    put(employment, "type", anketa.get("employment_type"))
    put(employment, "monthly_income", anketa.get("monthly_income"))
    put(employment, "organization", anketa.get("organization_name"))
    put(employment, "position", anketa.get("position_type"))
    put(employment, "work_start_year", anketa.get("work_start_year"))

    # === Активы: тип, авто, недвижимость ===
    put(assets, "type", anketa.get("asset_type"))
    if anketa.get("has_car") is not None:
        assets["has_car"] = bool(anketa["has_car"])

    vehicle_in = anketa.get("vehicle") if isinstance(anketa.get("vehicle"), dict) else None
    if vehicle_in:
        vehicle: dict[str, Any] = {}
        put(vehicle, "make", vehicle_in.get("make"))
        put(vehicle, "model", vehicle_in.get("model"))
        put(vehicle, "year", vehicle_in.get("year"))
        if vehicle_in.get("pledged") is not None:
            vehicle["pledged"] = bool(vehicle_in["pledged"])
        put(vehicle, "loan_balance", vehicle_in.get("loan_balance"))
        if vehicle:
            assets["vehicle"] = vehicle

    realty_in = anketa.get("realty") if isinstance(anketa.get("realty"), dict) else None
    if realty_in:
        realty: dict[str, Any] = {}
        put(realty, "kind", realty_in.get("kind"))
        put(realty, "region", realty_in.get("region"))
        put(realty, "ownership", realty_in.get("ownership"))
        put(realty, "share_with", realty_in.get("share_with"))
        put(realty, "encumbrance", realty_in.get("encumbrance"))
        put(realty, "loan_balance", realty_in.get("loan_balance"))
        if realty:
            assets["realty"] = realty

    # === Долги: блок раскрывается только при has_current_loans=True ===
    if anketa.get("has_current_loans") is not None:
        debts["has_current_loans"] = bool(anketa["has_current_loans"])
    put(debts, "total", anketa.get("debts_total"))
    put(debts, "monthly_payments", anketa.get("monthly_debt_payments"))
    kinds = anketa.get("credit_types")
    if isinstance(kinds, list) and kinds:
        debts["kinds"] = list(kinds)
        # Удобный флаг для маршрутизации: есть ли МФО среди типов.
        debts["has_mfo"] = any("микрозайм" in str(k).lower() or "мфо" in str(k).lower() for k in kinds)
    put(debts, "overdue_duration", anketa.get("overdue_duration"))
    # Удобный булев флаг «есть ли текущая просрочка» — для relevant_product_knowledge.
    overdue = (anketa.get("overdue_duration") or "").strip().lower()
    if overdue and overdue not in ("", "нет"):
        debts["has_current_overdue"] = True
    elif overdue == "нет":
        debts["has_current_overdue"] = False

    # === Домохозяйство ===
    put(household, "marital_status", anketa.get("marital_status"))
    if anketa.get("has_dependents") is not None:
        household["has_dependents"] = bool(anketa["has_dependents"])
    put(household, "dependents_count", anketa.get("dependents_count"))
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
