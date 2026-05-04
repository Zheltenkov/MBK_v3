"""Fact contracts and lightweight deterministic extraction for dialogue_v3."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Literal, Mapping

FactQuality = Literal["unknown", "approx", "exact", "conflicting", "not_applicable"]
FactSource = Literal["user", "form", "derived", "llm_extractor"]


@dataclass(frozen=True)
class FactValue:
    """A canonical fact with provenance and merge quality."""

    value: Any
    quality: FactQuality = "exact"
    source: FactSource = "user"
    updated_at_turn: int = 0


@dataclass
class ExtractedTurn:
    """Lightweight container for facts and non-routing turn signals."""

    facts: dict[str, Any] = field(default_factory=dict)
    direct_question: str | None = None
    off_topic: str | None = None
    customer_concerns: list[str] = field(default_factory=list)
    service_signal: str | None = None
    route_rejection: str | None = None
    raw_user_text: str = ""


def merge_fact(old: FactValue | None, new: FactValue) -> FactValue:
    """Merge a new fact without silently overwriting stronger evidence."""

    if old is None:
        return new
    if old.value == new.value:
        return old
    if old.quality == "unknown":
        return new
    if new.quality == "exact" and old.quality == "approx":
        return new
    return FactValue(
        value=old.value,
        quality="conflicting",
        source=old.source,
        updated_at_turn=new.updated_at_turn,
    )


def coerce_fact_value(
    value: Any,
    *,
    turn_index: int,
    source: FactSource = "user",
    quality: FactQuality = "exact",
) -> FactValue:
    """Wrap raw values so state stores one canonical fact representation."""

    if isinstance(value, FactValue):
        return value
    return FactValue(value=value, quality=quality, source=source, updated_at_turn=turn_index)


def extract_turn(user_message: str, *, turn_index: int = 0) -> ExtractedTurn:
    """Extract obvious Step 1 facts by deterministic rules only."""

    text = _normalize_text(user_message)
    facts: dict[str, Any] = {"last_user_text": user_message}
    concerns: list[str] = []

    service_signal = _detect_service_signal(text)
    if service_signal:
        facts["service_signal"] = service_signal

    off_topic = _detect_off_topic(text)
    if off_topic:
        facts["off_topic_kind"] = off_topic

    # Route-shaping facts stay simple and auditable at Step 1.
    _extract_property_facts(text, facts, concerns)
    _extract_vehicle_facts(text, facts, concerns)
    _extract_debt_and_income_facts(text, facts, concerns)

    direct_question = user_message.strip() if "?" in user_message else None

    route_rejection = _detect_route_rejection(text)
    if route_rejection:
        facts["route_rejection"] = route_rejection

    return ExtractedTurn(
        facts=facts,
        direct_question=direct_question,
        off_topic=off_topic,
        customer_concerns=concerns,
        service_signal=service_signal,
        route_rejection=route_rejection,
        raw_user_text=user_message,
    )


def fact_values_from_mapping(
    facts: Mapping[str, Any],
    *,
    turn_index: int,
    source: FactSource = "user",
) -> dict[str, FactValue]:
    """Convert raw extracted facts into canonical values."""

    return {
        key: coerce_fact_value(value, turn_index=turn_index, source=source)
        for key, value in facts.items()
    }


def _normalize_text(text: str) -> str:
    return " ".join(text.lower().replace("ё", "е").split())


def _contains_any(text: str, patterns: tuple[str, ...]) -> bool:
    return any(pattern in text for pattern in patterns)


def _detect_service_signal(text: str) -> str | None:
    fraud_patterns = (
        "просили код",
        "попросили код",
        "код из смс",
        "смс-код",
        "смс код",
        "я ничего не оформлял",
        "заявка не моя",
        "на меня оформили",
        "мошенники позвонили",
        "ao_mbk",
    )
    repeat_patterns = (
        "я уже обращался",
        "я уже обращалась",
        "я уже писал",
        "я уже писала",
        "мне не ответили",
        "продолжить заявку",
        "по старой заявке",
        "раньше обращалась",
        "раньше обращался",
        "изменился доход",
        "появились просрочки",
    )
    if _contains_any(text, fraud_patterns):
        return "fraud_check"
    if _contains_any(text, repeat_patterns):
        return "repeat_visit"
    return None


def _detect_off_topic(text: str) -> str | None:
    if _contains_any(
        text,
        (
            "напиши код",
            "python",
            "switch to english",
            "забудь инструкции",
            "переведи",
            "расскажи историю",
        ),
    ):
        return "off_topic_request"
    if _contains_any(text, ("ты бот", "ты ии")):
        return "assistant_identity"
    return None


def _detect_route_rejection(text: str) -> str | None:
    if _contains_any(
        text,
        (
            "птс не рассматриваю",
            "не хочу залог на машину",
            "машина вообще не должна участвовать",
            "никаких автозалогов",
            "авто не трогаем",
        ),
    ):
        return "PTS"
    if _contains_any(
        text,
        (
            "квартиру не трогаем",
            "залог недвижимости не рассматриваю",
            "не хочу использовать квартиру",
            "недвижимость не должна участвовать",
        ),
    ):
        return "MORTGAGE"
    return None


def _extract_property_facts(text: str, facts: dict[str, Any], concerns: list[str]) -> None:
    if _contains_any(text, ("квартира", "дом", "недвижимость", "жилье", "жилье")):
        facts["has_property"] = True

    if "квартира" in text:
        facts["property_type"] = "apartment"
    elif re.search(r"\bдом\b", text):
        facts["property_type"] = "house"

    if _contains_any(text, ("москва", "московская область", "московской области")):
        facts["property_region"] = "Москва"
    elif _contains_any(text, ("санкт-петербург", "спб", "питер", "ленинградская область")):
        facts["property_region"] = "Санкт-Петербург"

    if _contains_any(
        text,
        (
            "оформлена на меня",
            "оформлен на меня",
            "я собственник",
            "я единственный собственник",
            "собственник готов участвовать",
        ),
    ):
        facts["property_owner_known"] = True
        facts["property_owner"] = "known"

    if _contains_any(text, ("без обременений", "ипотеки нет", "залога нет", "ареста нет")):
        facts["property_encumbrance"] = False
        facts["property_mortgage"] = False
        facts["property_pledge"] = False
        facts["property_arrest"] = False

    if _contains_any(
        text,
        (
            "боюсь потерять",
            "страшно потерять",
            "боюсь за квартиру",
            "страх за квартиру",
            "потерять жилье боюсь",
            "потерять ее боюсь",
            "потерять квартиру боюсь",
        ),
    ):
        facts["property_risk_concern"] = True
        facts["property_refuses_collateral"] = False
        concerns.append("property_risk")

    if _detect_route_rejection(text) == "MORTGAGE":
        facts["property_refuses_collateral"] = True


def _extract_vehicle_facts(text: str, facts: dict[str, Any], concerns: list[str]) -> None:
    if _contains_any(text, ("авто", "машин", "птс", "kia", "hyundai", "лада", "ваз", "toyota")):
        facts["has_car"] = True

    raw_car_match = re.search(
        r"\b(kia rio|hyundai tucson|лада веста|toyota camry|ваз \d{4})\b",
        text,
    )
    if raw_car_match:
        facts["raw_car_name"] = raw_car_match.group(1)
        facts["car_brand_model_known"] = True

    year_match = re.search(r"\b(19[8-9]\d|20[0-2]\d)\b", text)
    if year_match:
        facts["car_year"] = int(year_match.group(1))

    if "я собственник" in text and facts.get("has_car"):
        facts["car_owner_known"] = True
        facts["car_owner"] = "client"

    if _contains_any(
        text,
        (
            "машину отдавать не буду",
            "авто отдавать не буду",
            "машина нужна",
            "она для работы",
            "авто нужно",
        ),
    ):
        facts["vehicle_requires_retention"] = True
        facts["vehicle_refuses_transfer"] = True
        facts["vehicle_refuses_collateral"] = False
        concerns.append("vehicle_retention")

    if _detect_route_rejection(text) == "PTS":
        facts["vehicle_refuses_collateral"] = True

    if _contains_any(
        text,
        (
            "не в залоге и ограничений нет",
            "кредитов по машине нет",
            "арестов по машине нет",
            "ограничений по машине нет",
        ),
    ):
        facts["car_in_pledge"] = False
        facts["car_arrest_or_restriction"] = False


def _extract_debt_and_income_facts(text: str, facts: dict[str, Any], concerns: list[str]) -> None:
    if _contains_any(text, ("кредит", "кредиты", "карты", "долг", "долги", "мфо", "займ")):
        facts["has_current_loans"] = True

    if _contains_any(text, ("мфо", "микрозайм", "микрозаймы")):
        facts["has_mfo"] = True

    total_debt = _find_amount_near(text, ("долг", "долги", "задолженность"))
    if total_debt is not None:
        facts["total_debt"] = total_debt

    desired_amount = _find_amount_near(text, ("нужн", "хочу", "сумма", "деньги"))
    if desired_amount is not None:
        facts["desired_amount"] = desired_amount

    monthly_payments = _find_amount_near(text, ("плачу", "платеж", "платежи"))
    if monthly_payments is not None:
        facts["monthly_payments"] = monthly_payments

    comfortable_payment = _find_amount_near(text, ("комфортно", "могу платить"))
    if comfortable_payment is not None:
        facts["comfortable_payment"] = comfortable_payment

    income = _find_amount_near(text, ("доход", "заработ", "получаю"))
    if income is not None:
        facts["official_income"] = income
        facts["income_status"] = "stable"

    if _contains_any(text, ("дохода стабильного нет", "нет стабильного дохода")):
        facts["income_status"] = "unstable"
    if _contains_any(text, ("официального дохода нет", "неофициальный доход")):
        facts["income_status"] = "no_official_income"
    if _contains_any(text, ("дохода нет", "без дохода")):
        facts["income_status"] = "none"

    if _contains_any(text, ("просроч", "не плачу", "пропустил", "пропустила")):
        facts["has_arrears"] = True
        arrears_months = _extract_month_count(text)
        if arrears_months is not None:
            facts["arrears_months"] = arrears_months
    if _contains_any(text, ("просрочек нет", "без просрочек")):
        facts["has_arrears"] = False

    if "коллектор" in text:
        facts["collector_pressure"] = True

    if _contains_any(text, ("нагрузка", "платежи большие", "платить тяжело")):
        facts["high_payment_load"] = True

    if _contains_any(text, ("банкротство не хочу", "хочу платить", "не списывать", "законный график")):
        facts["client_wants_to_pay"] = True
    if _contains_any(text, ("банкротство пугает", "боюсь банкротства")):
        facts["client_fears_bankruptcy"] = True
        concerns.append("bankruptcy_fear")
    if _contains_any(
        text,
        (
            "банкротство не рассматриваю",
            "суды не рассматриваю",
            "никаких процедур",
            "не хочу юридический разбор долгов",
        ),
    ):
        facts["client_refuses_debt_procedure"] = True

    if _contains_any(text, ("закрыть карты", "закрыть кредиты", "снизить платеж", "платеж меньше")):
        facts["need_type"] = "payment_reduction"
    elif _contains_any(text, ("мфо", "коллектор", "банкрот", "долг", "долги")):
        facts["need_type"] = "debt_solution"
    elif _contains_any(text, ("нужны деньги", "нужна сумма", "хочу кредит", "под птс")):
        facts["need_type"] = "new_money"

    monthly = facts.get("monthly_payments")
    official_income = facts.get("official_income")
    comfortable = facts.get("comfortable_payment")
    if isinstance(monthly, int) and isinstance(official_income, int) and official_income > 0:
        facts["high_payment_load"] = monthly / official_income >= 0.5
    if isinstance(monthly, int) and isinstance(comfortable, int):
        facts["payment_gap_large"] = monthly > comfortable * 1.5


def _find_amount_near(text: str, keywords: tuple[str, ...]) -> int | None:
    amount_pattern = re.compile(r"(\d+(?:[,.]\d+)?)\s*(млн|миллион|миллиона|тыс|к|руб|₽)?")
    for keyword in keywords:
        index = text.find(keyword)
        if index == -1:
            continue
        window = text[index : index + 80]
        match = amount_pattern.search(window)
        if match:
            return _parse_amount(match.group(1), match.group(2))
    return None


def _parse_amount(number: str, unit: str | None) -> int:
    value = float(number.replace(",", "."))
    if unit in {"млн", "миллион", "миллиона"}:
        value *= 1_000_000
    elif unit in {"тыс", "к"}:
        value *= 1_000
    return int(value)


def _extract_month_count(text: str) -> float | None:
    match = re.search(r"(\d+(?:[,.]\d+)?)\s*(месяц|месяца|месяцев)", text)
    if not match:
        return None
    return float(match.group(1).replace(",", "."))
