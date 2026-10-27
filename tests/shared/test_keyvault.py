"""Tests for optional asynchronous Key Vault environment hydration."""

from __future__ import annotations

import builtins
import os
from collections.abc import Mapping, Sequence
from types import ModuleType, SimpleNamespace

import azure.identity.aio
import azure.keyvault.secrets.aio
import pytest
from azure.core.exceptions import ResourceNotFoundError

from src.shared.keyvault import hydrate_from_keyvault


@pytest.mark.asyncio
async def test_unset_key_vault_url_does_not_import_azure_sdk(monkeypatch: pytest.MonkeyPatch) -> None:
    original_import = builtins.__import__

    def guarded_import(
        name: str,
        globals: Mapping[str, object] | None = None,
        locals: Mapping[str, object] | None = None,
        fromlist: Sequence[str] | None = None,
        level: int = 0,
    ) -> ModuleType:
        if name.startswith("azure."):
            raise AssertionError("Azure SDK imported without a Key Vault URL")
        return original_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", guarded_import)
    monkeypatch.delenv("ZAVA_KV_URL", raising=False)

    await hydrate_from_keyvault()


@pytest.mark.asyncio
async def test_hydration_uses_async_clients_and_preserves_every_existing_environment_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    values = {
        "GITHUB-TOKEN": "vault-token",
        "INVENTORY-MCP-URL": "https://inventory.example/mcp",
        "SUPPLIER-MCP-URL": "https://supplier.example/mcp",
        "SHIPPING-MCP-URL": "https://shipping.example/mcp",
        "PRICING-MCP-URL": "https://pricing.example/mcp",
    }
    requested: list[str] = []
    credential_closed = False
    client_closed = False

    class FakeCredential:
        async def __aenter__(self) -> FakeCredential:
            return self

        async def __aexit__(self, *_: object) -> None:
            nonlocal credential_closed
            credential_closed = True

    class FakeSecretClient:
        def __init__(self, *, vault_url: str, credential: object) -> None:
            assert vault_url == "https://vault.example"
            assert isinstance(credential, FakeCredential)

        async def __aenter__(self) -> FakeSecretClient:
            return self

        async def __aexit__(self, *_: object) -> None:
            nonlocal client_closed
            client_closed = True

        async def get_secret(self, name: str) -> SimpleNamespace:
            requested.append(name)
            return SimpleNamespace(value=values[name])

    monkeypatch.setattr(azure.identity.aio, "DefaultAzureCredential", FakeCredential)
    monkeypatch.setattr(azure.keyvault.secrets.aio, "SecretClient", FakeSecretClient)
    monkeypatch.setenv("ZAVA_KV_URL", "https://vault.example")
    monkeypatch.setenv("GITHUB_TOKEN", "csi-token")
    monkeypatch.setenv("ZAVA_SUPPLIER_MCP_URL", "preconfigured-supplier-url")
    monkeypatch.delenv("ZAVA_INVENTORY_MCP_URL", raising=False)
    monkeypatch.delenv("ZAVA_SHIPPING_MCP_URL", raising=False)
    monkeypatch.delenv("ZAVA_PRICING_MCP_URL", raising=False)

    await hydrate_from_keyvault()

    assert requested == ["INVENTORY-MCP-URL", "SHIPPING-MCP-URL", "PRICING-MCP-URL"]
    assert os.environ["GITHUB_TOKEN"] == "csi-token"
    assert os.environ["ZAVA_SUPPLIER_MCP_URL"] == "preconfigured-supplier-url"
    assert os.environ["ZAVA_INVENTORY_MCP_URL"] == values["INVENTORY-MCP-URL"]
    assert os.environ["ZAVA_SHIPPING_MCP_URL"] == values["SHIPPING-MCP-URL"]
    assert os.environ["ZAVA_PRICING_MCP_URL"] == values["PRICING-MCP-URL"]
    assert client_closed
    assert credential_closed


@pytest.mark.asyncio
async def test_missing_vault_secrets_are_skipped(monkeypatch: pytest.MonkeyPatch) -> None:
    requested: list[str] = []
    credential_closed = False
    client_closed = False

    class FakeCredential:
        async def __aenter__(self) -> FakeCredential:
            return self

        async def __aexit__(self, *_: object) -> None:
            nonlocal credential_closed
            credential_closed = True

    class FakeSecretClient:
        def __init__(self, *, vault_url: str, credential: object) -> None:
            pass

        async def __aenter__(self) -> FakeSecretClient:
            return self

        async def __aexit__(self, *_: object) -> None:
            nonlocal client_closed
            client_closed = True

        async def get_secret(self, name: str) -> SimpleNamespace:
            requested.append(name)
            if name == "INVENTORY-MCP-URL":
                return SimpleNamespace(value="https://inventory.example/mcp")
            raise ResourceNotFoundError(name)

    monkeypatch.setattr(azure.identity.aio, "DefaultAzureCredential", FakeCredential)
    monkeypatch.setattr(azure.keyvault.secrets.aio, "SecretClient", FakeSecretClient)
    monkeypatch.setenv("ZAVA_KV_URL", "https://vault.example")
    for name in (
        "GITHUB_TOKEN",
        "ZAVA_INVENTORY_MCP_URL",
        "ZAVA_SUPPLIER_MCP_URL",
        "ZAVA_SHIPPING_MCP_URL",
        "ZAVA_PRICING_MCP_URL",
    ):
        monkeypatch.delenv(name, raising=False)

    await hydrate_from_keyvault()

    assert requested == [
        "GITHUB-TOKEN",
        "INVENTORY-MCP-URL",
        "SUPPLIER-MCP-URL",
        "SHIPPING-MCP-URL",
        "PRICING-MCP-URL",
    ]
    assert os.environ["ZAVA_INVENTORY_MCP_URL"] == "https://inventory.example/mcp"
    assert "GITHUB_TOKEN" not in os.environ
    assert client_closed
    assert credential_closed
