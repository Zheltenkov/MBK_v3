"""Root-level manual UI form schema for dialogue_v3.

The Streamlit form must only collect public intake fields with nesting == 1
from "Input + Qualification.csv". Deeper facts are collected later by the
dialogue_v3 intake flow after a route is selected.
"""

from __future__ import annotations

import re
from uuid import uuid4

from .state import DialogueV3State


ROOT_FORM_FIELDS = [
    "Сумма",
    "ФИО",
    "Телефон",
    "Дата рождения",
    "Адрес регистрации",
    "галочка совпадает",
    "Адрес проживания",
    "Есть текущие кредиты или займы?",
    "Семейное положение",
    "Иждивенцы",
    "Тип занятости",
    "Есть ли в собственности авто?",
    "Расходы на аренду жилья",
    "Тип актива",
]


BLOCKED_CHILD_FIELDS = [
    "Общая задолженность по всем кредитным обязательствам",
    "Общие ежемесячные выплаты",
    "Виды активных кредитов",
    "Продолжительность просрочки",
    "Количество иждивенцев",
    "Доход",
    "Марка",
    "Модель",
    "Год выпуска",
    "В залоге",
    "Остаток по кредиту",
    "Информация о 2 автомобиле",
    "Тип недвижимости",
    "Регион собственности",
    "Форма собственности",
    "С кем доля",
    "Обременение/ограничение",
    "Вторая недвижимость",
]


CHILD_FACT_KEYS = {
    "total_debt",
    "monthly_payments",
    "loan_types",
    "has_mfo",
    "has_arrears",
    "arrears_months",
    "official_income",
    "other_income",
    "income_status",
    "raw_car_name",
    "car_brand",
    "car_model",
    "car_brand_model_known",
    "car_year",
    "car_owner",
    "car_owner_known",
    "car_in_pledge",
    "car_arrest_or_restriction",
    "property_type",
    "property_region",
    "property_owner",
    "property_owner_known",
    "property_ownership",
    "property_encumbrance",
    "property_encumbrance_type",
    "property_mortgage",
    "property_pledge",
    "property_arrest",
    "dependents_count",
}


def normalize_form_field_name(name: object) -> str:
    """Normalize CSV/UI labels for stable root-field matching."""

    return re.sub(r"\s+", " ", str(name or "").strip())


def rendered_root_form_fields() -> list[str]:
    """Return the only field labels the startup UI is allowed to render."""

    return list(ROOT_FORM_FIELDS)


def public_form_to_state(
    payload: dict[str, object],
    *,
    session_id: str | None = None,
) -> DialogueV3State:
    """Create initial dialogue state from submitted root UI fields."""

    state = DialogueV3State(session_id=session_id or str(uuid4()))
    state.merge_facts(public_form_to_facts(payload), source="form")
    return state


def public_form_to_facts(payload: dict[str, object]) -> dict[str, object]:
    """Map only submitted root form fields to starting facts.

    Child facts are intentionally ignored even if they appear in payload, so
    they remain unknown until dialogue_v3 intake asks for them in chat.
    """

    normalized = {
        normalize_form_field_name(key): value
        for key, value in payload.items()
        if normalize_form_field_name(key) in ROOT_FORM_FIELDS
    }
    facts: dict[str, object] = {
        "desired_amount": _parse_amount(normalized.get("Сумма")),
        "full_name": _str_or_none(normalized.get("ФИО")),
        "phone": _str_or_none(normalized.get("Телефон")),
        "birth_date": _str_or_none(normalized.get("Дата рождения")),
        "registration_address": _str_or_none(normalized.get("Адрес регистрации")),
        "living_address": _living_address(normalized),
        "addresses_match": _bool_or_none(normalized.get("галочка совпадает")),
        "has_current_loans": _bool_or_none(
            normalized.get("Есть текущие кредиты или займы?")
        ),
        "marital_status": _str_or_none(normalized.get("Семейное положение")),
        "has_dependents": _bool_or_none(normalized.get("Иждивенцы")),
        "employment_type": _str_or_none(normalized.get("Тип занятости")),
        "has_car": _bool_or_none(normalized.get("Есть ли в собственности авто?")),
        "rent_expenses": _parse_amount(normalized.get("Расходы на аренду жилья")),
        "asset_type": _str_or_none(normalized.get("Тип актива")),
    }
    asset_type = str(facts.get("asset_type") or "").lower().replace("ё", "е")
    if "недвиж" in asset_type:
        facts["has_property"] = True
    elif "нет" in asset_type and "актив" in asset_type:
        facts["has_property"] = False

    return _drop_empty(facts)


def _living_address(payload: dict[str, object]) -> str | None:
    if _bool_or_none(payload.get("галочка совпадает")) is True:
        return _str_or_none(payload.get("Адрес регистрации"))
    return _str_or_none(payload.get("Адрес проживания"))


def _bool_or_none(value: object) -> bool | None:
    if isinstance(value, bool):
        return value
    normalized = str(value or "").strip().lower().replace("ё", "е")
    if normalized in {"да", "yes", "true", "1", "есть"}:
        return True
    if normalized in {"нет", "no", "false", "0", "нету"}:
        return False
    return None


def _str_or_none(value: object) -> str | None:
    text = str(value or "").strip()
    if not text or text == "—":
        return None
    return text


def _parse_amount(value: object) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        number = int(value)
        return number if number else None

    text = str(value).lower()
    multiplier = 1
    if "млн" in text:
        multiplier = 1_000_000
    elif "тыс" in text:
        multiplier = 1_000
    cleaned = re.sub(r"[^0-9,.]", "", text).replace(",", ".")
    if not cleaned:
        return None
    try:
        number = int(float(cleaned) * multiplier)
    except ValueError:
        return None
    return number if number else None


def _drop_empty(payload: dict[str, object]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in payload.items():
        if value in (None, "", [], {}):
            continue
        result[key] = value
    return result
