from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict, Tuple

from config import load_config
from llm_agent import run_assistant_agent
from utils import apply_fact_updates, apply_status_updates, enforce_hard_policy


BUSINESS_RULES_SUMMARY = """
МБК не выдаёт кредиты. Мы смотрим профиль и подсказываем, какой маршрут реально имеет смысл.

Приоритет:
- Есть квартира/дом/коммерция → чаще всего смотрим залог недвижимости.
- Есть машина → можно смотреть ПТС/залог авто.
- Чистый профиль без сильной нагрузки → можно пробовать беззалог через партнёров.
- Нет активов + просрочки/МФО → чаще нужны долговые варианты или честный отказ от новых заявок.

Анкета уже часть диагностики. Сумму, наличие кредитов, активы, занятость, иждивенцев,
город и семейное положение считай известными вводными, если они есть в current_facts.

Не собирай анкету до идеала. Если цель, масштаб проблемы, красный флаг и актив уже понятны,
делай вывод или передавай на специалиста. Лучше живой triage, чем длинный опрос.

5 вопросов — это контрольная точка, не жёсткий лимит. После неё нельзя спрашивать по инерции:
либо вывод/передача, либо короткое объяснение, зачем нужен ещё один вопрос.

Долги + чистое авто + документы на руках → можно передавать на разбор по авто и задолженности.
Не переспрашивай ПТС/СТС, залог, кредит или ограничения, если клиент уже подтвердил чистоту машины.

По недвижимости важны: город, ипотека/обременения, собственники, доли, несовершеннолетние собственники.
Дети, которые только прописаны, не равны несовершеннолетним собственникам, но документы всё равно нужно смотреть аккуратно.

Не обещай одобрение, ставку, точное списание или выдачу денег. Говори: "можно посмотреть", "реалистично", "имеет смысл".
""".strip()


def build_runtime_payload(state: Dict, latest_user_message: str) -> Dict:
    """Максимально чистый payload для одного хода."""
    return {
        "current_facts": state.get("current_facts", {}),
        "fact_statuses": state.get("fact_statuses", {}),
        "short_history": state.get("chat_history", [])[-10:],
        "latest_user_message": latest_user_message,
        "business_rules_summary": BUSINESS_RULES_SUMMARY,
    }


def apply_updates(state: Dict, result: Dict, user_message: str) -> Dict:
    new_state = deepcopy(state)
    new_state["current_facts"] = apply_fact_updates(
        state.get("current_facts", {}),
        result.get("fact_updates", []),
    )
    new_state["fact_statuses"] = apply_status_updates(
        state.get("fact_statuses", {}),
        result.get("status_updates", []),
    )

    if product_fit := result.get("product_fit_result"):
        new_state["product_fit_result"] = product_fit
        if rec := product_fit.get("recommended_product_id"):
            new_state["selected_product_id"] = rec

    if target_completion := result.get("target_completion"):
        new_state["target_completion"] = target_completion

    if phase := result.get("dialog_phase"):
        new_state["dialog_phase"] = phase

    history = new_state.setdefault("chat_history", [])
    history.append({"role": "user", "content": user_message})
    for bubble in result.get("messages", []):
        history.append({"role": "assistant", "content": bubble})
    new_state["message_count"] = state.get("message_count", 0) + 1
    return new_state


def process_message(state: Dict, user_message: str) -> Tuple[list[str], Dict, Dict]:
    payload = build_runtime_payload(state, user_message)
    result = run_assistant_agent(payload, load_config())
    result = enforce_hard_policy(result)
    new_state = apply_updates(state, result, user_message)
    return result.get("messages", []), new_state, result


class PipelineError(Exception):
    """UI-facing pipeline error with a stable code/message contract."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def _seed_current_facts(anketa: dict[str, Any]) -> dict[str, Any]:
    """Map the Streamlit form into the schema-free facts object used by the writer."""
    facts: dict[str, Any] = {
        "client": {},
        "request": {},
        "employment": {},
        "assets": {},
        "household": {},
    }

    if anketa.get("full_name"):
        facts["client"]["full_name"] = anketa["full_name"]
    if anketa.get("phone"):
        facts["client"]["phone"] = anketa["phone"]
    if anketa.get("birth_date"):
        facts["client"]["birth_date"] = anketa["birth_date"]
    if anketa.get("desired_amount"):
        facts["request"]["desired_amount"] = anketa["desired_amount"]
    if anketa.get("employment_type"):
        facts["employment"]["type"] = anketa["employment_type"]
    if anketa.get("asset_type"):
        facts["assets"]["type"] = anketa["asset_type"]
    if anketa.get("has_car") is not None:
        facts["assets"]["has_car"] = anketa["has_car"]
    if anketa.get("has_current_loans") is not None:
        facts["debts"] = {"has_current_loans": anketa["has_current_loans"]}
    if anketa.get("marital_status"):
        facts["household"]["marital_status"] = anketa["marital_status"]
    if anketa.get("has_dependents") is not None:
        facts["household"]["has_dependents"] = anketa["has_dependents"]
    if anketa.get("rent_expenses"):
        facts["household"]["rent_expenses"] = anketa["rent_expenses"]

    return {key: value for key, value in facts.items() if value}


def _normalize_ui_state(
    anketa: dict[str, Any],
    chat_history: list[dict[str, str]],
    current_state: dict[str, Any],
) -> dict[str, Any]:
    """Bridge the older Streamlit state shape to the new agent runtime state."""
    state = deepcopy(current_state or {})
    state.setdefault("current_facts", _seed_current_facts(anketa or {}))
    state.setdefault("fact_statuses", {})
    state.setdefault("chat_history", chat_history or [])
    state.setdefault("message_count", 0)
    return state


def _sync_legacy_debug_fields(state: dict[str, Any]) -> dict[str, Any]:
    """Keep old Streamlit debug widgets alive while the runtime uses current_facts."""
    state.setdefault("selected_case", state.get("selected_product_id"))
    state.setdefault("dialog_stage", state.get("dialog_phase", "qualification"))
    state["extracted_data"] = state.get("current_facts", {})
    state["answered_fields"] = sorted(state.get("current_facts", {}).keys())
    return state


def process_user_message(
    anketa: dict[str, Any],
    user_message: str,
    chat_history: list[dict[str, str]],
    current_state: dict[str, Any],
) -> dict[str, Any]:
    """Compatibility entrypoint used by app.py."""
    try:
        state = _normalize_ui_state(anketa, chat_history, current_state)
        messages, new_state, raw_result = process_message(state, user_message)
    except Exception as exc:
        raise PipelineError("llm_runtime_error", str(exc)) from exc

    new_state = _sync_legacy_debug_fields(new_state)
    return {
        "messages": messages,
        "message": "\n\n".join(messages),
        "current_state": new_state,
        "analysis": {
            "model": load_config().model,
            "dialog_phase": raw_result.get("dialog_phase"),
            "internal_summary": raw_result.get("internal_summary", ""),
            "product_fit_result": raw_result.get("product_fit_result"),
            "target_completion": raw_result.get("target_completion"),
            "ready_for_offer": raw_result.get("dialog_phase") in {"handoff", "target_completion"},
        },
        "raw_result": raw_result,
    }
