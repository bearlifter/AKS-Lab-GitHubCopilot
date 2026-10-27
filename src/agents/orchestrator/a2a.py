"""A2A HTTP client for orchestrator-to-specialist calls."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from uuid import uuid4

import httpx
from pydantic import BaseModel, ConfigDict, Field

from src.shared.server import InvokeRequest, InvokeResponse
from src.shared.settings import Settings


@dataclass(frozen=True)
class SpecialistClient:
    """HTTP client for invoking ZavaShop specialist agents."""

    settings: Settings

    async def invoke(self, *, name: str, url: str, goal: str, run_id: str | None = None) -> str:
        request = InvokeRequest(run_id=run_id or uuid4().hex, goal=goal, context={"caller": "orchestrator"})
        timeout = httpx.Timeout(connect=10.0, read=120.0, write=30.0, pool=10.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(url, json=request.model_dump())
            response.raise_for_status()
        envelope = InvokeResponse.model_validate(response.json())
        return envelope.output


class SpecialistInvoker(Protocol):
    """Protocol for specialist invokers used by production code and tests."""

    @property
    def settings(self) -> Settings:
        """Settings used to resolve specialist endpoint URLs."""

        ...

    async def invoke(self, *, name: str, url: str, goal: str, run_id: str | None = None) -> str: ...


class FanOutGoals(BaseModel):
    """Specialist goals generated for one stock-out request."""

    model_config = ConfigDict(frozen=True)

    inventory: str = Field(min_length=1)
    supplier: str = Field(min_length=1)
    logistics: str = Field(min_length=1)
    pricing: str = Field(min_length=1)


def build_specialist_goals(*, sku: str, store_id: str, supplier_quantity: int = 80) -> FanOutGoals:
    """Build deterministic specialist goals for a stock-out response plan."""

    po_hint = f"PO candidate for {sku} at {store_id}"
    return FanOutGoals(
        inventory=f"Check stock risk for SKU {sku} at {store_id}; include nearby store and warehouse options.",
        supplier=f"List suppliers and draft a purchase order for SKU {sku} at {store_id} quantity {supplier_quantity}.",
        logistics=f"Quote shipment for {po_hint} to {store_id} quantity {supplier_quantity}.",
        pricing=f"Recommend price for SKU {sku} at {store_id} with high demand signal and critical stock risk.",
    )
