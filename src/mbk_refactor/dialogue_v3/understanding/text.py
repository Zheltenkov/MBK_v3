"""Shared deterministic text utilities for turn understanding."""

from __future__ import annotations

import re

ACTIVE_DIALOG_CORRECTION_PATTERNS = (
    "я уже писал",
    "я уже писала",
    "я уже написал",
    "я уже написала",
    "я уже говорил",
    "я уже говорила",
    "я уже отвечал",
    "я уже отвечала",
    "уже писал",
    "уже писала",
    "уже написал",
    "уже написала",
    "уже говорил",
    "уже говорила",
    "уже отвечал",
    "уже отвечала",
    "я же сказал",
    "я же сказала",
    "выше написал",
    "выше написала",
    "я это уже указал",
    "я это уже указала",
    "это уже указал",
    "это уже указала",
    "повторяю",
    "как писал",
    "как писала",
    "как говорил",
    "как говорила",
)


def normalize_text(text: str) -> str:
    """Normalize user text for deterministic phrase matching."""

    return " ".join(text.lower().replace("ё", "е").split())


def contains_any(text: str, patterns: tuple[str, ...]) -> bool:
    return any(pattern in text for pattern in patterns)


def matches_any_regex(text: str, patterns: tuple[re.Pattern[str], ...]) -> bool:
    return any(pattern.search(text) for pattern in patterns)
