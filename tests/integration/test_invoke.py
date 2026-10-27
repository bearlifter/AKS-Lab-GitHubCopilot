"""ASGI loopback tests for the agents' A2A /invoke contract."""

from __future__ import annotations

from http import HTTPStatus

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from src.agents.inventory.server import app as inventory_app
from src.agents.logistics.server import app as logistics_app
from src.agents.orchestrator.server import app as orchestrator_app
from src.agents.pricing.server import app as pricing_app
from src.agents.supplier.server import app as supplier_app
from src.shared.server import InvokeResponse
from tests.agents._mock import MockChatClient


def _fake_copilot_client() -> object:
    return object()


AGENT_APPS: tuple[tuple[str, FastAPI], ...] = (
    ("inventory", inventory_app),
    ("supplier", supplier_app),
    ("logistics", logistics_app),
    ("pricing", pricing_app),
    ("orchestrator", orchestrator_app),
)


@pytest.mark.asyncio
@pytest.mark.parametrize(("agent_name", "app"), AGENT_APPS, ids=[name for name, _ in AGENT_APPS])
async def test_agent_invoke_returns_a2a_response_over_asgi(
    agent_name: str, app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    MockChatClient.reset(responses=['{"sku":"ZS-1042","summary":"recovery ready"}'])
    monkeypatch.delenv("ZAVA_KV_URL", raising=False)
    monkeypatch.setattr("src.shared.server.hydrate_from_keyvault", _no_keyvault_hydration)
    agent_module = f"src.agents.{agent_name}.agent"
    monkeypatch.setattr(f"{agent_module}.GitHubCopilotAgent", MockChatClient)
    monkeypatch.setattr(f"{agent_module}.build_copilot_client", _fake_copilot_client)

    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url=f"http://{agent_name}") as client:
            response = await client.post(
                "/invoke",
                json={"run_id": f"lab04-{agent_name}", "goal": "Build a plan for SKU ZS-1042 at store-101."},
            )

    assert response.status_code == HTTPStatus.OK
    result = InvokeResponse.model_validate(response.json())
    assert result.run_id == f"lab04-{agent_name}"
    assert "ZS-1042" in result.output
    assert isinstance(result.tool_calls, list)


async def _no_keyvault_hydration() -> None:
    return None
