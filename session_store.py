"""
In-memory store сессий + снапшоты на диск.

Хранит:
- state (current_facts, chat_history, declined_products, lead_delivered и т.д.)
- anketa (опционально)
- usage (SessionUsage)
- pending_extraction (Future из общего ThreadPoolExecutor)

Каждое изменение пишется снимком в logs/sessions/{id}.json — для дебага и
аудитa. На рестарте процесса состояние не восстанавливается из снапшотов
автоматически (это сознательно: чтобы не таскать стейл-сессии); если понадобится,
переключим на Redis + восстановление одним коннектором.
"""
from __future__ import annotations

import asyncio
import json
import uuid
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any

from state import init_dialog_state
from usage_tracker import SessionUsage


SESSIONS_DIR = Path(__file__).resolve().parent / "logs" / "sessions"
SESSIONS_DIR.mkdir(parents=True, exist_ok=True)


@dataclass
class Session:
    id: str
    state: dict[str, Any]
    anketa: dict[str, Any] | None
    usage: SessionUsage
    pending_extraction: Future | None = None
    has_started_opening: bool = False
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    last_active: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    _lock: Lock = field(default_factory=Lock, repr=False)

    def touch(self) -> None:
        self.last_active = datetime.now(timezone.utc)

    def snapshot_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "anketa": self.anketa,
            "state": self.state,
            "usage": self.usage.summary(),
            "has_started_opening": self.has_started_opening,
            "created_at": self.created_at.isoformat(),
            "last_active": self.last_active.isoformat(),
        }


class SessionStore:
    """Потокобезопасный store + один общий ThreadPoolExecutor для фоновой extract-фазы."""

    def __init__(self, max_extract_workers: int = 4):
        self._sessions: dict[str, Session] = {}
        self._lock = asyncio.Lock()
        self.executor = ThreadPoolExecutor(
            max_workers=max_extract_workers, thread_name_prefix="mbk-extractor"
        )

    async def create(self, anketa: dict | None) -> Session:
        sid = uuid.uuid4().hex[:12]
        state = init_dialog_state(anketa or {})
        state["session_id"] = sid
        session = Session(
            id=sid,
            state=state,
            anketa=anketa,
            usage=SessionUsage(session_id=sid),
        )
        async with self._lock:
            self._sessions[sid] = session
        self.persist(session)
        return session

    async def get(self, session_id: str) -> Session | None:
        async with self._lock:
            return self._sessions.get(session_id)

    def get_sync(self, session_id: str) -> Session | None:
        """Версия для использования из синхронных контекстов (внутри Future)."""
        return self._sessions.get(session_id)

    def persist(self, session: Session) -> None:
        """Записать снапшот сессии на диск. Безопасно вызывать из любых потоков."""
        try:
            path = SESSIONS_DIR / f"{session.id}.json"
            tmp = path.with_suffix(".json.tmp")
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(session.snapshot_dict(), f, ensure_ascii=False, indent=2, default=str)
            tmp.replace(path)
        except Exception:  # noqa: BLE001 — снапшот не должен ронять пайплайн
            pass

    async def drop_stale(self, max_age_hours: int = 24) -> int:
        """Чистка сессий старше N часов (вызывать по таймеру из main.py при желании)."""
        cutoff = datetime.now(timezone.utc).timestamp() - max_age_hours * 3600
        async with self._lock:
            stale = [sid for sid, s in self._sessions.items() if s.last_active.timestamp() < cutoff]
            for sid in stale:
                del self._sessions[sid]
        return len(stale)

    def all_sessions(self) -> list[Session]:
        return list(self._sessions.values())
