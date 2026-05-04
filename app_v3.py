"""Streamlit UI for manual dialogue_v3 checks.

Run with:

    streamlit run app_v3.py

The UI is intentionally thin: it collects a manual form, calls DialogueV3Engine
for every user turn, and renders chat/debug/export state. It does not own route,
terminal action, or writer validation decisions.
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict, is_dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import streamlit as st

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from mbk_refactor.dialogue_v3.actor_writer import ActorWriter
from mbk_refactor.dialogue_v3.engine import DialogueV3Engine, DialogueV3TurnResult
from mbk_refactor.dialogue_v3.llm_client import LLMClientStatus, build_optional_llm_client
from mbk_refactor.dialogue_v3.state import DialogueV3State
from mbk_refactor.dialogue_v3.ui_form_schema import (
    ROOT_FORM_FIELDS,
    public_form_to_facts,
    public_form_to_state,
)


ARTIFACTS_DIR = ROOT / "artifacts"
WRITER_MODE = "llm_guarded"
DEFAULT_MODEL_NAME = os.getenv("MBK_V3_MODEL_NAME") or os.getenv("OPENAI_MODEL") or "gpt-4o-mini"


SESSION_RESET_DEFAULTS: dict[str, Any] = {
    "v3_state": None,
    "applied_form": {},
    "applied_facts": {},
    "turn_records": [],
    "last_result": None,
    "last_error": "",
    "last_llm_status": None,
    "saved_dialog_path": "",
    "saved_trace_path": "",
}


def main() -> None:
    """Render the v3 manual testing UI."""

    st.set_page_config(
        page_title="MBK dialogue_v3",
        page_icon="MBK",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    _init_state()

    with st.sidebar:
        st.header("MBK v3")
        _render_model_settings()
        st.divider()
        _render_manual_form()
        st.divider()
        _render_save_panel()

    st.title("MBK dialogue_v3")
    st.caption("Ручная анкета, LLM writer, диалог и trace одного controlled runtime.")

    col_chat, col_debug = st.columns([0.64, 0.36], gap="large")
    with col_chat:
        _render_chat()
        _handle_user_turn()
    with col_debug:
        _render_debug_panel()


def _init_state() -> None:
    """Create Streamlit session keys used by the UI."""

    defaults: dict[str, Any] = {
        "v3_state": None,
        "applied_form": {},
        "applied_facts": {},
        "turn_records": [],
        "last_result": None,
        "last_error": "",
        "last_llm_status": None,
        "model_name": DEFAULT_MODEL_NAME,
        "saved_dialog_path": "",
        "saved_trace_path": "",
    }
    for key, value in defaults.items():
        st.session_state.setdefault(key, value)


def _render_model_settings() -> None:
    """Render the only writer configuration exposed to the operator."""

    st.markdown("**LLM writer**")
    st.text_input("Название модели", key="model_name")
    status = st.session_state.get("last_llm_status")
    if isinstance(status, LLMClientStatus):
        if status.available:
            st.success(f"LLM подключен: {status.model_name}")
        else:
            st.warning(f"LLM недоступен: {status.reason}")
    else:
        st.caption("LLM подключение проверится на следующем ходе.")

    if st.button("Сбросить диалог", use_container_width=True):
        _reset_dialog()
        st.rerun()


def _render_manual_form() -> None:
    """Render only root-level manual fields and apply them as initial facts."""

    st.markdown("**Анкета ручного ввода**")
    st.caption(
        "Стартовая анкета содержит только поля Вложенность = 1. "
        "Детали по авто, кредитам, занятости и недвижимости ассистент уточнит в чате, если они нужны."
    )
    with st.form("dialogue_v3_manual_form", clear_on_submit=False):
        st.markdown("**Клиент и запрос**")
        desired_amount = st.number_input(
            "Сумма",
            min_value=0,
            step=50_000,
            key="form_desired_amount",
        )
        full_name = st.text_input("ФИО", key="form_full_name")
        phone = st.text_input("Телефон", key="form_phone")
        birth_date = st.text_input("Дата рождения", key="form_birth_date", placeholder="ДД.ММ.ГГГГ")

        st.markdown("**Адреса**")
        registration_address = st.text_input("Адрес регистрации", key="form_registration_address")
        addresses_match = st.checkbox(
            "Адрес проживания совпадает с адресом регистрации",
            key="form_addresses_match",
        )
        if addresses_match:
            living_address = registration_address
            st.caption("Адрес проживания будет взят из адреса регистрации.")
        else:
            living_address = st.text_input("Адрес проживания", key="form_living_address")

        st.markdown("**Root qualification**")
        has_current_loans = _tri_state("Есть текущие кредиты или займы?", "form_has_current_loans")
        marital_status = st.selectbox(
            "Семейное положение",
            ("—", "Женат / Замужем", "Не женат / Не замужем"),
            key="form_marital_status",
        )
        has_dependents = _tri_state("Иждивенцы", "form_has_dependents")
        employment_type = st.text_input(
            "Тип занятости",
            key="form_employment_type",
            placeholder="найм / самозанятый / ИП / безработный",
        )
        has_car = _tri_state("Есть ли в собственности авто?", "form_has_car")
        rent_expenses = st.number_input(
            "Расходы на аренду жилья",
            min_value=0,
            step=5_000,
            key="form_rent_expenses",
        )
        asset_type = st.selectbox(
            "Тип актива",
            ("—", "Недвижимость", "Нет активов"),
            key="form_asset_type",
        )

        submitted = st.form_submit_button("Старт чат по анкете", type="primary", use_container_width=True)

    if submitted:
        form_payload = {
            "Сумма": _int_or_none(desired_amount),
            "ФИО": _str_or_none(full_name),
            "Телефон": _str_or_none(phone),
            "Дата рождения": _str_or_none(birth_date),
            "Адрес регистрации": _str_or_none(registration_address),
            "галочка совпадает": True if addresses_match else False,
            "Адрес проживания": _str_or_none(living_address),
            "Есть текущие кредиты или займы?": has_current_loans,
            "Семейное положение": None if marital_status == "—" else marital_status,
            "Иждивенцы": has_dependents,
            "Тип занятости": _str_or_none(employment_type),
            "Есть ли в собственности авто?": has_car,
            "Расходы на аренду жилья": _int_or_none(rent_expenses),
            "Тип актива": None if asset_type == "—" else asset_type,
        }
        facts = public_form_to_facts(form_payload)
        if not facts:
            st.error("Заполните хотя бы одно содержательное поле анкеты.")
            return
        state = public_form_to_state(form_payload, session_id=str(uuid4()))
        st.session_state["v3_state"] = state
        st.session_state["applied_form"] = _drop_empty(form_payload)
        st.session_state["applied_facts"] = facts
        st.session_state["turn_records"] = []
        st.session_state["last_result"] = None
        st.session_state["last_error"] = ""
        st.session_state["saved_dialog_path"] = ""
        st.session_state["saved_trace_path"] = ""
        st.success("Анкета применена. Можно вести диалог.")
        st.rerun()

    if st.session_state.get("applied_form"):
        with st.expander("Применённая анкета", expanded=False):
            st.json(st.session_state["applied_form"], expanded=True)
            st.caption(f"Root fields rendered: {len(ROOT_FORM_FIELDS)}")


def _render_save_panel() -> None:
    """Render JSON download and file-save controls for dialog and traces."""

    st.markdown("**Сохранение**")
    has_session = st.session_state.get("v3_state") is not None
    dialog_name, dialog_bytes = _build_dialog_download()
    trace_name, trace_bytes = _build_trace_download()

    st.download_button(
        "Скачать диалог JSON",
        data=dialog_bytes,
        file_name=dialog_name,
        mime="application/json",
        disabled=not has_session,
        use_container_width=True,
    )
    st.download_button(
        "Скачать trace JSON",
        data=trace_bytes,
        file_name=trace_name,
        mime="application/json",
        disabled=not has_session,
        use_container_width=True,
    )

    save_col, trace_col = st.columns(2)
    with save_col:
        if st.button("Save dialog", disabled=not has_session, use_container_width=True):
            path = _save_artifact("dialogue_v3_ui_dialog", _current_dialog_payload())
            st.session_state["saved_dialog_path"] = str(path)
    with trace_col:
        if st.button("Save trace", disabled=not has_session, use_container_width=True):
            path = _save_artifact("dialogue_v3_ui_trace", _current_trace_payload())
            st.session_state["saved_trace_path"] = str(path)

    if st.session_state.get("saved_dialog_path"):
        st.caption(f"Диалог: {st.session_state['saved_dialog_path']}")
    if st.session_state.get("saved_trace_path"):
        st.caption(f"Trace: {st.session_state['saved_trace_path']}")


def _render_chat() -> None:
    """Render persisted dialogue messages."""

    state = st.session_state.get("v3_state")
    messages = list(getattr(state, "messages", []) or [])

    if state is None:
        st.warning("Диалог заблокирован: сначала заполните анкету слева и нажмите «Старт чат по анкете».")
        return
    if not messages:
        st.info("Анкета применена. Напишите первое сообщение клиента.")
        return

    for message in messages:
        with st.chat_message(message.role):
            st.markdown(message.content)


def _handle_user_turn() -> None:
    """Send one user turn into DialogueV3Engine."""

    state = st.session_state.get("v3_state")
    chat_ready = state is not None
    user_message = st.chat_input(
        "Напишите сообщение клиента..." if chat_ready else "Сначала заполните анкету",
        disabled=not chat_ready,
    )
    if not user_message:
        return

    try:
        engine, llm_status = _build_engine()
        st.session_state["last_llm_status"] = llm_status
        with st.spinner("Думаю..."):
            result = engine.handle_turn(user_message, state)
    except Exception as exc:
        st.session_state["last_error"] = f"{type(exc).__name__}: {exc}"
        st.error(st.session_state["last_error"])
        return

    st.session_state["v3_state"] = result.state
    st.session_state["last_result"] = result
    st.session_state["last_error"] = ""
    st.session_state["turn_records"].append(_turn_record(result))
    st.rerun()


def _render_debug_panel() -> None:
    """Render read-only debug state for the last engine turn."""

    st.subheader("Debug")
    last_error = st.session_state.get("last_error")
    if last_error:
        st.error(last_error)

    state = st.session_state.get("v3_state")
    result = st.session_state.get("last_result")
    if state is None:
        st.caption("Анкета ещё не применена.")
        return

    if result is None:
        st.info("Первый turn ещё не обработан.")
        with st.expander("Initial facts", expanded=True):
            st.json(_facts_to_plain(state), expanded=True)
        return

    trace = result.trace.to_dict()
    top = {
        "selected_route": trace.get("selected_route"),
        "phase": trace.get("phase"),
        "next_slot": trace.get("next_slot"),
        "terminal_action": trace.get("terminal_action"),
        "validation_problems": [_to_plain(issue) for issue in result.writer_validation.issues],
        "initial_validation_problems": [
            _to_plain(issue) for issue in result.initial_writer_validation.issues
        ],
        "fallback_used": result.fallback_used,
        "writer_invalid": result.writer_invalid,
    }
    st.json(top, expanded=True)

    with st.expander("RouteSession", expanded=True):
        st.json(_to_plain(result.route_session), expanded=True)
    with st.expander("ActorMove", expanded=False):
        st.json(_to_plain(result.actor_move), expanded=True)
    with st.expander("Writer validation", expanded=False):
        st.json(
            {
                "accepted": result.writer_validation.accepted,
                "initial_accepted": result.initial_writer_validation.accepted,
                "repair_attempted": result.repair_attempted,
                "fallback_used": result.fallback_used,
                "issues": [_to_plain(issue) for issue in result.writer_validation.issues],
                "initial_issues": [_to_plain(issue) for issue in result.initial_writer_validation.issues],
            },
            expanded=True,
        )
    with st.expander("Action events", expanded=False):
        st.json([_to_plain(event) for event in result.events], expanded=True)
    with st.expander("Extracted facts", expanded=False):
        st.json(_to_plain(result.extracted), expanded=True)
    with st.expander("CaseFrame", expanded=False):
        st.json(_to_plain(result.frame), expanded=True)
    with st.expander("Trace history", expanded=False):
        st.json(list(state.trace_history), expanded=True)


def _build_engine() -> tuple[DialogueV3Engine, LLMClientStatus]:
    """Create an engine for one turn with the selected model name."""

    model_name = str(st.session_state.get("model_name") or DEFAULT_MODEL_NAME).strip()
    llm_client, status = build_optional_llm_client(model_name)
    writer = ActorWriter(mode=WRITER_MODE, llm_client=llm_client)
    return DialogueV3Engine(writer_mode=WRITER_MODE, actor_writer=writer), status


def _reset_dialog() -> None:
    """Reset chat and applied form without touching runtime code."""

    for key in (
        "v3_state",
        "applied_form",
        "applied_facts",
        "turn_records",
        "last_result",
        "last_error",
        "last_llm_status",
        "saved_dialog_path",
        "saved_trace_path",
    ):
        st.session_state[key] = SESSION_RESET_DEFAULTS[key]


def _tri_state(label: str, key: str) -> bool | None:
    """Render a yes/no/unknown selectbox."""

    value = st.selectbox(
        label,
        ("unknown", "yes", "no"),
        format_func={"unknown": "неизвестно", "yes": "да", "no": "нет"}.__getitem__,
        key=key,
    )
    if value == "yes":
        return True
    if value == "no":
        return False
    return None


def _drop_empty(payload: dict[str, Any]) -> dict[str, Any]:
    """Drop empty values while preserving explicit booleans."""

    result: dict[str, Any] = {}
    for key, value in payload.items():
        if value in (None, "", [], {}):
            continue
        if value == "unknown":
            continue
        if isinstance(value, (int, float)) and not isinstance(value, bool) and value == 0:
            continue
        result[key] = value
    return result


def _str_or_none(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _int_or_none(value: Any) -> int | None:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number else None


def _current_dialog_payload() -> dict[str, Any]:
    """Build a serializable dialog export payload."""

    state = st.session_state.get("v3_state")
    timestamp = datetime.now().isoformat(timespec="seconds")
    status = st.session_state.get("last_llm_status")
    return {
        "timestamp": timestamp,
        "mode": "dialogue_v3_ui",
        "writer_mode": WRITER_MODE,
        "model_name": st.session_state.get("model_name"),
        "llm_status": _to_plain(status) if status is not None else None,
        "input_parameters": st.session_state.get("applied_form") or {},
        "applied_facts": st.session_state.get("applied_facts") or {},
        "messages": _messages_to_plain(state),
        "turns": list(st.session_state.get("turn_records") or []),
        "trace_history": list(getattr(state, "trace_history", []) or []),
        "state": _state_to_plain(state),
    }


def _current_trace_payload() -> dict[str, Any]:
    """Build a focused trace export payload."""

    state = st.session_state.get("v3_state")
    return {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "mode": "dialogue_v3_trace",
        "writer_mode": WRITER_MODE,
        "model_name": st.session_state.get("model_name"),
        "trace_history": list(getattr(state, "trace_history", []) or []),
        "turns": list(st.session_state.get("turn_records") or []),
    }


def _build_dialog_download() -> tuple[str, bytes]:
    payload = _current_dialog_payload()
    return _download_name("dialogue_v3_dialog"), _json_bytes(payload)


def _build_trace_download() -> tuple[str, bytes]:
    payload = _current_trace_payload()
    return _download_name("dialogue_v3_trace"), _json_bytes(payload)


def _save_artifact(prefix: str, payload: dict[str, Any]) -> Path:
    """Persist a UI artifact under artifacts/."""

    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    path = ARTIFACTS_DIR / _download_name(prefix)
    path.write_bytes(_json_bytes(payload))
    return path


def _download_name(prefix: str) -> str:
    return f"{prefix}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"


def _json_bytes(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, ensure_ascii=False, indent=2, default=str).encode("utf-8")


def _turn_record(result: DialogueV3TurnResult) -> dict[str, Any]:
    """Build compact per-turn record for debug/export."""

    return {
        "turn_index": result.state.turn_index,
        "selected_route": result.route_session.selected_route,
        "phase": result.route_session.phase,
        "next_slot": result.route_session.next_slot,
        "terminal_action": result.route_session.terminal_action,
        "action_events": [_to_plain(event) for event in result.events],
        "actor_move": _to_plain(result.actor_move),
        "writer_output": _to_plain(result.writer_output),
        "writer_validation": {
            "accepted": result.writer_validation.accepted,
            "issues": [_to_plain(issue) for issue in result.writer_validation.issues],
        },
        "validation_problems": [_to_plain(issue) for issue in result.writer_validation.issues],
        "initial_validation_problems": [
            _to_plain(issue) for issue in result.initial_writer_validation.issues
        ],
        "writer_invalid": result.writer_invalid,
        "repair_attempted": result.repair_attempted,
        "fallback_used": result.fallback_used,
        "trace": result.trace.to_dict(),
    }


def _state_to_plain(state: DialogueV3State | None) -> dict[str, Any]:
    if state is None:
        return {}
    return {
        "session_id": state.session_id,
        "turn_index": state.turn_index,
        "facts": _facts_to_plain(state),
        "service_mode": state.service_mode,
        "asked_slots": list(state.asked_slots),
        "closed_slot_groups": sorted(state.closed_slot_groups),
        "rejected_routes": sorted(state.rejected_routes),
        "accepted_route": state.accepted_route,
    }


def _messages_to_plain(state: DialogueV3State | None) -> list[dict[str, Any]]:
    if state is None:
        return []
    return [_to_plain(message) for message in state.messages]


def _facts_to_plain(state: DialogueV3State) -> dict[str, Any]:
    return {key: _to_plain(value) for key, value in state.facts.items()}


def _to_plain(value: Any) -> Any:
    """Convert dataclasses and containers to Streamlit/json-friendly values."""

    if is_dataclass(value):
        return {key: _to_plain(item) for key, item in asdict(value).items()}
    if isinstance(value, dict):
        return {str(key): _to_plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_to_plain(item) for item in value]
    return value


if __name__ == "__main__":
    main()
