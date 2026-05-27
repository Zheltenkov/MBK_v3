import json
import os
from datetime import datetime
from typing import Dict, Optional


def ensure_log_dir():
    """Создаёт папку logs, если её нет"""
    os.makedirs("logs", exist_ok=True)


def log_dialog(
    session_id: str,
    message: str,
    is_user: bool,
    state: Dict,
    analysis: Optional[Dict] = None,
    anketa_id: Optional[str] = None
):
    """Логирует каждое сообщение"""
    ensure_log_dir()

    log_entry = {
        "timestamp": datetime.now().isoformat(),
        "session_id": session_id,
        "anketa_id": anketa_id or "unknown",
        "is_user": is_user,
        "message": message,
        "selected_case": state.get("selected_case"),
        "dialog_stage": state.get("dialog_stage"),
        "message_count": state.get("message_count"),
        "analysis": analysis or {}
    }

    filename = f"logs/dialog_{session_id}.jsonl"

    with open(filename, "a", encoding="utf-8") as f:
        f.write(json.dumps(log_entry, ensure_ascii=False) + "\n")


def log_summary(session_id: str, final_state: Dict):
    """Итоговый summary по завершении диалога"""
    ensure_log_dir()
    summary = {
        "session_id": session_id,
        "finished_at": datetime.now().isoformat(),
        "selected_case": final_state.get("selected_case"),
        "dialog_stage": final_state.get("dialog_stage"),
        "total_messages": final_state.get("message_count", 0),
        "success": final_state.get("dialog_stage") in ["offer", "closed"]
    }

    with open(f"logs/summary_{session_id}.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    print(f"✅ Диалог {session_id} сохранён в logs/")