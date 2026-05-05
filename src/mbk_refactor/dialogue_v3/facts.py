"""Fact contracts and deterministic extraction facade for dialogue_v3."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal

from .understanding.amounts import (
    _derive_payment_load,
    extract_amounts_with_context as _extract_amounts_with_context,
)
from .understanding.collateral import extract_collateral_signals as _extract_collateral_signals
from .understanding.debt import extract_debt_signals as _extract_debt_signals
from .understanding.need import extract_need_signals as _extract_need_signals
from .understanding.post_terminal import detect_post_terminal_topic as _detect_post_terminal_topic
from .understanding.service import extract_service_signals as _extract_service_signals
from .understanding.text import normalize_text as _normalize_text

if TYPE_CHECKING:
    from .state import DialogueV3State

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


def extract_turn(
    user_message: str,
    *,
    turn_index: int = 0,
    state: DialogueV3State | None = None,
) -> ExtractedTurn:
    """Extract turn facts and non-routing signals by deterministic rules only."""

    text = _normalize_text(user_message)
    facts: dict[str, Any] = {}
    concerns: list[str] = []

    post_terminal_topic = _detect_post_terminal_topic(text)
    if post_terminal_topic:
        facts["post_terminal_topic"] = post_terminal_topic

    service_signal, off_topic = _extract_service_signals(text, facts, concerns, state)
    _extract_need_signals(text, facts)
    _extract_collateral_signals(text, facts, concerns, state)
    _extract_debt_signals(text, facts, concerns, state)
    _extract_amounts_with_context(text, facts, state)
    _derive_payment_load(facts)

    direct_question = user_message.strip() if "?" in user_message else None
    route_rejection = facts.get("route_rejection")

    return ExtractedTurn(
        facts=facts,
        direct_question=direct_question,
        off_topic=off_topic,
        customer_concerns=concerns,
        service_signal=service_signal,
        route_rejection=route_rejection if isinstance(route_rejection, str) else None,
        raw_user_text=user_message,
    )
