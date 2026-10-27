"""Loopback fleet tests for the orchestrator's real A2A specialist client."""

from __future__ import annotations

from collections import Counter
from collections.abc import AsyncGenerator
from contextlib import AsyncExitStack
from dataclasses import dataclass
from http import HTTPStatus

import httpx
import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient, Request, Response

from src.agents.inventory.server import app as inventory_app
from src.agents.logistics.server import app as logistics_app
from src.agents.orchestrator.contracts import Plan, PlanRefusal
from src.agents.orchestrator.server import create_app
from src.agents.pricing.server import app as pricing_app
from src.agents.supplier.server import app as supplier_app
from src.shared.settings import Settings
from tests.agents._mock import MockChatClient

SPECIALISTS: tuple[tuple[str, FastAPI], ...] = (
    ("inventory", inventory_app),
    ("supplier", supplier_app),
    ("logistics", logistics_app),
    ("pricing", pricing_app),
)
AGENT_NAMES = (*(name for name, _ in SPECIALISTS), "orchestrator")


@dataclass(frozen=True)
class Fleet:
    """In-process apps and counters for one full orchestrator request."""

    orchestrator_client: AsyncClient
    specialist_calls: Counter[str]


@pytest.fixture
async def fleet(monkeypatch: pytest.MonkeyPatch) -> AsyncGenerator[Fleet, None]:
    monkeypatch.delenv("ZAVA_KV_URL", raising=False)
    MockChatClient.reset(responses=['{"result":"mock specialist response"}'] * len(SPECIALISTS))
    for agent_name in AGENT_NAMES:
        agent_module = f"src.agents.{agent_name}.agent"
        monkeypatch.setattr(f"{agent_module}.GitHubCopilotAgent", MockChatClient)
        monkeypatch.setattr(f"{agent_module}.build_copilot_client", _fake_copilot_client)

    specialist_calls: Counter[str] = Counter()
    specialist_apps = dict(SPECIALISTS)

    class RecordingASGITransport(ASGITransport):
        def __init__(self, *, specialist_name: str, app: FastAPI) -> None:
            self.specialist_name = specialist_name
            super().__init__(app=app)

        async def handle_async_request(self, request: Request) -> Response:
            specialist_calls[self.specialist_name] += 1
            return await super().handle_async_request(request)

    original_async_client = httpx.AsyncClient

    class RoutedAsyncClient(original_async_client):
        def __init__(self, *, timeout: httpx.Timeout) -> None:
            mounts = {
                f"http://{specialist_name}.test": RecordingASGITransport(
                    specialist_name=specialist_name,
                    app=specialist_app,
                )
                for specialist_name, specialist_app in specialist_apps.items()
            }
            super().__init__(timeout=timeout, mounts=mounts)

    settings = Settings(
        inventory_a2a_url="http://inventory.test/invoke",
        supplier_a2a_url="http://supplier.test/invoke",
        logistics_a2a_url="http://logistics.test/invoke",
        pricing_a2a_url="http://pricing.test/invoke",
    )
    orchestrator_app = create_app(settings=settings)
    agent_apps = (*SPECIALISTS, ("orchestrator", orchestrator_app))
    monkeypatch.setattr("src.agents.orchestrator.a2a.httpx.AsyncClient", RoutedAsyncClient)

    async with AsyncExitStack() as stack:
        for _, app in agent_apps:
            await stack.enter_async_context(app.router.lifespan_context(app))
        orchestrator_client = await stack.enter_async_context(
            original_async_client(transport=ASGITransport(app=orchestrator_app), base_url="http://orchestrator.test")
        )
        yield Fleet(orchestrator_client=orchestrator_client, specialist_calls=specialist_calls)


@pytest.mark.asyncio
async def test_plan_routes_to_specialist_apps_over_real_a2a_client(fleet: Fleet) -> None:
    response = await fleet.orchestrator_client.post(
        "/plan",
        json={
            "goal": "Recover SKU ZS-1042 at store-101.",
            "sku": "ZS-1042",
            "store_id": "store-101",
        },
    )

    assert response.status_code == HTTPStatus.OK
    plan = Plan.model_validate(response.json())
    assert plan.sku == "ZS-1042"
    assert plan.store_id == "store-101"
    assert "mock specialist response" in plan.stock_view
    assert "mock specialist response" in plan.price_view
    assert "mock specialist response" in plan.po_view
    assert "mock specialist response" in plan.shipping_view
    assert plan.summary
    assert plan.next_actions
    assert fleet.specialist_calls == Counter({name: 1 for name, _ in SPECIALISTS})


@pytest.mark.asyncio
async def test_regional_plan_without_store_is_refused_before_any_specialist_call(fleet: Fleet) -> None:
    response = await fleet.orchestrator_client.post(
        "/plan",
        json={
            "goal": "Plan recovery across the Northeast region for SKU ZS-1042.",
            "sku": "ZS-1042",
        },
    )

    assert response.status_code == HTTPStatus.OK
    refusal = PlanRefusal.model_validate(response.json())
    assert refusal.status == "refused"
    assert "single store" in refusal.reason
    assert not fleet.specialist_calls


def _fake_copilot_client() -> object:
    return object()
