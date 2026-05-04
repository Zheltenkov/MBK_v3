from __future__ import annotations

import csv
from pathlib import Path

from mbk_refactor.dialogue_v3.engine import DialogueV3Engine
from mbk_refactor.dialogue_v3.ui_form_schema import (
    BLOCKED_CHILD_FIELDS,
    CHILD_FACT_KEYS,
    ROOT_FORM_FIELDS,
    public_form_to_facts,
    public_form_to_state,
    rendered_root_form_fields,
)


CAR_CHILD_FIELDS = {
    "Марка",
    "Модель",
    "Год выпуска",
    "В залоге",
    "Остаток по кредиту",
    "Информация о 2 автомобиле",
}

DEBT_CHILD_FIELDS = {
    "Общая задолженность по всем кредитным обязательствам",
    "Общие ежемесячные выплаты",
    "Виды активных кредитов",
    "Продолжительность просрочки",
}

PROPERTY_CHILD_FIELDS = {
    "Тип недвижимости",
    "Регион собственности",
    "Форма собственности",
    "С кем доля",
    "Обременение/ограничение",
    "Остаток по кредиту",
    "Вторая недвижимость",
}


def test_root_form_contains_only_nesting_1_fields() -> None:
    rendered = rendered_root_form_fields()

    assert rendered == ROOT_FORM_FIELDS
    assert not set(rendered) & set(BLOCKED_CHILD_FIELDS)

    csv_path = Path("docs/Input + Qualification.csv")
    if csv_path.exists():
        rows = list(csv.DictReader(csv_path.open(encoding="utf-8-sig")))
        csv_root = [
            str(row["Поле"]).strip()
            for row in rows
            if str(row.get("Вложенность") or "").strip() == "1"
        ]
        assert rendered == csv_root


def test_car_child_fields_are_not_rendered_when_car_root_exists() -> None:
    rendered = set(rendered_root_form_fields())

    assert "Есть ли в собственности авто?" in rendered
    assert not rendered & CAR_CHILD_FIELDS


def test_debt_child_fields_are_not_rendered_when_debt_root_exists() -> None:
    rendered = set(rendered_root_form_fields())

    assert "Есть текущие кредиты или займы?" in rendered
    assert not rendered & DEBT_CHILD_FIELDS


def test_employment_child_income_is_not_rendered() -> None:
    rendered = set(rendered_root_form_fields())

    assert "Тип занятости" in rendered
    assert "Доход" not in rendered


def test_property_child_fields_are_not_rendered_when_asset_root_exists() -> None:
    rendered = set(rendered_root_form_fields())

    assert "Тип актива" in rendered
    assert not rendered & PROPERTY_CHILD_FIELDS


def test_public_form_to_state_maps_only_submitted_root_fields() -> None:
    payload = {
        "Сумма": 700_000,
        "ФИО": "Иван Петров",
        "Есть ли в собственности авто?": True,
        "Тип занятости": "найм",
        "Марка": "Toyota",
        "Год выпуска": 2020,
        "Общая задолженность по всем кредитным обязательствам": 1_200_000,
        "Доход": 150_000,
        "Тип недвижимости": "квартира",
    }

    facts = public_form_to_facts(payload)

    assert facts["desired_amount"] == 700_000
    assert facts["full_name"] == "Иван Петров"
    assert facts["has_car"] is True
    assert facts["employment_type"] == "найм"
    assert "raw_car_name" not in facts
    assert "car_year" not in facts
    assert "total_debt" not in facts
    assert "official_income" not in facts
    assert "property_type" not in facts


def test_child_facts_are_unknown_after_form_submit() -> None:
    state = public_form_to_state(
        {
            "Сумма": 900_000,
            "Есть ли в собственности авто?": True,
            "Есть текущие кредиты или займы?": True,
            "Иждивенцы": True,
            "Тип занятости": "найм",
            "Тип актива": "Недвижимость",
        },
        session_id="form-schema-test",
    )

    assert state.fact_value("has_car") is True
    assert state.fact_value("has_current_loans") is True
    assert state.fact_value("has_dependents") is True
    assert state.fact_value("employment_type") == "найм"
    assert state.fact_value("has_property") is True
    for key in CHILD_FACT_KEYS:
        assert state.fact_value(key) is None


def test_living_address_matches_registration_when_checkbox_true() -> None:
    state = public_form_to_state(
        {
            "Адрес регистрации": "Москва, Тверская 1",
            "галочка совпадает": True,
        },
        session_id="address-match",
    )

    assert state.fact_value("registration_address") == "Москва, Тверская 1"
    assert state.fact_value("living_address") == "Москва, Тверская 1"


def test_living_address_can_be_entered_when_checkbox_false() -> None:
    state = public_form_to_state(
        {
            "Адрес регистрации": "Москва, Тверская 1",
            "галочка совпадает": False,
            "Адрес проживания": "Москва, Арбат 2",
        },
        session_id="address-different",
    )

    assert state.fact_value("registration_address") == "Москва, Тверская 1"
    assert state.fact_value("living_address") == "Москва, Арбат 2"


def test_assistant_collects_car_child_fact_after_root_car_signal() -> None:
    state = public_form_to_state(
        {"Сумма": 500_000, "Есть ли в собственности авто?": True},
        session_id="car-intake",
    )

    result = DialogueV3Engine().handle_turn("Нужны деньги, авто есть.", state)

    assert result.route_session.selected_route == "PTS"
    assert result.route_session.next_slot == "car_brand_model"
    assert state.fact_value("raw_car_name") is None


def test_assistant_collects_debt_child_fact_after_root_credit_signal() -> None:
    state = public_form_to_state(
        {"Есть текущие кредиты или займы?": True},
        session_id="debt-intake",
    )

    result = DialogueV3Engine().handle_turn("Банкротство не хочу, хочу платить.", state)

    assert result.route_session.selected_route == "BFL_RD"
    assert result.route_session.next_slot == "total_debt"
    assert state.fact_value("total_debt") is None
    assert state.fact_value("monthly_payments") is None


def test_assistant_collects_property_child_fact_after_root_asset_signal() -> None:
    state = public_form_to_state(
        {"Сумма": 2_000_000, "Тип актива": "Недвижимость"},
        session_id="property-intake",
    )

    result = DialogueV3Engine().handle_turn("Нужны деньги.", state)

    assert result.route_session.selected_route == "MORTGAGE_AUX"
    assert result.route_session.next_slot == "property_type"
    assert state.fact_value("property_type") is None
    assert state.fact_value("property_region") is None
