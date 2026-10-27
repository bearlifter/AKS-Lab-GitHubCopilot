"""Unit tests for the ZavaShop orchestrator agent."""

from __future__ import annotations

import pytest

from src.agents.orchestrator.agent import build_agent
from src.shared.settings import Settings
from tests.agents._mock import MockChatClient, captured_options


async def test_orchestrator_agent_uses_copilot_with_a2a_tools(monkeypatch: pytest.MonkeyPatch) -> None:
    MockChatClient.reset(responses=['{"summary":"ok"}'])
    monkeypatch.setattr("src.agents.orchestrator.agent.GitHubCopilotAgent", MockChatClient)

    agent = await build_agent(Settings())
    response = await agent.run("Build a plan for SKU ZS-1042 at store-101.")
    options = captured_options()

    assert "summary" in response.output_text
    assert "gpt-5.5" == options.get("model")
    assert "mcp_servers" not in options
    assert MockChatClient.messages == ["Build a plan for SKU ZS-1042 at store-101."]


@pytest.mark.asyncio
async def test_orchestrator_agent_returns_refusal(monkeypatch: pytest.MonkeyPatch) -> None:
    MockChatClient.reset(responses=['{"refuse":"regional planning requires a single store"}'])
    monkeypatch.setattr("src.agents.orchestrator.agent.GitHubCopilotAgent", MockChatClient)

    agent = await build_agent(Settings())
    response = await agent.run("Build a regional plan for SKU ZS-1042.")

    assert "refuse" in response.output_text
    assert "single store" in response.output_text


@pytest.mark.asyncio
async def test_orchestrator_agent_propagates_tool_error(monkeypatch: pytest.MonkeyPatch) -> None:
    MockChatClient.reset(errors=[RuntimeError("A2A specialist unavailable")])
    monkeypatch.setattr("src.agents.orchestrator.agent.GitHubCopilotAgent", MockChatClient)

    agent = await build_agent(Settings())

    with pytest.raises(RuntimeError, match="A2A specialist unavailable"):
        await agent.run("Build a plan for SKU ZS-1042 at store-101.")
