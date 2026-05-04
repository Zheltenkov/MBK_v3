"""Action event stubs for terminal dialogue_v3 moves."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .moves import ActorMove
from .state import DialogueV3State


@dataclass(frozen=True)
class ActionEvent:
    action_id: str
    selected_route: str
    payload: dict[str, Any]


def execute_if_needed(move: ActorMove, state: DialogueV3State) -> list[ActionEvent]:
    """Create a terminal event stub when backend selected an action."""

    if not move.terminal_action:
        return []
    action_key = f"{move.selected_route}:{move.terminal_action}"
    if action_key in state.emitted_terminal_actions:
        return []
    state.emitted_terminal_actions.add(action_key)
    return [
        ActionEvent(
            action_id=move.terminal_action,
            selected_route=move.selected_route,
            payload={
                "session_id": state.session_id,
                "turn_index": state.turn_index,
                "move_type": move.move_type,
            },
        )
    ]
