from __future__ import annotations

import pytest

from mbk_refactor.dialogue_v3.constants import MORTGAGE_MAIN, PTS
from mbk_refactor.dialogue_v3.debug_probe import probe_phrase


def test_probe_preserves_monthly_when_comfortable_payment_extracted() -> None:
    result = probe_phrase(
        "Комфортнее было бы платить где-то 25-28 тысяч в месяц.",
        known_facts={"monthly_payments": 34000},
        asked_slots=["comfortable_payment"],
    )

    assert result.extracted_facts["comfortable_payment"] == 28000
    assert "monthly_payments" not in result.extracted_facts
    assert result.state_facts_after_merge["monthly_payments"] == 34000
    assert result.state_facts_after_merge["comfortable_payment"] == 28000
    assert "monthly_payments" not in result.conflicting_facts
    assert result.warnings == []


def test_probe_extracts_income_in_income_context() -> None:
    result = probe_phrase(
        "Официально работаю по найму, доход примерно 115 тысяч в месяц.",
        asked_slots=["income_status"],
    )

    assert result.extracted_facts["official_income"] == 115000
    assert result.extracted_facts["income_status"] == "stable"


def test_probe_routes_soft_auto_retention_phrase_to_pts() -> None:
    result = probe_phrase(
        "Машину как вариант можно обсуждать, но без того, чтобы ее забирать. Она нужна каждый день.",
        known_facts={"has_car": True},
    )

    assert result.extracted_facts["explicit_pts_intent"] is True
    assert result.extracted_facts["vehicle_requires_retention"] is True
    assert result.extracted_facts["vehicle_refuses_collateral"] is False
    assert result.selected_route == PTS
    assert result.next_slot == "car_brand_model"


def test_probe_blocks_hard_pts_refusal() -> None:
    result = probe_phrase(
        "ПТС не рассматриваю, машину вообще не трогаем.",
        known_facts={"has_car": True},
    )

    assert result.extracted_facts["vehicle_refuses_collateral"] is True
    assert result.route_rejection == PTS
    assert result.selected_route != PTS


def test_probe_slot_local_car_brand_model_answer_closes_slot() -> None:
    result = probe_phrase(
        "Kia Sportage.",
        known_facts={"has_car": True, "explicit_pts_intent": True},
        asked_slots=["car_brand_model"],
    )

    assert result.extracted_facts["raw_car_name"] == "Kia Sportage"
    assert result.extracted_facts["car_brand_model_known"] is True
    assert result.selected_route == PTS
    assert result.next_slot == "car_year"


def test_probe_slot_local_car_year_answer_keeps_brand_model_closed() -> None:
    result = probe_phrase(
        "2018 года.",
        known_facts={
            "has_car": True,
            "explicit_pts_intent": True,
            "raw_car_name": "Kia Sportage",
            "car_brand_model_known": True,
        },
        asked_slots=["car_year"],
    )

    assert result.extracted_facts["car_year"] == 2018
    assert result.state_facts_after_merge["raw_car_name"] == "Kia Sportage"
    assert result.selected_route == PTS
    assert result.next_slot == "car_owner"


def test_probe_slot_local_property_type_answer_closes_type_and_region() -> None:
    result = probe_phrase(
        "Квартира в Москве.",
        known_facts={"explicit_mortgage_intent": True},
        asked_slots=["property_type"],
    )

    assert result.extracted_facts["property_type"] == "apartment"
    assert result.extracted_facts["property_region"] == "Москва"
    assert result.selected_route == MORTGAGE_MAIN
    assert result.next_slot == "property_owner_or_ownership"


def test_probe_slot_local_property_region_free_text() -> None:
    result = probe_phrase(
        "Нижний Новгород",
        known_facts={"explicit_mortgage_intent": True, "property_type": "apartment"},
        asked_slots=["property_region"],
    )

    assert result.extracted_facts["property_region"] == "Нижний Новгород"
    assert result.next_slot == "property_owner_or_ownership"


def test_probe_slot_local_property_third_party_owner() -> None:
    result = probe_phrase(
        "На жене.",
        known_facts={"explicit_mortgage_intent": True, "property_type": "apartment"},
        asked_slots=["property_owner_or_ownership"],
    )

    assert result.extracted_facts["property_owner_known"] is True
    assert result.extracted_facts["property_owner"] == "third_party"
    assert result.extracted_facts["third_party_property_owner"] is True
    assert result.next_slot == "property_encumbrance_basic"


def test_probe_slot_local_property_encumbrance_positive_closes_slot() -> None:
    result = probe_phrase(
        "Есть ипотека.",
        known_facts={
            "explicit_mortgage_intent": True,
            "property_type": "apartment",
            "property_owner_known": True,
        },
        asked_slots=["property_encumbrance_basic"],
    )

    assert result.extracted_facts["property_encumbrance"] is True
    assert result.extracted_facts["property_mortgage"] is True
    assert result.extracted_facts["property_encumbrance_type"] == "mortgage"
    assert result.next_slot is None


@pytest.mark.parametrize(
    ("slot", "text", "expected_facts"),
    [
        ("car_brand_model", "Авто нет.", {"has_car": False, "vehicle_no_car_red_flag": True}),
        ("car_year", "2005 года.", {"car_year": 2005, "car_old_year": True}),
        (
            "car_owner",
            "На жене.",
            {"car_owner_known": True, "car_owner": "third_party", "third_party_car_owner": True},
        ),
        (
            "car_pledge_or_restrictions",
            "Автокредита нет, в залоге не была, арестов и ограничений тоже нет.",
            {
                "car_in_pledge": False,
                "car_arrest_or_restriction": False,
                "car_loan_red_flag": False,
                "car_pledge_red_flag": False,
                "car_arrest_red_flag": False,
                "car_restriction_red_flag": False,
            },
        ),
        (
            "car_pledge_or_restrictions",
            "Автокредита нет, но есть ограничения.",
            {
                "car_in_pledge": False,
                "car_loan_red_flag": False,
                "car_arrest_or_restriction": True,
                "car_restriction_red_flag": True,
            },
        ),
        (
            "car_pledge_or_restrictions",
            "Есть автокредит.",
            {"car_in_pledge": True, "car_loan_red_flag": True},
        ),
        (
            "car_pledge_or_restrictions",
            "Машина в залоге.",
            {"car_in_pledge": True, "car_pledge_red_flag": True},
        ),
        (
            "car_pledge_or_restrictions",
            "Есть арест.",
            {"car_arrest_or_restriction": True, "car_arrest_red_flag": True},
        ),
    ],
)
def test_probe_vehicle_slot_level_red_flags(
    slot: str,
    text: str,
    expected_facts: dict[str, object],
) -> None:
    result = probe_phrase(
        text,
        known_facts={"has_car": True, "explicit_pts_intent": True},
        asked_slots=[slot],
        run_route=False,
    )

    for key, value in expected_facts.items():
        assert result.extracted_facts[key] == value


@pytest.mark.parametrize(
    ("slot", "text", "expected_facts"),
    [
        (
            "property_owner_or_ownership",
            "На жене.",
            {"property_owner": "third_party", "property_owner_red_flag": True},
        ),
        (
            "property_encumbrance_basic",
            "В залоге, есть арест.",
            {
                "property_encumbrance": True,
                "property_pledge": True,
                "property_arrest": True,
                "property_encumbrance_red_flag": True,
            },
        ),
        (
            "property_type",
            "Муниципальное жилье.",
            {"property_type": "municipal_housing", "property_object_red_flag": True},
        ),
        ("property_type", "Доля.", {"property_type": "share", "property_share": True}),
        (
            "property_region",
            "Владивосток.",
            {"property_region": "Владивосток", "property_region_supported": False},
        ),
    ],
)
def test_probe_property_slot_level_red_flags(
    slot: str,
    text: str,
    expected_facts: dict[str, object],
) -> None:
    result = probe_phrase(
        text,
        known_facts={"explicit_mortgage_intent": True},
        asked_slots=[slot],
        run_route=False,
    )

    for key, value in expected_facts.items():
        assert result.extracted_facts[key] == value


@pytest.mark.parametrize(
    ("slot", "text", "expected_facts"),
    [
        ("total_debt", "Около 1.2 млн.", {"total_debt": 1_200_000}),
        ("monthly_payments", "Плачу 62 тысячи.", {"monthly_payments": 62_000}),
        ("income_status", "Официально 105 тысяч.", {"official_income": 105_000, "income_status": "stable"}),
        ("comfortable_payment", "Мог бы платить 35.", {"comfortable_payment": 35_000}),
        ("delinquency_context", "Просрочек нет.", {"has_arrears": False}),
        ("delinquency_context", "Месяц просрочки.", {"has_arrears": True, "arrears_months": 1.0}),
    ],
)
def test_probe_debt_primary_slot_answers(
    slot: str,
    text: str,
    expected_facts: dict[str, object],
) -> None:
    result = probe_phrase(text, asked_slots=[slot], run_route=False)

    for key, value in expected_facts.items():
        assert result.extracted_facts[key] == value
