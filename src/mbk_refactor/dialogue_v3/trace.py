"""Trace objects for one deterministic dialogue_v3 turn."""

from __future__ import annotations

from dataclasses import asdict, dataclass

from .actions import ActionEvent
from .moves import ActorMove
from .route_session import RouteSession


@dataclass(frozen=True)
class TurnTrace:
    turn_index: int
    selected_route: str
    phase: str
    next_slot: str | None
    terminal_action: str | None
    closed_primary_slots: list[str]
    missing_primary_slots: list[str]
    move_type: str
    event_action_ids: list[str]
    writer_mode: str = "deterministic_fallback"

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def build_turn_trace(
    *,
    turn_index: int,
    route_session: RouteSession,
    move: ActorMove,
    events: list[ActionEvent],
    writer_mode: str = "deterministic_fallback",
) -> TurnTrace:
    """Capture the minimal debug contract needed by tests and UI later."""

    return TurnTrace(
        turn_index=turn_index,
        selected_route=route_session.selected_route,
        phase=route_session.phase,
        next_slot=route_session.next_slot,
        terminal_action=route_session.terminal_action,
        closed_primary_slots=list(route_session.closed_primary_slots),
        missing_primary_slots=list(route_session.missing_primary_slots),
        move_type=move.move_type,
        event_action_ids=[event.action_id for event in events],
        writer_mode=writer_mode,
    )
