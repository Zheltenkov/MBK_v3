"""Debug helpers for inspecting one dialogue_v3 user phrase.

This module is intentionally outside the runtime engine. It reuses the
production deterministic core to show where a phrase is interpreted: extraction,
state merge, CaseFrame, route session, or actor move planning.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from .case_frame import build_case_frame
from .facts import FactValue, extract_turn
from .moves import plan_actor_move
from .route_session import build_route_session
from .routes import select_route
from .state import DialogueV3State
from .understanding.text import normalize_text


@dataclass
class PhraseProbeResult:
    """Debug-only result for deterministic phrase interpretation."""

    input_text: str
    normalized_text: str
    extracted_facts: dict[str, Any] = field(default_factory=dict)
    customer_concerns: list[str] = field(default_factory=list)
    service_signal: str | None = None
    off_topic: str | None = None
    route_rejection: str | None = None
    direct_question: str | None = None
    state_facts_after_merge: dict[str, Any] = field(default_factory=dict)
    conflicting_facts: dict[str, Any] = field(default_factory=dict)
    case_frame: dict[str, Any] = field(default_factory=dict)
    selected_route: str | None = None
    phase: str | None = None
    next_slot: str | None = None
    terminal_action: str | None = None
    actor_move_type: str | None = None
    warnings: list[str] = field(default_factory=list)


def probe_phrase(
    text: str,
    *,
    known_facts: dict[str, Any] | None = None,
    asked_slots: list[str] | None = None,
    session_id: str = "phrase-probe",
    turn_index: int = 1,
    run_route: bool = True,
) -> PhraseProbeResult:
    """Inspect how dialogue_v3 interprets one phrase using deterministic logic.

    The probe creates an isolated state, loads supplied context, runs the same
    extractor and merge path as the runtime engine, and optionally builds the
    downstream CaseFrame, route session, and ActorMove. It does not call writer,
    LLMs, action emitters, CRM, or any external side effects.
    """

    state = DialogueV3State(session_id=session_id)
    previous_turn = max(turn_index - 1, 0)
    state.turn_index = previous_turn

    # Load known context as pre-existing user facts.
    for key, value in (known_facts or {}).items():
        state.facts[key] = FactValue(
            value=value,
            quality="exact",
            source="user",
            updated_at_turn=previous_turn,
        )

    # Preserve asked-slot order because several deterministic extractors depend
    # on the last asked slot for contextual amount/property interpretation.
    for slot in asked_slots or []:
        if slot not in state.asked_slots:
            state.asked_slots.append(slot)

    extracted = extract_turn(
        text,
        turn_index=turn_index,
        state=state,
    )

    state.turn_index = turn_index
    state.merge_extracted_turn(extracted)

    merged_facts, conflicting_facts = _snapshot_state_facts(state)
    result = PhraseProbeResult(
        input_text=text,
        normalized_text=normalize_text(text),
        extracted_facts=dict(extracted.facts),
        customer_concerns=list(extracted.customer_concerns),
        service_signal=extracted.service_signal,
        off_topic=extracted.off_topic,
        route_rejection=extracted.route_rejection,
        direct_question=extracted.direct_question,
        state_facts_after_merge=merged_facts,
        conflicting_facts=conflicting_facts,
    )
    _add_probe_warnings(result)

    if not run_route:
        return result

    frame = build_case_frame(state)
    selected_route = select_route(frame, state)
    route_session = build_route_session(
        selected_route,
        state=state,
        frame=frame,
    )
    actor_move = plan_actor_move(
        route_session,
        frame=frame,
        state=state,
    )

    result.case_frame = asdict(frame)
    result.selected_route = selected_route
    result.phase = route_session.phase
    result.next_slot = route_session.next_slot
    result.terminal_action = route_session.terminal_action
    result.actor_move_type = actor_move.move_type
    return result


def _snapshot_state_facts(
    state: DialogueV3State,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return readable fact snapshots without exposing FactValue wrappers."""

    merged_facts: dict[str, Any] = {}
    conflicting_facts: dict[str, Any] = {}
    for key, fact in state.facts.items():
        merged_facts[key] = fact.value
        if fact.quality == "conflicting":
            conflicting_facts[key] = {
                "value": fact.value,
                "source": fact.source,
                "updated_at_turn": fact.updated_at_turn,
            }
    return merged_facts, conflicting_facts


def _add_probe_warnings(result: PhraseProbeResult) -> None:
    """Flag common suspicious interpretations for manual debugging."""

    if (
        "monthly_payments" in result.extracted_facts
        and "comfortable_payment" in result.extracted_facts
    ):
        result.warnings.append("same_turn_monthly_and_comfortable_payment_extracted")
    if result.conflicting_facts:
        result.warnings.append("state_has_conflicting_facts")
