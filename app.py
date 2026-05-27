from __future__ import annotations
import json
import os
from datetime import datetime
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv

from config import load_config
from core import PipelineError, process_user_message
from logger import log_dialog, log_summary
from state import init_dialog_state, should_close_dialog

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env")

st.set_page_config(
    page_title="MBK Simple Bot",
    page_icon="💬",
    layout="wide",
)


def _read_env_value(name: str) -> str | None:
    return os.getenv(name) or os.getenv(f"$env:{name}")


def require_openrouter_key() -> None:
    if not (_read_env_value("OPEN_ROUTER_API_KEY") or _read_env_value("OPENROUTER_API_KEY")):
        st.error("Не настроен OPEN_ROUTER_API_KEY в .env")
        st.stop()


require_openrouter_key()

if "session_id" not in st.session_state:
    st.session_state.session_id = f"ui_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

for key in ["state", "history", "anketa", "applied_form", "turn_records"]:
    if key not in st.session_state:
        st.session_state[key] = {} if key in ["state", "anketa", "applied_form"] else []


def get_debug_state() -> dict[str, object]:
    last_analysis = (
        st.session_state.get("turn_records", [{}])[-1].get("analysis", {})
        if st.session_state.get("turn_records")
        else {}
    )
    current_state = st.session_state.get("state") or {}

    return {
        "selected_case": current_state.get("selected_case"),
        "message_count": current_state.get("message_count", 0),
        "dialog_stage": current_state.get("dialog_stage"),
        "ready_for_offer": last_analysis.get("ready_for_offer", False),
        "extracted_data": current_state.get("extracted_data", {}),
        "answered_fields": current_state.get("answered_fields", []),
        "last_objection": current_state.get("last_objection"),
    }


def is_dialog_closed(state: dict, analysis: dict | None = None) -> bool:
    if state.get("dialog_stage") in {"offer", "closed"}:
        return True
    return should_close_dialog(state, analysis or {})


def build_dialog_export() -> bytes:
    payload = {
        "session_id": st.session_state.get("session_id"),
        "exported_at": datetime.now().isoformat(),
        "anketa": st.session_state.get("anketa", {}),
        "applied_form": st.session_state.get("applied_form", {}),
        "history": st.session_state.get("history", []),
        "turn_records": st.session_state.get("turn_records", []),
        "current_state": st.session_state.get("state", {}),
        "debug_state": get_debug_state(),
    }

    return json.dumps(payload, ensure_ascii=False, indent=2, default=str).encode("utf-8")


with st.sidebar:
    st.header("MBK Simple Bot")
    st.caption(f"Олег • {load_config().model}")

    if st.button("🔄 Сбросить диалог", use_container_width=True):
        for key in ["state", "history", "anketa", "applied_form", "turn_records"]:
            st.session_state[key] = {} if key in ["state", "anketa", "applied_form"] else []
        st.rerun()

    st.divider()
    st.markdown("**Анкета (root-level)**")

    with st.form("manual_form", clear_on_submit=False):
        full_name = st.text_input("ФИО", key="form_full_name")
        desired_amount = st.number_input("Сумма", min_value=0, step=50000, key="form_desired_amount")
        phone = st.text_input("Телефон", key="form_phone")
        birth_date = st.text_input("Дата рождения", placeholder="ДД.ММ.ГГГГ", key="form_birth_date")

        st.markdown("**Адреса**")
        registration_address = st.text_input("Адрес регистрации", key="form_registration_address")
        addresses_match = st.checkbox(
            "Адрес проживания совпадает с адресом регистрации",
            key="form_addresses_match",
        )
        if addresses_match:
            living_address = registration_address
            st.caption("Адрес проживания будет взят из адреса регистрации")
        else:
            living_address = st.text_input("Адрес проживания", key="form_living_address")

        st.markdown("**Квалификация**")
        col1, col2 = st.columns(2)
        with col1:
            has_current_loans = st.selectbox(
                "Есть текущие кредиты или займы?",
                ["—", "Да", "Нет"],
                key="form_has_current_loans",
            )
            marital_status = st.selectbox(
                "Семейное положение",
                ["—", "Женат", "Замужем", "Не женат", "Не замужем", "Холост"],
                key="form_marital_status",
            )
            has_dependents = st.selectbox(
                "Иждивенцы",
                ["—", "Да", "Нет"],
                key="form_has_dependents",
            )

        with col2:
            employment_type = st.text_input(
                "Тип занятости (найм / ИП / самозанятый / безработный)",
                key="form_employment_type",
            )
            has_car = st.selectbox(
                "Есть ли в собственности авто?",
                ["—", "Да", "Нет"],
                key="form_has_car",
            )
            rent_expenses = st.number_input(
                "Расходы на аренду жилья",
                min_value=0,
                step=5000,
                key="form_rent_expenses",
            )
            asset_type = st.selectbox(
                "Тип актива",
                ["—", "Недвижимость", "Нет активов"],
                key="form_asset_type",
            )

        submitted = st.form_submit_button("Запустить чат по анкете", type="primary", use_container_width=True)

    if submitted:
        st.session_state.anketa = {
            "full_name": full_name or None,
            "desired_amount": int(desired_amount) if desired_amount > 0 else None,
            "phone": phone or None,
            "birth_date": birth_date or None,
            "registration_address": registration_address or None,
            "addresses_match": addresses_match,
            "living_address": living_address or None,
            "has_current_loans": has_current_loans == "Да" if has_current_loans != "—" else None,
            "marital_status": marital_status if marital_status != "—" else None,
            "has_dependents": has_dependents == "Да" if has_dependents != "—" else None,
            "employment_type": employment_type or None,
            "has_car": has_car == "Да" if has_car != "—" else None,
            "rent_expenses": int(rent_expenses) if rent_expenses > 0 else None,
            "asset_type": asset_type if asset_type != "—" else None,
        }

        st.session_state.state = init_dialog_state(st.session_state.anketa)
        st.session_state.history = []
        st.session_state.applied_form = {k: v for k, v in st.session_state.anketa.items() if v is not None}
        st.session_state.turn_records = []
        st.success("✅ Анкета применена. Диалог запущен.")
        st.rerun()

st.title("💬 MBK — Простой помощник")

if not st.session_state.get("state"):
    st.info("← Заполните анкету в боковой панели и нажмите «Запустить чат по анкете»")
else:
    current_state = st.session_state.state
    last_analysis = (
        st.session_state.get("turn_records", [{}])[-1].get("analysis", {})
        if st.session_state.get("turn_records")
        else {}
    )
    dialog_closed = is_dialog_closed(current_state, last_analysis)

    for msg in st.session_state.history:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    if dialog_closed:
        st.success(
            f"Диалог завершён. Сценарий: {current_state.get('selected_case') or 'не выбран'}."
        )
    else:
        user_input = st.chat_input("Сообщение клиента...")

        if user_input:
            st.session_state.history.append({"role": "user", "content": user_input})

            try:
                with st.spinner("Александр отвечает..."):
                    result = process_user_message(
                        anketa=st.session_state.anketa,
                        user_message=user_input,
                        chat_history=st.session_state.history,
                        current_state=st.session_state.state,
                    )
            except PipelineError as exc:
                st.session_state.history.pop()
                st.error(f"Не удалось получить ответ ({exc.code}): {exc.message}")
                st.stop()

            log_dialog(
                session_id=st.session_state.session_id,
                message=user_input,
                is_user=True,
                state=result["current_state"],
                analysis=result.get("analysis"),
            )
            log_dialog(
                session_id=st.session_state.session_id,
                message=result["message"],
                is_user=False,
                state=result["current_state"],
                analysis=result.get("analysis"),
            )

            for bubble in result.get("messages") or [result["message"]]:
                st.session_state.history.append({"role": "assistant", "content": bubble})
            st.session_state.state = result["current_state"]
            st.session_state.turn_records.append(result)

            if is_dialog_closed(st.session_state.state, result.get("analysis", {})):
                log_summary(st.session_state.session_id, st.session_state.state)

            st.rerun()

with st.expander("Текущее состояние (debug)", expanded=False):
    if st.session_state.get("state"):
        st.json(get_debug_state())

st.download_button(
    "⬇️ Скачать диалог и состояние",
    data=build_dialog_export(),
    file_name=f"mbk_dialog_{st.session_state.session_id}.json",
    mime="application/json",
    use_container_width=True,
    disabled=not bool(st.session_state.get("state") or st.session_state.get("history")),
)
