"""Process-boundary contracts for the ZavaShop orchestrator."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class Goal(BaseModel):
    """Structured stock-out goal accepted by the /plan endpoint."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    goal: str = Field(min_length=1, description="Natural-language stock-out recovery goal.")
    sku: str = Field(min_length=1, description="SKU to recover.")
    store_id: str | None = Field(default=None, description="Target store identifier for a single-store plan.")


class Plan(BaseModel):
    """Stock-out response plan assembled by the orchestrator."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    sku: str
    store_id: str
    stock_view: str
    price_view: str
    po_view: str
    shipping_view: str
    summary: str
    next_actions: list[str]


class PlanRefusal(BaseModel):
    """Typed refusal for requests outside the single-store planning scope."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    status: Literal["refused"] = "refused"
    reason: str = Field(min_length=1)
