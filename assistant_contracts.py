from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


FactScalar = str | int | float | bool | None
FactValue = FactScalar | list[FactScalar] | dict[str, FactScalar] | list[dict[str, FactScalar]]


class FactUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str
    value: FactValue
    confidence: Literal["high", "medium", "low"]
    source: Literal["latest_user_message", "form", "derived"]
    conflict: bool


class StatusUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str
    status: Literal[
        "known",
        "unknown",
        "needs_confirmation",
        "confirmed",
        "not_applicable",
        "conflict",
    ]


class ProductFitResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    recommended_product_id: str | None
    eligible_products: list[str] = Field(default_factory=list)
    blocked_products: list[str] = Field(default_factory=list)
    handoff_required: bool = False
    missing_facts: list[str] = Field(default_factory=list)


class TargetCompletion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_mode: str | None
    target_status: str | None
    next_action: str | None
    links_to_send_now: list[str] = Field(default_factory=list)
    crm_note: str | None


class AssistantTurn(BaseModel):
    """Один ход ассистента. Текст клиенту — это ОЧЕРЕДЬ коротких сообщений (как в мессенджере)."""

    model_config = ConfigDict(extra="forbid")

    # Раньше было одно длинное assistant_message: str.
    # Теперь — список из 1-4 коротких "пузырей", как пишет живой специалист:
    # короткая реакция -> при нужде причина/оценка -> один-три коротких вопроса ИЛИ следующий шаг.
    messages: list[str] = Field(
        default_factory=list,
        description=(
            "1-4 коротких сообщения подряд, каждое — отдельный пузырь в чате. "
            "Не один абзац. Вопрос (если он есть) — это последний пузырь."
        ),
    )
    dialog_phase: Literal[
        "qualification", "product_fit", "target_completion", "handoff", "fallback"
    ] = "qualification"
    fact_updates: list[FactUpdate] = Field(default_factory=list)
    status_updates: list[StatusUpdate] = Field(default_factory=list)
    product_fit_result: ProductFitResult | None = None
    target_completion: TargetCompletion | None = None
    internal_summary: str = ""

    @field_validator("messages")
    @classmethod
    def _clean_messages(cls, value: list[str]) -> list[str]:
        cleaned = [m.strip() for m in value if isinstance(m, str) and m.strip()]
        if not cleaned:
            raise ValueError("messages must contain at least one non-empty string")
        # Мягкий потолок: не даём боту "заспамить" клиента очередью из 10 пузырей.
        return cleaned[:4]

    @property
    def assistant_message(self) -> str:
        """Обратная совместимость: склейка пузырей в одну строку для логов/экспорта."""
        return "\n".join(self.messages)
