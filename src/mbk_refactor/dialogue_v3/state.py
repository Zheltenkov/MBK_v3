"""Canonical state for the isolated dialogue_v3 runtime."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Mapping

from .facts import ExtractedTurn, FactValue, coerce_fact_value, merge_fact


@dataclass
class ChatMessage:
    """One persisted chat message."""

    role: Literal["user", "assistant"]
    content: str
    turn_index: int


@dataclass
class DialogueV3State:
    """Minimal mutable state owned by the v3 engine."""

    session_id: str
    turn_index: int = 0
    facts: dict[str, FactValue] = field(default_factory=dict)
    route: object | None = None
    messages: list[ChatMessage] = field(default_factory=list)
    asked_slots: list[str] = field(default_factory=list)
    closed_slot_groups: set[str] = field(default_factory=set)
    rejected_routes: set[str] = field(default_factory=set)
    accepted_route: str | None = None
    pending_route: str | None = None
    pending_terminal_action: str | None = None
    service_mode: str = "normal_credit_case"
    trace_history: list[dict[str, object]] = field(default_factory=list)
    emitted_terminal_actions: set[str] = field(default_factory=set)

    def add_user_message(self, content: str) -> None:
        """Persist the user turn after the engine advances turn_index."""

        self.messages.append(ChatMessage(role="user", content=content, turn_index=self.turn_index))

    def add_assistant_message(self, content: str) -> None:
        """Persist a non-empty assistant answer for the same turn."""

        if not content.strip():
            raise ValueError("assistant response must not be empty")
        self.messages.append(ChatMessage(role="assistant", content=content, turn_index=self.turn_index))

    def merge_facts(self, facts: Mapping[str, object], *, source: str = "user") -> None:
        """Merge raw facts into canonical state using FactValue conflict rules."""

        for key, value in facts.items():
            fact = coerce_fact_value(value, turn_index=self.turn_index, source=source)  # type: ignore[arg-type]
            self.facts[key] = merge_fact(self.facts.get(key), fact)

    def merge_extracted_turn(self, extracted: ExtractedTurn) -> None:
        """Apply extracted facts and per-turn signals."""

        # This is a turn-scoped clarification signal; clear it before applying the
        # current extraction so a previous "what next?" does not leak into later turns.
        self.facts.pop("post_terminal_topic", None)
        self.merge_facts(extracted.facts, source="user")

        if extracted.service_signal:
            self.service_mode = extracted.service_signal
        if extracted.route_rejection:
            self.rejected_routes.add(extracted.route_rejection)
        if extracted.direct_question:
            self.merge_facts({"direct_question": extracted.direct_question}, source="user")
        if extracted.off_topic:
            self.merge_facts({"off_topic_kind": extracted.off_topic}, source="user")
        if extracted.customer_concerns:
            self.merge_facts({"customer_concerns": tuple(extracted.customer_concerns)}, source="user")

    def fact_value(self, key: str, default: object | None = None) -> object | None:
        """Return the raw fact value when it is known and usable."""

        fact = self.facts.get(key)
        if fact is None or fact.quality in {"unknown", "not_applicable", "conflicting"}:
            return default
        return fact.value
