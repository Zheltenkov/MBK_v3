"""Deterministic Step 1 dialogue_v3 engine."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4

from .actions import ActionEvent, execute_if_needed
from .actor_writer import ActorWriter, WriterMode, build_compact_state_summary
from .case_frame import CaseFrame, build_case_frame
from .constants import BFL_RD, BFL_RI, MORTGAGE_AUX, MORTGAGE_MAIN
from .facts import ExtractedTurn, extract_turn
from .moves import ActorMove, build_terminal_known_facts, plan_actor_move, terminal_action_scope
from .response_guard import GuardIssue, GuardValidation, ResponseGuard
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
    writer_error: str | None = None


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
        # If a previous attempt failed after recording the user message but before the
        # assistant answer, a retry of the same text must finish the same turn instead
        # of appending a duplicate user message.
        if not _is_retry_of_unanswered_user_turn(current_state, user_message):
            current_state.turn_index += 1
            current_state.add_user_message(user_message)

        extracted = extract_turn(
            user_message,
            turn_index=current_state.turn_index,
            state=current_state,
        )
        current_state.merge_extracted_turn(extracted)

        pending_consent = current_state.fact_value("pending_terminal_consent")
        pending_route_refused = _extracted_rejects_pending_route(extracted, current_state.pending_route)
        declined_pending_terminal = False
        if (
            current_state.pending_terminal_action
            and pending_consent == "affirmative"
            and not pending_route_refused
        ):
            current_state.facts.pop("pending_terminal_consent", None)
            return self._handle_pending_terminal_acceptance(current_state, extracted)
        if (
            current_state.pending_terminal_action
            and (pending_consent == "negative" or pending_route_refused)
        ):
            current_state.facts.pop("pending_terminal_consent", None)
            _decline_pending_terminal(current_state)
            declined_pending_terminal = True

        frame = build_case_frame(current_state)
        selected_route = select_route(frame, current_state)
        route_session = build_route_session(selected_route, state=current_state, frame=frame)
        current_state.route = route_session

        actor_move = plan_actor_move(route_session, frame=frame, state=current_state)
        if declined_pending_terminal and actor_move.terminal_action:
            actor_move = ActorMove(
                move_type="post_terminal_answer",
                selected_route=route_session.selected_route,
                phase=route_session.phase,
                direct_answer_topic="route_declined",
                known_facts=build_terminal_known_facts(route_session.selected_route, current_state),
                action_scope=terminal_action_scope(route_session.terminal_action),
            )
        return self._finalize_turn(
            current_state=current_state,
            extracted=extracted,
            frame=frame,
            route_session=route_session,
            actor_move=actor_move,
        )

    def _handle_pending_terminal_acceptance(
        self,
        current_state: DialogueV3State,
        extracted: ExtractedTurn,
    ) -> DialogueV3TurnResult:
        pending_route = current_state.pending_route
        pending_action = current_state.pending_terminal_action
        if not pending_route or not pending_action:
            raise ValueError("pending terminal action is incomplete")

        frame = build_case_frame(current_state)
        route_session = build_route_session(pending_route, state=current_state, frame=frame)
        current_state.route = route_session
        action_key = f"{pending_route}:{pending_action}"
        if action_key in current_state.emitted_terminal_actions:
            actor_move = ActorMove(
                move_type="post_terminal_answer",
                selected_route=pending_route,
                phase=route_session.phase,
                direct_answer_topic="confirmed_terminal_consent",
                known_facts=build_terminal_known_facts(pending_route, current_state),
                action_scope=terminal_action_scope(pending_action),
            )
        else:
            actor_move = ActorMove(
                move_type="terminal_action",
                selected_route=pending_route,
                phase=route_session.phase,
                terminal_action=pending_action,
                direct_answer_topic="confirmed_terminal_consent",
                known_facts=build_terminal_known_facts(pending_route, current_state),
                action_scope=terminal_action_scope(pending_action),
            )
        return self._finalize_turn(
            current_state=current_state,
            extracted=extracted,
            frame=frame,
            route_session=route_session,
            actor_move=actor_move,
            clear_pending_after_action=True,
        )

    def _finalize_turn(
        self,
        *,
        current_state: DialogueV3State,
        extracted: ExtractedTurn,
        frame: CaseFrame,
        route_session: RouteSession,
        actor_move: ActorMove,
        clear_pending_after_action: bool = False,
    ) -> DialogueV3TurnResult:
        if actor_move.pending_terminal_action:
            current_state.pending_route = actor_move.pending_route
            current_state.pending_terminal_action = actor_move.pending_terminal_action

        state_summary = build_compact_state_summary(current_state, extracted)
        writer_error: str | None = None
        try:
            writer_output = self.actor_writer.write(
                move=actor_move,
                state_summary=state_summary,
            )
            writer_validation = self.response_guard.validate(output=writer_output, move=actor_move)
            initial_writer_validation = writer_validation
        except Exception as exc:
            writer_error = f"{type(exc).__name__}: {exc}"
            writer_output = render_safe_fallback(actor_move)
            writer_validation = self.response_guard.validate(output=writer_output, move=actor_move)
            initial_writer_validation = _writer_exception_validation(writer_error)

        writer_invalid = not initial_writer_validation.accepted
        repair_attempted = False
        fallback_used = writer_error is not None
        if not writer_validation.accepted:
            repair_attempted = self.writer_mode in {"llm", "llm_guarded"}
            if repair_attempted:
                try:
                    writer_output = self.actor_writer.repair(
                        move=actor_move,
                        state_summary=state_summary,
                        output=writer_output,
                        validation=writer_validation,
                    )
                    writer_validation = self.response_guard.validate(output=writer_output, move=actor_move)
                except Exception as exc:
                    writer_error = f"{type(exc).__name__}: {exc}"
                    writer_output = render_safe_fallback(actor_move)
                    fallback_used = True
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
        if clear_pending_after_action:
            current_state.pending_route = None
            current_state.pending_terminal_action = None
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
            writer_error=writer_error,
        )


def _decline_pending_terminal(state: DialogueV3State) -> None:
    pending_route = state.pending_route
    if pending_route:
        state.rejected_routes.add(pending_route)
        if pending_route in {MORTGAGE_MAIN, MORTGAGE_AUX}:
            state.rejected_routes.add("MORTGAGE")
        if pending_route in {BFL_RD, BFL_RI}:
            state.rejected_routes.add(pending_route)
    state.pending_route = None
    state.pending_terminal_action = None


def _extracted_rejects_pending_route(extracted: ExtractedTurn, pending_route: str | None) -> bool:
    """Detect a hard refusal of the pending route before normal route reselection."""

    if not pending_route or not extracted.route_rejection:
        return False
    if extracted.route_rejection == pending_route:
        return True
    return pending_route in {MORTGAGE_MAIN, MORTGAGE_AUX} and extracted.route_rejection == "MORTGAGE"


def _is_retry_of_unanswered_user_turn(state: DialogueV3State, user_message: str) -> bool:
    """Return True when the same user turn was stored but no assistant answered yet."""

    if not state.messages:
        return False
    last_message = state.messages[-1]
    if last_message.role != "user":
        return False
    return last_message.content.strip() == user_message.strip()


def _writer_exception_validation(writer_error: str) -> GuardValidation:
    """Represent a writer exception as a controlled validation failure."""

    return GuardValidation(
        accepted=False,
        issues=[
            GuardIssue(
                code="writer_exception_fallback",
                message=writer_error,
            )
        ],
        repairable=False,
    )
