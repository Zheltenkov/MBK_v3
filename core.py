from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict, Iterator

import llm_agent
from config import AppConfig, load_config
from prompts import split_bubbles
from utils import apply_fact_updates, apply_status_updates, guard_bubbles


BUSINESS_RULES_SUMMARY = """
МБК не выдаёт кредиты сам — мы смотрим профиль и ведём клиента к реальному решению.

Приоритет маршрутов:
- Есть квартира/дом/коммерция → чаще всего залог недвижимости.
- Есть машина → можно ПТС/залог авто.
- Чистый профиль без сильной нагрузки → беззалог через партнёров.
- Нет активов + просрочки/МФО → долговые варианты (банкротство) или честный отказ от новых заявок.

Анкета — часть диагностики: сумму, кредиты, активы, занятость, иждивенцев, город и семейное
положение считай известными, если они уже есть в фактах, и не переспрашивай.

Не собирай анкету до идеала. Если цель, масштаб проблемы, красный флаг и актив уже понятны —
делай вывод или передавай специалисту. Лучше живой triage, чем длинный опрос. 5 вопросов —
контрольная точка, не лимит: после неё либо вывод/передача, либо короткое объяснение, зачем ещё вопрос.

Долги + чистое авто + документы на руках → можно передавать на разбор по авто и задолженности;
не переспрашивай ПТС/залог/ограничения, если клиент уже подтвердил, что машина чистая.

По недвижимости важны: город, ипотека/обременения, собственники, доли, несовершеннолетние собственники.
Прописанные дети ≠ несовершеннолетние собственники, но документы всё равно смотреть аккуратно.

Не обещай гарантий (одобрение, ставку, списание, выдачу денег). При этом говори конкретно и по делу,
без мямленья — опирайся на свою экспертизу по продуктам.
""".strip()


def build_runtime_payload(state: Dict, latest_user_message: str) -> Dict:
    """Чистый payload для одного хода (история БЕЗ текущей реплики клиента)."""
    return {
        "current_facts": state.get("current_facts", {}),
        "fact_statuses": state.get("fact_statuses", {}),
        "short_history": state.get("chat_history", [])[-10:],
        "latest_user_message": latest_user_message,
        "business_rules_summary": BUSINESS_RULES_SUMMARY,
    }


def apply_updates(state: Dict, state_update: Dict, user_message: str, bubbles: list[str]) -> Dict:
    new_state = deepcopy(state)
    new_state["current_facts"] = apply_fact_updates(
        state.get("current_facts", {}), state_update.get("fact_updates", [])
    )
    new_state["fact_statuses"] = apply_status_updates(
        state.get("fact_statuses", {}), state_update.get("status_updates", [])
    )

    if product_fit := state_update.get("product_fit_result"):
        new_state["product_fit_result"] = product_fit
        if rec := product_fit.get("recommended_product_id"):
            new_state["selected_product_id"] = rec
    if target_completion := state_update.get("target_completion"):
        new_state["target_completion"] = target_completion
    if phase := state_update.get("dialog_phase"):
        new_state["dialog_phase"] = phase

    history = new_state.setdefault("chat_history", [])
    history.append({"role": "user", "content": user_message})
    for bubble in bubbles:
        history.append({"role": "assistant", "content": bubble})
    new_state["message_count"] = state.get("message_count", 0) + 1
    return new_state


# --------------------------------------------------------------------------- #
# Стриминговый путь (для UI «как GPT»)
# --------------------------------------------------------------------------- #
def stream_reply(state: Dict, user_message: str, config: AppConfig | None = None) -> Iterator[str]:
    """Живой ответ токен за токеном. Возвращает чанки текста для st.write_stream."""
    config = config or load_config()
    payload = build_runtime_payload(state, user_message)
    yield from llm_agent.stream_conversation(payload, config)


def commit_turn(state: Dict, user_message: str, full_reply: str, config: AppConfig | None = None) -> Dict:
    """После стрима: разбор в JSON (молча) + применение фактов. Разговор от него не зависит."""
    config = config or load_config()
    payload = build_runtime_payload(state, user_message)

    bubbles = guard_bubbles(split_bubbles(full_reply)) or [full_reply.strip() or "…"]

    try:
        state_update = llm_agent.extract_state(payload, full_reply, config)
    except Exception:
        # Извлечение может сбоить (модель/JSON) — это НЕ должно ломать диалог.
        state_update = {"dialog_phase": state.get("dialog_phase", "qualification")}

    new_state = apply_updates(state, state_update, user_message, bubbles)
    new_state = _sync_legacy_debug_fields(new_state)
    return _build_result(bubbles, new_state, state_update, config)


# --------------------------------------------------------------------------- #
# Не-стримовый путь (совместимость / тесты)
# --------------------------------------------------------------------------- #
class PipelineError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def process_message(state: Dict, user_message: str) -> tuple[list[str], Dict, Dict]:
    config = load_config()
    payload = build_runtime_payload(state, user_message)
    full_reply = llm_agent.generate_reply(payload, config)
    result = commit_turn(state, user_message, full_reply, config)
    return result["messages"], result["current_state"], result["raw_result"]


def _build_result(bubbles: list[str], new_state: Dict, state_update: Dict, config: AppConfig) -> Dict:
    return {
        "messages": bubbles,
        "message": "\n\n".join(bubbles),
        "current_state": new_state,
        "analysis": {
            "model": config.model,
            "dialog_phase": state_update.get("dialog_phase"),
            "internal_summary": state_update.get("internal_summary", ""),
            "product_fit_result": state_update.get("product_fit_result"),
            "target_completion": state_update.get("target_completion"),
            "ready_for_offer": state_update.get("dialog_phase") in {"handoff", "target_completion"},
        },
        "raw_result": state_update,
    }


def _seed_current_facts(anketa: dict[str, Any]) -> dict[str, Any]:
    facts: dict[str, Any] = {"client": {}, "request": {}, "employment": {}, "assets": {}, "household": {}}
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


def _normalize_ui_state(anketa, chat_history, current_state) -> dict[str, Any]:
    state = deepcopy(current_state or {})
    state.setdefault("current_facts", _seed_current_facts(anketa or {}))
    state.setdefault("fact_statuses", {})
    state.setdefault("chat_history", chat_history or [])
    state.setdefault("message_count", 0)
    return state


def _sync_legacy_debug_fields(state: dict[str, Any]) -> dict[str, Any]:
    state.setdefault("selected_case", state.get("selected_product_id"))
    state.setdefault("dialog_stage", state.get("dialog_phase", "qualification"))
    state["extracted_data"] = state.get("current_facts", {})
    state["answered_fields"] = sorted(state.get("current_facts", {}).keys())
    return state


def process_user_message(anketa, user_message, chat_history, current_state) -> dict[str, Any]:
    """Не-стримовый совместимый вход (для тестов/фолбэка)."""
    try:
        state = _normalize_ui_state(anketa, chat_history, current_state)
        return commit_turn_nonstream(state, user_message)
    except Exception as exc:
        raise PipelineError("llm_runtime_error", str(exc)) from exc


def commit_turn_nonstream(state: Dict, user_message: str) -> dict[str, Any]:
    config = load_config()
    payload = build_runtime_payload(state, user_message)
    full_reply = llm_agent.generate_reply(payload, config)
    return commit_turn(state, user_message, full_reply, config)
