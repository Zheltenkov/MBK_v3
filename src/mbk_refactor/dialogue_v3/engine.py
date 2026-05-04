"""Deterministic Step 1 dialogue_v3 engine."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4

from .actions import ActionEvent, execute_if_needed
from .actor_writer import ActorWriter, WriterMode, build_compact_state_summary
from .case_frame import CaseFrame, build_case_frame
from .facts import ExtractedTurn, extract_turn
from .moves import ActorMove, plan_actor_move
from .response_guard import GuardValidation, ResponseGuard
from .route_session import RouteSession, build_route_session
from .routes import select_route
from .safe_fallback import ActorWriterOutput, render_safe_fallback
from .state import DialogueV3State
from .trace import TurnTrace, build_turn_trace


@dataclass
class DialogueV3TurnResult:
    text: str
    state: DialogueV3State
    trace: TurnTrace
    events: list[ActionEvent]
    extracted: ExtractedTurn
    frame: CaseFrame
    route_session: RouteSession
    actor_move: ActorMove
    writer_output: ActorWriterOutput
    writer_validation: GuardValidation
    initial_writer_validation: GuardValidation
    writer_invalid: bool = False
    repair_attempted: bool = False
    fallback_used: bool = False


class DialogueV3Engine:
    """Single-turn deterministic runtime without LLM writer or UI."""

    def __init__(
        self,
        *,
        writer_mode: WriterMode = "deterministic",
        actor_writer: ActorWriter | None = None,
        response_guard: ResponseGuard | None = None,
    ):
        self.writer_mode = writer_mode
        self.actor_writer = actor_writer or ActorWriter(mode=writer_mode)
        self.response_guard = response_guard or ResponseGuard()

    def handle_turn(
        self,
        user_message: str,
        state: DialogueV3State | None = None,
    ) -> DialogueV3TurnResult:
        """Run facts -> CaseFrame -> RouteSession -> ActorMove -> response -> events."""

        current_state = state or DialogueV3State(session_id=str(uuid4()))

        # The turn index is the stable timestamp for facts, messages, trace, and events.
        current_state.turn_index += 1
        current_state.add_user_message(user_message)

        extracted = extract_turn(
            user_message,
            turn_index=current_state.turn_index,
            state=current_state,
        )
        current_state.merge_extracted_turn(extracted)

        frame = build_case_frame(current_state)
        selected_route = select_route(frame, current_state)
        route_session = build_route_session(selected_route, state=current_state, frame=frame)
        current_state.route = route_session

        actor_move = plan_actor_move(route_session, frame=frame, state=current_state)
        state_summary = build_compact_state_summary(current_state, extracted)
        writer_output = self.actor_writer.write(
            move=actor_move,
            state_summary=state_summary,
        )
        writer_validation = self.response_guard.validate(output=writer_output, move=actor_move)
        initial_writer_validation = writer_validation
        writer_invalid = not writer_validation.accepted
        repair_attempted = False
        fallback_used = False
        if not writer_validation.accepted:
            repair_attempted = self.writer_mode in {"llm", "llm_guarded"}
            if repair_attempted:
                writer_output = self.actor_writer.repair(
                    move=actor_move,
                    state_summary=state_summary,
                    output=writer_output,
                    validation=writer_validation,
                )
                writer_validation = self.response_guard.validate(output=writer_output, move=actor_move)
            if not writer_validation.accepted:
                writer_output = render_safe_fallback(actor_move)
                fallback_used = True
                writer_validation = self.response_guard.validate(output=writer_output, move=actor_move)

        if not writer_output.text.strip():
            raise ValueError("dialogue_v3 produced an empty assistant response")
        if not writer_validation.accepted:
            issue_codes = ", ".join(sorted(writer_validation.issue_codes))
            raise ValueError(f"dialogue_v3 produced unsafe fallback response: {issue_codes}")

        events = execute_if_needed(actor_move, current_state)
        writer_validation = self.response_guard.validate(
            output=writer_output,
            move=actor_move,
            events=events,
        )
        if not writer_validation.accepted:
            issue_codes = ", ".join(sorted(writer_validation.issue_codes))
            raise ValueError(f"dialogue_v3 response failed post-action guard: {issue_codes}")

        trace = build_turn_trace(
            turn_index=current_state.turn_index,
            route_session=route_session,
            move=actor_move,
            events=events,
            writer_mode=self.writer_mode,
        )
        current_state.trace_history.append(trace.to_dict())
        if route_session.next_slot:
            current_state.asked_slots.append(route_session.next_slot)
        current_state.add_assistant_message(writer_output.text)

        return DialogueV3TurnResult(
            text=writer_output.text,
            state=current_state,
            trace=trace,
            events=events,
            extracted=extracted,
            frame=frame,
            route_session=route_session,
            actor_move=actor_move,
            writer_output=writer_output,
            writer_validation=writer_validation,
            initial_writer_validation=initial_writer_validation,
            writer_invalid=writer_invalid,
            repair_attempted=repair_attempted,
            fallback_used=fallback_used,
        )
