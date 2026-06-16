"""
Маскировка персональных данных перед отправкой в LLM.

Архитектурный принцип:
  - На нашем сервере хранятся ПОЛНЫЕ данные клиента (для CRM-выгрузки лида).
  - В разговорную модель (Qwen) и в извлекатель уходит ОБЕЗЛИЧЕННАЯ копия.
  - ФЗ-152: трансграничная передача обезличенных данных существенно мягче по требованиям.

Что маскируем и почему:
  - Имя: оставляем ТОЛЬКО первое слово (имя). Фамилию/отчество скрываем. Имя само по себе
    не идентифицирует лицо (не ПД в строгом смысле) и нужно боту для живого обращения.
  - Телефон: полностью.
  - Дата рождения: оставляем только год (нужен для возрастных стопов).
  - Адрес: оставляем город/регион (нужен для региональных стопов), скрываем улицу/дом.
  - Финансовые суммы НЕ маскируем — без них бот не работает (БФЛ-формула, оценка нагрузки,
    выбор продукта). Суммы сами по себе не ПД.

Демаскинг ответа НЕ делаем: модель не видела оригинал, «вспомнить» его не может.
"""
from __future__ import annotations

import copy
import re
from dataclasses import dataclass, field
from typing import Any


_PHONE_PATTERN = re.compile(
    r"(?:\+7|\b8)[\s\-()]*\d{3}[\s\-()]*\d{3}[\s\-()]*\d{2}[\s\-()]*\d{2}"
)
_DATE_PATTERN = re.compile(
    r"\b(\d{1,2})[./\-](\d{1,2})[./\-](19\d{2}|20[0-2]\d)\b"
    r"|\b(19\d{2}|20[0-2]\d)[./\-](\d{1,2})[./\-](\d{1,2})\b"
)


@dataclass
class Masker:
    """Маскировщик ПД, привязанный к одной сессии. Карта замен строится из current_facts."""

    direct: dict[str, str] = field(default_factory=dict)
    first_name: str | None = None

    @classmethod
    def from_facts(cls, facts: dict[str, Any] | None) -> "Masker":
        m = cls()
        if not isinstance(facts, dict):
            return m
        client = facts.get("client") if isinstance(facts.get("client"), dict) else {}

        # === ФИО: оставляем имя, маскируем остальное ===
        full_name = client.get("full_name", "")
        if isinstance(full_name, str) and full_name.strip():
            parts = full_name.strip().split()
            if len(parts) >= 2:
                first = min(parts, key=len)  # имя обычно короче фамилии
                m.first_name = first
                for part in parts:
                    if part != first and len(part) >= 2:
                        m.direct[part] = "[фамилия]"
            elif len(parts) == 1 and len(parts[0]) >= 2:
                m.first_name = parts[0]

        # === Телефон (плюс нормализованные варианты) ===
        phone = client.get("phone", "")
        if isinstance(phone, str) and phone.strip():
            m.direct[phone] = "[телефон]"
            digits = re.sub(r"\D", "", phone)
            if len(digits) == 11 and digits[0] in ("7", "8"):
                for variant in (digits, "+" + digits, "+7" + digits[1:], "8" + digits[1:]):
                    m.direct[variant] = "[телефон]"

        # === Дата рождения: оставляем год ===
        bd = client.get("birth_date", "")
        if isinstance(bd, str) and bd.strip():
            ym = re.search(r"\b(19\d{2}|20[0-2]\d)\b", bd)
            if ym:
                m.direct[bd] = f"год рождения {ym.group()}"

        # === Адрес: оставляем город (до первой запятой) ===
        for addr_key in ("registration_address", "living_address"):
            addr = client.get(addr_key, "")
            if isinstance(addr, str) and "," in addr:
                m.direct[addr] = f"{addr.split(',')[0].strip()} (адрес скрыт)"

        return m

    def mask_text(self, text: str) -> str:
        if not isinstance(text, str) or not text:
            return text
        # Сначала регекспы (телефон/дата в свободном виде), потом точные замены из анкеты —
        # иначе подстановка «год рождения 1985» из direct сама попадёт под date-regexp.
        text = _PHONE_PATTERN.sub("[телефон]", text)
        text = _DATE_PATTERN.sub(_mask_date_to_year, text)
        for original in sorted(self.direct.keys(), key=len, reverse=True):
            # Дату рождения в свободном тексте уже накрыл regexp — точную замену из анкеты
            # применяем только если оригинал ещё буквально присутствует.
            if original in text:
                text = text.replace(original, self.direct[original])
        return text

    def mask_facts(self, facts: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(facts, dict):
            return facts
        masked = copy.deepcopy(facts)
        client = masked.get("client") if isinstance(masked.get("client"), dict) else None
        if client:
            if isinstance(client.get("full_name"), str):
                parts = client["full_name"].strip().split()
                if self.first_name and len(parts) >= 2:
                    client["full_name"] = f"{self.first_name} [фамилия]"
            if client.get("phone"):
                client["phone"] = "[телефон]"
            if isinstance(client.get("birth_date"), str):
                ym = re.search(r"\b(19\d{2}|20[0-2]\d)\b", client["birth_date"])
                if ym:
                    client["birth_date"] = f"{ym.group()} (год рождения)"
            for k in ("registration_address", "living_address"):
                v = client.get(k)
                if isinstance(v, str) and "," in v:
                    client[k] = v.split(",")[0].strip() + " (адрес скрыт)"
        return masked

    def mask_history(self, history: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if not isinstance(history, list):
            return history
        return [{**msg, "content": self.mask_text(msg.get("content", ""))} for msg in history]

    def mask_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Копия payload, готовая к отправке в LLM: маскированы факты, история, реплика, сводка."""
        m = copy.copy(payload)
        if "current_facts" in m:
            m["current_facts"] = self.mask_facts(m["current_facts"])
        if "short_history" in m:
            m["short_history"] = self.mask_history(m["short_history"])
        if "latest_user_message" in m:
            m["latest_user_message"] = self.mask_text(str(m.get("latest_user_message", "")))
        if isinstance(m.get("business_rules_summary"), str):
            m["business_rules_summary"] = self.mask_text(m["business_rules_summary"])
        return m


def _mask_date_to_year(match: re.Match) -> str:
    g = match.groups()
    year = g[2] or g[3]
    if year and 1900 <= int(year) <= 2030:
        return f"{year} год"
    return match.group()


def mask_payload_for_llm(payload: dict[str, Any], enable: bool) -> dict[str, Any]:
    """Точка входа для llm_agent: если включено — маскируем payload по фактам из него же."""
    if not enable:
        return payload
    masker = Masker.from_facts(payload.get("current_facts"))
    return masker.mask_payload(payload)
