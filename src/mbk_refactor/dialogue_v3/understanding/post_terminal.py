"""Post-terminal clarification topic detection for dialogue_v3 turns."""

from __future__ import annotations

import re

from .text import contains_any, normalize_text

POST_TERMINAL_NEXT_STEP_PATTERNS = (
    "что дальше",
    "что делать",
    "что значит отдельный разбор",
    "куда нажать",
)
POST_TERMINAL_CONTACT_PATTERNS = (
    "кто со мной свяжется",
    "кто свяжется",
    "как со мной свяжутся",
    "когда со мной свяжутся",
)
BANKRUPTCY_CLARIFICATION_PATTERNS = (
    "это банкротство",
    "можно без банкротства",
    "банкротство или реструктуризация",
    "банкротство или можно",
)


def detect_post_terminal_topic(text: str) -> str | None:
    """Return a compact post-terminal clarification topic, if the turn contains one."""

    text = normalize_text(text)
    if _is_bankruptcy_clarification(text):
        return "bankruptcy_clarification"
    if _is_contact_question(text):
        return "contact_question"
    if _is_next_step_question(text):
        return "next_step"
    return None


def _is_next_step_question(text: str) -> bool:
    """Detect clarification about the next operational step."""

    if contains_any(text, POST_TERMINAL_NEXT_STEP_PATTERNS):
        return True
    return any(
        re.search(pattern, text)
        for pattern in (
            r"\bдальше\b.{0,20}\b(?:что|как|будет|делать)\b",
            r"\b(?:куда|где)\b.{0,20}\bпереход\w*\b",
            r"\bнужно\b.{0,20}\bкуда[-\s]?то\b.{0,20}\bпереход\w*\b",
            r"\bспециалист\b.{0,30}\b(?:сам\s+)?посмотр\w*\b",
            r"\bкто\b.{0,20}\bдальше\b.{0,20}\bпосмотр\w*\b",
            r"\bкак\b.{0,20}\bдальше\b.{0,20}\bбуд\w*\b",
        )
    )


def _is_bankruptcy_clarification(text: str) -> bool:
    """Detect debt-procedure clarification without deciding the route."""

    if contains_any(text, BANKRUPTCY_CLARIFICATION_PATTERNS):
        return True
    return any(
        re.search(pattern, text)
        for pattern in (
            r"\bбанкротств\w*\b.{0,30}\bили\b",
            r"\bэто\b.{0,20}\bреструктуризац\w*\b",
            r"\bбез\s+суда\b.{0,20}\bможн\w*\b",
            r"\bсписан\w*\b.{0,20}\bили\b.{0,20}\bплат\w*\b",
        )
    )


def _is_contact_question(text: str) -> bool:
    """Detect clarification about who contacts the client and when."""

    if contains_any(text, POST_TERMINAL_CONTACT_PATTERNS):
        return True
    return any(
        re.search(pattern, text)
        for pattern in (
            r"\bкогда\b.{0,25}\bсвяж\w*\b",
            r"\bмне\b.{0,20}\bпозвон\w*\b",
            r"\bспециалист\b.{0,25}\bнапиш\w*\b",
            r"\bждать\b.{0,20}\b(?:звонк\w*|сообщен\w*)\b",
        )
    )
