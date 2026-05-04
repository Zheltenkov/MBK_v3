"""Deterministic dialogue_v3 runtime for the MBK assistant."""

__all__ = [
    "ActorWriter",
    "DialogueV3Engine",
    "DialogueV3State",
    "DialogueV3TurnResult",
    "ResponseGuard",
]


def __getattr__(name: str):
    """Lazily expose public classes without package import cycles."""

    if name == "ActorWriter":
        from .actor_writer import ActorWriter

        return ActorWriter
    if name in {"DialogueV3Engine", "DialogueV3TurnResult"}:
        from .engine import DialogueV3Engine, DialogueV3TurnResult

        return {"DialogueV3Engine": DialogueV3Engine, "DialogueV3TurnResult": DialogueV3TurnResult}[name]
    if name == "ResponseGuard":
        from .response_guard import ResponseGuard

        return ResponseGuard
    if name == "DialogueV3State":
        from .state import DialogueV3State

        return DialogueV3State
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
