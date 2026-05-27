from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


FactScalar = str | int | float | bool | None
FactValue = FactScalar | list[FactScalar] | dict[str, FactScalar] | list[dict[str, FactScalar]]


class FactUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str
    value: FactValue
    confidence: Literal["high", "medium", "low"]
    source: Literal["latest_user_message", "form", "derived"]
    conflict: bool = False


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

    recommended_product_id: str | None = None
    eligible_products: list[str] = Field(default_factory=list)
    blocked_products: list[str] = Field(default_factory=list)
    handoff_required: bool = False
    missing_facts: list[str] = Field(default_factory=list)


class TargetCompletion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_mode: str | None = None
    target_status: str | None = None
    next_action: str | None = None
    links_to_send_now: list[str] = Field(default_factory=list)
    crm_note: str | None = None


class StateUpdate(BaseModel):
    """Чисто СЕРВЕРНЫЙ результат разбора хода. Клиент его НЕ видит.

    Здесь больше нет текста для клиента (`messages`). Видимый ответ генерируется
    отдельным разговорным вызовом и стримится как обычный текст. Этот контракт нужен
    только бэкенду/CRM: какие факты обновить, в какой фазе диалог, что продавать.
    """

    model_config = ConfigDict(extra="forbid")

    dialog_phase: Literal[
        "qualification", "product_fit", "target_completion", "handoff", "fallback"
    ] = "qualification"
    fact_updates: list[FactUpdate] = Field(default_factory=list)
    status_updates: list[StatusUpdate] = Field(default_factory=list)
    product_fit_result: ProductFitResult | None = None
    target_completion: TargetCompletion | None = None
    internal_summary: str = ""


# Обратная совместимость со старым именем.
AssistantTurn = StateUpdate
