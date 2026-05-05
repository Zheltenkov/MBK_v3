"""Collateral semantic extraction facade for property and vehicle observations."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ..constants import PTS
from .amounts import get_last_asked_slot
from .need import set_need_signal
from .property import (
    extract_property_facts,
    has_explicit_mortgage_intent,
    has_property_collateral_refusal,
)
from .text import contains_any
from .vehicle import detect_vehicle_intent, extract_vehicle_facts

if TYPE_CHECKING:
    from ..state import DialogueV3State

PROPERTY_COLLATERAL_CONSIDERATION_PATTERNS = (
    "недвижимость можно",
    "недвижимость готов",
    "недвижимость как вариант",
    "квартиру можно",
    "квартиру готов",
    "квартира как вариант",
    "дом можно",
    "дом готов",
    "дом как вариант",
)


def extract_collateral_signals(
    text: str,
    facts: dict[str, Any],
    concerns: list[str],
    state: DialogueV3State | None = None,
) -> None:
    """Extract collateral facts and concerns without choosing a route."""

    if has_explicit_mortgage_intent(text) or _has_slot_local_property_collateral_consideration(text, state):
        facts["explicit_mortgage_intent"] = True
        set_need_signal(facts, "explicit_mortgage")

    extract_property_facts(text, facts, concerns, state)
    vehicle_evidence = detect_vehicle_intent(text, state)
    extract_vehicle_facts(text, facts, concerns, state, vehicle_evidence)

    if vehicle_evidence.hard_collateral_refusal:
        facts["route_rejection"] = PTS
        facts["vehicle_refuses_collateral"] = True
    if has_property_collateral_refusal(text):
        facts["route_rejection"] = "MORTGAGE"
        facts["property_refuses_collateral"] = True


def _has_slot_local_property_collateral_consideration(
    text: str,
    state: DialogueV3State | None,
) -> bool:
    """Treat a positive property answer as mortgage intent only in collateral slot context."""

    return bool(
        get_last_asked_slot(state) == "collateral_preference"
        and contains_any(text, PROPERTY_COLLATERAL_CONSIDERATION_PATTERNS)
        and not has_property_collateral_refusal(text)
    )
