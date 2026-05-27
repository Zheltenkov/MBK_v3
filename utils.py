from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict, List


LIST_FACT_ROOTS = {"properties", "vehicles"}


def _is_list_index(part: str) -> bool:
    return part.isdigit()


def _would_create_extra_list_item(path: str, facts: Dict[str, Any]) -> bool:
    parts = path.split(".")
    if len(parts) < 2 or parts[0] not in LIST_FACT_ROOTS or not _is_list_index(parts[1]):
        return False

    item_index = int(parts[1])
    if item_index == 0:
        return False

    existing_items = facts.get(parts[0])
    if not isinstance(existing_items, list):
        return True
    return item_index >= len(existing_items)


def set_by_path(obj: Dict[str, Any], path: str, value: Any) -> None:
    current: Any = obj
    parts = path.split(".")
    for index, part in enumerate(parts[:-1]):
        next_part = parts[index + 1]
        if isinstance(current, list) and _is_list_index(part):
            item_index = int(part)
            while len(current) <= item_index:
                current.append({} if not _is_list_index(next_part) else [])
            if current[item_index] is None:
                current[item_index] = {} if not _is_list_index(next_part) else []
            current = current[item_index]
            continue

        if not isinstance(current, dict):
            return
        if part not in current or current[part] is None:
            current[part] = [] if _is_list_index(next_part) else {}
        current = current[part]

    if isinstance(current, dict):
        current[parts[-1]] = value
    elif isinstance(current, list) and _is_list_index(parts[-1]):
        item_index = int(parts[-1])
        while len(current) <= item_index:
            current.append(None)
        current[item_index] = value


def apply_fact_updates(current_facts: Dict, fact_updates: List[Dict]) -> Dict:
    facts = deepcopy(current_facts)
    for update in fact_updates:
        path = update.get("path")
        if (
            path
            and update.get("value") is not None
            and update.get("conflict") is not True
            and not _would_create_extra_list_item(path, facts)
        ):
            set_by_path(facts, path, update["value"])
    return facts


def apply_status_updates(fact_statuses: Dict, status_updates: List[Dict]) -> Dict:
    statuses = deepcopy(fact_statuses)
    for update in status_updates:
        if update.get("path") and update.get("status"):
            statuses[update["path"]] = update["status"]
    return statuses


def enforce_hard_policy(result: Dict) -> Dict:
    """Тонкий safety-гард по правилу №1: только прямые гарантии одобрения/выдачи.

    Намеренно НЕ ловим обороты живого специалиста («ставка будет ниже», «в районе»,
    «шансы низкие») — иначе вернёмся к ботовости. Работаем по списку messages и
    выкидываем только проблемный пузырь, а не весь ход.
    """
    messages = list(result.get("messages") or [])
    forbidden = (
        "точно одобр",
        "гарантируем одобр",
        "гарантированно одобр",
        "100% одобр",
        "гарантированно спишем",
        "спишем 100%",
        "мы выдадим кредит",
        "мы выдаем кредит",
        "мы выдаём кредит",
        "дадим вам деньги",
        "дадим вам денег",
    )

    safe = [m for m in messages if not any(marker in m.lower() for marker in forbidden)]
    if len(safe) == len(messages):
        return result

    if not safe:
        safe = [
            "Гарантировать одобрение или точную ставку заранее не могу — это было бы нечестно.",
            "Но могу разобрать профиль и сказать, какой маршрут реально имеет смысл.",
        ]

    guarded = dict(result)
    guarded["messages"] = safe
    guarded["internal_summary"] = f"{result.get('internal_summary', '')} | hard_policy_guard".strip(" |")
    return guarded
