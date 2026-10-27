"""API tests for the ZavaShop orchestrator /plan endpoint."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from http import HTTPStatus

import pytest
from httpx import ASGITransport, AsyncClient

from src.agents.orchestrator.server import create_app
from src.shared.settings import Settings


@dataclass(frozen=True)
class FakeSpecialistClient:
    settings: Settings

    async def invoke(self, *, name: str, url: str, goal: str, run_id: str | None = None) -> str:
        return f"{name} output for {goal} via {url}"


class RecordingSpecialistClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.calls: list[str] = []

    async def invoke(self, *, name: str, url: str, goal: str, run_id: str | None = None) -> str:
        self.calls.append(name)
        return f"{name} output for {goal} via {url}"


@pytest.mark.asyncio
async def test_plan_endpoint_returns_frozen_plan() -> None:
    settings = Settings(
        inventory_a2a_url="http://inventory.local/invoke",
        supplier_a2a_url="http://supplier.local/invoke",
        logistics_a2a_url="http://logistics.local/invoke",
        pricing_a2a_url="http://pricing.local/invoke",
    )
    app = create_app(settings=settings, specialist_client=FakeSpecialistClient(settings=settings))
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/plan",
            json={
                "goal": "Store 101 will stock out of SKU ZS-1042 by Friday.",
                "sku": "ZS-1042",
                "store_id": "store-101",
            },
        )

    assert response.status_code == HTTPStatus.OK
    body = response.json()
    assert body["sku"] == "ZS-1042"
    assert body["store_id"] == "store-101"
    assert "inventory output" in body["stock_view"]
    assert "supplier output" in body["po_view"]
    assert "logistics output" in body["shipping_view"]
    assert "pricing output" in body["price_view"]
    assert body["next_actions"]


@pytest.mark.asyncio
async def test_regional_plan_without_store_id_is_refused_without_specialist_calls() -> None:
    settings = Settings(
        inventory_a2a_url="http://inventory.local/invoke",
        supplier_a2a_url="http://supplier.local/invoke",
        logistics_a2a_url="http://logistics.local/invoke",
        pricing_a2a_url="http://pricing.local/invoke",
    )
    specialist_client = RecordingSpecialistClient(settings=settings)
    app = create_app(settings=settings, specialist_client=specialist_client)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/plan",
            json={
                "goal": "The Northeast region may stock out of SKU ZS-1042. Build a regional recovery plan.",
                "sku": "ZS-1042",
            },
        )

    assert response.status_code == HTTPStatus.OK
    body = response.json()
    assert body["status"] == "refused"
    assert body["reason"].strip()
    assert specialist_client.calls == []


class ConcurrentSpecialistClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.calls: list[str] = []
        self.parallel_finished: set[str] = set()
        self.both_parallel_started = asyncio.Event()

    async def invoke(self, *, name: str, url: str, goal: str, run_id: str | None = None) -> str:
        self.calls.append(name)
        if name in {"inventory", "pricing"}:
            if {"inventory", "pricing"}.issubset(self.calls):
                self.both_parallel_started.set()
            await asyncio.wait_for(self.both_parallel_started.wait(), timeout=1)
            self.parallel_finished.add(name)
        elif name == "supplier":
            assert self.parallel_finished == {"inventory", "pricing"}
        else:
            assert name == "logistics"
            assert self.calls[-2:] == ["supplier", "logistics"]
        return f"{name} output"


@pytest.mark.asyncio
async def test_plan_workflow_runs_stock_and_price_in_parallel_then_supplier_and_logistics() -> None:
    settings = Settings()
    specialist_client = ConcurrentSpecialistClient(settings=settings)
    app = create_app(settings=settings, specialist_client=specialist_client)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/plan",
            json={"goal": "Recover SKU ZS-1042", "sku": "ZS-1042", "store_id": "store-101"},
        )

    assert response.status_code == HTTPStatus.OK
    assert set(specialist_client.calls[:2]) == {"inventory", "pricing"}
    assert specialist_client.calls[2:] == ["supplier", "logistics"]


@pytest.mark.asyncio
async def test_plan_workflow_failure_is_explicit() -> None:
    class FailingSpecialistClient(RecordingSpecialistClient):
        async def invoke(self, *, name: str, url: str, goal: str, run_id: str | None = None) -> str:
            if name == "supplier":
                raise RuntimeError("specialist unavailable")
            return await super().invoke(name=name, url=url, goal=goal, run_id=run_id)

    settings = Settings()
    app = create_app(settings=settings, specialist_client=FailingSpecialistClient(settings=settings))
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/plan",
            json={"goal": "Recover SKU ZS-1042", "sku": "ZS-1042", "store_id": "store-101"},
        )

    assert response.status_code == HTTPStatus.BAD_GATEWAY
    assert response.json() == {"detail": "Plan workflow failed"}
