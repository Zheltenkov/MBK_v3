"""Property and mortgage-collateral semantic extraction for dialogue_v3 turns."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from ..constants import MORTGAGE_AUX, MORTGAGE_MAIN
from .amounts import get_last_asked_slot
from .text import contains_any, matches_any_regex

if TYPE_CHECKING:
    from ..state import DialogueV3State

EXPLICIT_MORTGAGE_PATTERNS = (
    "под залог квартиры",
    "под залог квартиру",
    "под залог недвижимости",
    "под залог дома",
    "под залог дом",
    "под залог жилья",
    "залог недвижимости",
    "под недвижимость",
    "под квартиру",
    "под дом",
    "под жилье",
)
EXPLICIT_MORTGAGE_REGEXES = (
    re.compile(r"\bпод\s+залог\s+(?:квартир\w*|недвижимост\w*|дом(?:а|ом|у|е)?|жиль\w*)\b"),
    re.compile(
        r"\b(?:рассмотреть|обсудить|оформить)\b.{0,40}"
        r"\bпод\s+(?:квартир\w*|недвижимост\w*|дом(?:а|ом|у|е)?|жиль\w*)\b"
    ),
)
MORTGAGE_REJECTION_PATTERNS = (
    "квартиру не трогаем",
    "квартиру в залог не рассматриваю",
    "квартира в залог не рассматривается",
    "залог недвижимости не рассматриваю",
    "не хочу использовать квартиру",
    "недвижимость не должна участвовать",
)
PROPERTY_WORD_PATTERNS = ("квартир", "дом", "недвижим", "жиль")
PROPERTY_POSITIVE_PATTERNS = (
    "квартира есть",
    "есть квартира",
    "квартира в собственности",
    "в собственности квартира",
    "дом есть",
    "есть дом",
    "дом в собственности",
    "в собственности дом",
    "недвижимость есть",
    "есть недвижимость",
    "недвижимость в собственности",
    "в собственности недвижимость",
    "жилье есть",
    "есть жилье",
    "жилье в собственности",
    "в собственности жилье",
)
PROPERTY_NEGATIVE_PATTERNS = (
    "квартиры нет",
    "нет квартиры",
    "дома нет",
    "нет дома",
    "недвижимости нет",
    "нет недвижимости",
    "жилья нет",
    "нет жилья",
    "жилья в собственности нет",
    "нет жилья в собственности",
)
PROPERTY_RISK_PATTERNS = (
    "боюсь потерять",
    "страшно потерять",
    "боюсь за квартиру",
    "страх за квартиру",
    "страшно за жилье",
    "квартиру потерять не хочу",
    "жилье потерять не хочу",
    "квартиру потерять боюсь",
    "потерять жилье боюсь",
    "потерять ее боюсь",
    "потерять квартиру боюсь",
)
PROPERTY_RISK_REGEXES = (
    re.compile(r"\bквартир\w*\b.{0,30}\bпотерять\b.{0,30}\bне\s+хоч"),
    re.compile(r"\bжиль\w*\b.{0,30}\bпотерять\b.{0,30}\bне\s+хоч"),
)
PROPERTY_SELF_OWNER_PATTERNS = (
    "оформлена на меня",
    "оформлен на меня",
    "я собственник",
    "собственник я",
    "я единственный собственник",
    "я владелец",
    "я владелица",
    "на мне",
    "моя",
    "мой",
)
PROPERTY_THIRD_PARTY_OWNER_PATTERNS = (
    "на жене",
    "на супруге",
    "на муже",
    "на супруге",
    "на маме",
    "на матери",
    "на отце",
    "на папе",
    "на родител",
)
PROPERTY_REGION_ALIASES: tuple[tuple[tuple[str, ...], str], ...] = (
    (("москва", "москве", "московская область", "московской области"), "Москва"),
    (
        ("санкт-петербург", "санкт-петербурге", "спб", "питер", "питере", "ленинградская область"),
        "Санкт-Петербург",
    ),
    (("нижний новгород", "нижнем новгороде"), "Нижний Новгород"),
    (("самара", "самаре"), "Самара"),
)
PROPERTY_ENCUMBRANCE_CLEAR_PATTERNS = (
    "без обременений",
    "обременений нет",
    "ипотеки нет",
    "залога нет",
    "ареста нет",
    "ограничений нет",
    "ничего нет",
)
PROPERTY_MORTGAGE_POSITIVE_PATTERNS = ("есть ипотека", "ипотека есть", "в ипотеке")
PROPERTY_PLEDGE_POSITIVE_PATTERNS = ("есть залог", "залог есть", "в залоге")
PROPERTY_ARREST_POSITIVE_PATTERNS = ("есть арест", "арест есть", "есть ограничения", "ограничения есть")
PROPERTY_MAIN_REGION_MARKERS = ("москва", "москов", "санкт", "спб", "петербург")


def has_explicit_mortgage_intent(text: str) -> bool:
    """Detect a mortgage/property collateral channel without choosing a route."""

    return contains_any(text, EXPLICIT_MORTGAGE_PATTERNS) or matches_any_regex(
        text, EXPLICIT_MORTGAGE_REGEXES
    )


def has_property_collateral_refusal(text: str) -> bool:
    """Detect hard property-collateral refusal, not a risk concern."""

    return contains_any(text, MORTGAGE_REJECTION_PATTERNS)


def extract_property_facts(
    text: str,
    facts: dict[str, Any],
    concerns: list[str],
    state: DialogueV3State | None,
) -> None:
    _extract_property_facts(text, facts, concerns, state)


def _extract_property_facts(
    text: str,
    facts: dict[str, Any],
    concerns: list[str],
    state: DialogueV3State | None,
) -> None:
    _extract_slot_local_property_answer(text, facts, state)

    property_word_present = contains_any(text, PROPERTY_WORD_PATTERNS)
    explicit_mortgage_intent = has_explicit_mortgage_intent(text)
    property_available = contains_any(text, PROPERTY_POSITIVE_PATTERNS)
    property_negative = contains_any(text, PROPERTY_NEGATIVE_PATTERNS)
    mortgage_slot_context = _has_mortgage_property_slot_context(state)
    owner_signal = contains_any(
        text, PROPERTY_SELF_OWNER_PATTERNS + PROPERTY_THIRD_PARTY_OWNER_PATTERNS + ("собственник готов участвовать",)
    )
    property_owner_context = property_word_present or facts.get("has_property") is True or mortgage_slot_context
    owner_value = _slot_local_property_owner(text) if property_owner_context else None
    if owner_value is not None:
        facts["property_owner_known"] = True
        facts["property_owner"] = owner_value
        facts["has_property"] = True
        if owner_value == "third_party":
            facts["third_party_property_owner"] = True
            facts["property_owner_red_flag"] = True
    owner_known = bool(facts.get("property_owner_known")) or (
        owner_signal and property_owner_context
    )

    if property_available or (property_word_present and owner_known and not property_negative):
        facts["has_property"] = True
    elif property_negative and not property_available:
        facts["has_property"] = False

    has_property_context = facts.get("has_property") is True or owner_known
    if has_property_context and _property_type_is_descriptive(text, "квартира"):
        facts["property_type"] = "apartment"
    elif has_property_context and _property_type_is_descriptive(text, "дом"):
        facts["property_type"] = "house"
    elif mortgage_slot_context and _property_type_is_descriptive(text, "квартира"):
        facts["property_type"] = "apartment"
    elif mortgage_slot_context and _property_type_is_descriptive(text, "дом"):
        facts["property_type"] = "house"
    elif mortgage_slot_context and _property_type_is_descriptive(text, "комната"):
        facts["property_type"] = "room"
    elif explicit_mortgage_intent:
        collateral_property_type = _slot_local_property_type(text)
        if collateral_property_type is not None:
            facts["property_type"] = collateral_property_type
    _mark_property_type_red_flags(text, facts)

    property_region = _extract_known_property_region(text)
    if property_region is not None:
        facts["property_region"] = property_region
        _set_property_region_support(facts, property_region)

    if owner_known and "property_owner" not in facts:
        facts["property_owner_known"] = True
        facts["property_owner"] = "known"
        if property_word_present and not property_negative:
            facts["has_property"] = True

    if property_word_present or facts.get("has_property") is True or mortgage_slot_context:
        _extract_property_encumbrance(text, facts)

    if contains_any(text, PROPERTY_RISK_PATTERNS) or matches_any_regex(text, PROPERTY_RISK_REGEXES):
        facts["property_risk_concern"] = True
        facts["property_refuses_collateral"] = False
        concerns.append("property_risk")


def _extract_slot_local_property_answer(
    text: str,
    facts: dict[str, Any],
    state: DialogueV3State | None,
) -> None:
    """Interpret short answers only when backend has asked a property slot."""

    asked_slot = get_last_asked_slot(state)
    if asked_slot == "property_type":
        property_type = _slot_local_property_type(text)
        if property_type is not None:
            facts["property_type"] = property_type
            facts["has_property"] = True
            _mark_property_type_red_flags(text, facts)
        region = _extract_known_property_region(text)
        if region is not None:
            facts["property_region"] = region
            _set_property_region_support(facts, region)

    if asked_slot == "property_region":
        region = _slot_local_property_region(text)
        if region is not None:
            facts["property_region"] = region
            _set_property_region_support(facts, region)

    if asked_slot == "property_owner_or_ownership":
        owner = _slot_local_property_owner(text)
        if owner is not None:
            facts["property_owner_known"] = True
            facts["property_owner"] = owner
            facts["has_property"] = True
            if owner == "third_party":
                facts["third_party_property_owner"] = True
                facts["property_owner_red_flag"] = True

    if asked_slot == "property_encumbrance_basic":
        _extract_property_encumbrance(text, facts, assume_complete_negative=True)

    if asked_slot == "bfl_property_context":
        property_type = _slot_local_property_type(text)
        if property_type is not None:
            facts["property_type"] = property_type
            facts["has_property"] = True
            _mark_property_type_red_flags(text, facts)
        region = _extract_known_property_region(text)
        if region is not None:
            facts["property_region"] = region
            _set_property_region_support(facts, region)
        owner = _slot_local_property_owner(text)
        if owner is not None:
            facts["property_owner_known"] = True
            facts["property_owner"] = owner
            facts["has_property"] = True
            if owner == "third_party":
                facts["third_party_property_owner"] = True
                facts["property_owner_red_flag"] = True
        _extract_property_encumbrance(text, facts, assume_complete_negative=True)
        if _has_only_housing_signal(text):
            facts["is_only_housing"] = True
        elif contains_any(text, ("не единственное жилье", "есть еще жилье", "есть вторая квартира")):
            facts["is_only_housing"] = False
        if (
            facts.get("property_type") is not None
            and facts.get("property_region") is not None
            and facts.get("property_owner_known") is True
            and facts.get("property_encumbrance") is not None
            and facts.get("is_only_housing") is not None
        ):
            facts["bfl_property_context_known"] = True


def _slot_local_property_type(text: str) -> str | None:
    if contains_any(text, PROPERTY_NEGATIVE_PATTERNS + PROPERTY_RISK_PATTERNS):
        return None
    if contains_any(text, ("муниципальное жилье", "муниципальная квартира", "соцнайм")):
        return "municipal_housing"
    if re.search(r"\bдол[яи]\b", text):
        return "share"
    if re.search(r"\bквартир\w*\b", text) or re.search(r"\bапартамент\w*\b", text):
        return "apartment"
    if re.search(r"\bдом(?:а|ом|у|е)?\b", text):
        return "house"
    if re.search(r"\bкомнат\w*\b", text):
        return "room"
    return None


def _slot_local_property_region(text: str) -> str | None:
    known_region = _extract_known_property_region(text)
    if known_region is not None:
        return known_region
    if not _looks_like_short_region_answer(text):
        return None
    cleaned = re.sub(r"^(в|во|г\.?|город)\s+", "", text.strip(" .,!?:;"))
    return _title_ru_phrase(cleaned)


def _slot_local_property_owner(text: str) -> str | None:
    if contains_any(text, PROPERTY_SELF_OWNER_PATTERNS):
        return "client"
    if contains_any(text, PROPERTY_THIRD_PARTY_OWNER_PATTERNS):
        return "third_party"
    return None


def _extract_known_property_region(text: str) -> str | None:
    for patterns, canonical_region in PROPERTY_REGION_ALIASES:
        if contains_any(text, patterns):
            return canonical_region
    return None


def _set_property_region_support(facts: dict[str, Any], region: str) -> None:
    normalized_region = region.lower().replace("ё", "е")
    supported = any(marker in normalized_region for marker in PROPERTY_MAIN_REGION_MARKERS)
    facts["property_region_supported"] = supported
    if not supported:
        facts["property_region_red_flag"] = True


def _mark_property_type_red_flags(text: str, facts: dict[str, Any]) -> None:
    property_type = facts.get("property_type")
    if property_type == "municipal_housing" or contains_any(
        text,
        ("муниципальное жилье", "муниципальная квартира", "соцнайм"),
    ):
        facts["property_municipal_housing"] = True
        facts["property_object_red_flag"] = True
        facts["municipal_housing_red_flag"] = True
    if property_type == "share" or re.search(r"\bдол[яи]\b", text):
        facts["property_share"] = True
        facts["property_object_red_flag"] = True
        facts["property_share_red_flag"] = True
    if property_type == "room":
        facts["property_room_red_flag"] = True
        facts["property_object_red_flag"] = True


def _looks_like_short_region_answer(text: str) -> bool:
    cleaned = re.sub(r"^(в|во|г\.?|город)\s+", "", text.strip(" .,!?:;"))
    if not re.search(r"[а-яa-z]", cleaned):
        return False
    if re.search(r"\d", cleaned):
        return False
    if len(cleaned.split()) > 3:
        return False
    return not contains_any(
        cleaned,
        (
            "да",
            "нет",
            "не знаю",
            "ипотек",
            "залог",
            "арест",
            "обремен",
            "собственник",
        ),
    )


def _title_ru_phrase(text: str) -> str:
    return " ".join(token[:1].upper() + token[1:] for token in text.split())


def _extract_property_encumbrance(
    text: str,
    facts: dict[str, Any],
    *,
    assume_complete_negative: bool = False,
) -> None:
    mortgage_negative = contains_any(text, ("ипотеки нет", "ипотека отсутствует", "без ипотеки")) or bool(
        re.search(r"\bипотек\w*.{0,50}\bнет\b", text)
    )
    pledge_negative = contains_any(text, ("залога нет", "не в залоге", "без залога")) or bool(
        re.search(r"\bзалог\w*.{0,50}\bнет\b", text)
    )
    arrest_negative = contains_any(
        text,
        ("ареста нет", "без ареста", "ограничений нет", "без ограничений"),
    ) or bool(re.search(r"\b(?:арест\w*|огранич\w*).{0,50}\bнет\b", text))
    clear_negative = contains_any(text, PROPERTY_ENCUMBRANCE_CLEAR_PATTERNS)

    mortgage_positive = contains_any(text, PROPERTY_MORTGAGE_POSITIVE_PATTERNS) and not mortgage_negative
    pledge_positive = contains_any(text, PROPERTY_PLEDGE_POSITIVE_PATTERNS) and not pledge_negative
    arrest_positive = contains_any(text, PROPERTY_ARREST_POSITIVE_PATTERNS) and not arrest_negative

    if mortgage_positive:
        facts["property_encumbrance"] = True
        facts["property_mortgage"] = True
        facts["property_encumbrance_type"] = "mortgage"
        facts["property_encumbrance_red_flag"] = True
    if pledge_positive:
        facts["property_encumbrance"] = True
        facts["property_pledge"] = True
        facts["property_encumbrance_type"] = "pledge"
        facts["property_encumbrance_red_flag"] = True
        facts["property_pledge_red_flag"] = True
    if arrest_positive:
        facts["property_encumbrance"] = True
        facts["property_arrest"] = True
        facts["property_encumbrance_type"] = "arrest_or_restriction"
        facts["property_encumbrance_red_flag"] = True
        facts["property_arrest_red_flag"] = True

    has_negative_signal = clear_negative or mortgage_negative or pledge_negative or arrest_negative
    if has_negative_signal and not (mortgage_positive or pledge_positive or arrest_positive):
        facts["property_encumbrance"] = False
        if assume_complete_negative or clear_negative:
            facts["property_mortgage"] = False
            facts["property_pledge"] = False
            facts["property_arrest"] = False
            facts["property_pledge_red_flag"] = False
            facts["property_arrest_red_flag"] = False
        else:
            if mortgage_negative:
                facts["property_mortgage"] = False
            if pledge_negative:
                facts["property_pledge"] = False
                facts["property_pledge_red_flag"] = False
            if arrest_negative:
                facts["property_arrest"] = False
                facts["property_arrest_red_flag"] = False


def _has_mortgage_property_slot_context(state: DialogueV3State | None) -> bool:
    if state is None:
        return False
    if get_last_asked_slot(state) == "property_type":
        return True
    route = getattr(state, "route", None)
    return getattr(route, "selected_route", None) in {MORTGAGE_MAIN, MORTGAGE_AUX}


def _has_only_housing_signal(text: str) -> bool:
    return bool(
        contains_any(
            text,
            (
                "единственная квартира",
                "единственное жилье",
                "единственное жильё",
                "единственный объект",
            ),
        )
        or re.search(r"\bквартир\w*.{0,30}\bединствен\w*\b", text)
        or re.search(r"\bединствен\w*.{0,30}\bквартир\w*\b", text)
    )


def _property_type_is_descriptive(text: str, property_word: str) -> bool:
    if property_word == "дом":
        if not re.search(r"\bдом\b", text):
            return False
    elif property_word == "комната":
        if not re.search(r"\bкомнат\w*\b", text):
            return False
    elif property_word not in text:
        return False
    intent_patterns = {
        "квартира": ("под квартиру", "рассмотреть под квартиру"),
        "дом": ("под дом", "рассмотреть под дом"),
        "комната": ("под комнату", "рассмотреть под комнату"),
    }
    if contains_any(text, intent_patterns.get(property_word, ())):
        return False
    return True
