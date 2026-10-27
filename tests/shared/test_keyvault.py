"""Tests for optional Key Vault environment hydration."""

from __future__ import annotations

import builtins
import os
from collections.abc import Mapping, Sequence
from types import ModuleType, SimpleNamespace

import azure.identity
import azure.keyvault.secrets
import pytest
from azure.core.exceptions import ResourceNotFoundError

from src.shared.keyvault import hydrate_key_vault_secrets


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

    assert await hydrate_key_vault_secrets(None) == {}
    assert await hydrate_key_vault_secrets("") == {}


@pytest.mark.asyncio
async def test_key_vault_hydrates_mappings_and_preserves_csi_token(monkeypatch: pytest.MonkeyPatch) -> None:
    values = {
        "GITHUB-TOKEN": "vault-token",
        "INVENTORY-MCP-URL": "https://inventory.example/mcp",
        "SUPPLIER-MCP-URL": "https://supplier.example/mcp",
        "SHIPPING-MCP-URL": "https://shipping.example/mcp",
        "PRICING-MCP-URL": "https://pricing.example/mcp",
    }
    requested: list[str] = []

    class FakeCredential:
        def close(self) -> None:
            pass

    class FakeSecretClient:
        def __init__(self, *, vault_url: str, credential: object) -> None:
            assert vault_url == "https://vault.example"

        def get_secret(self, name: str) -> SimpleNamespace:
            requested.append(name)
            return SimpleNamespace(value=values[name])

        def close(self) -> None:
            pass

    monkeypatch.setattr(azure.identity, "DefaultAzureCredential", FakeCredential)
    monkeypatch.setattr(azure.keyvault.secrets, "SecretClient", FakeSecretClient)
    monkeypatch.setenv("GITHUB_TOKEN", "csi-token")

    hydrated = await hydrate_key_vault_secrets("https://vault.example")

    assert requested == ["INVENTORY-MCP-URL", "SUPPLIER-MCP-URL", "SHIPPING-MCP-URL", "PRICING-MCP-URL"]
    assert hydrated == {
        "ZAVA_INVENTORY_MCP_URL": values["INVENTORY-MCP-URL"],
        "ZAVA_SUPPLIER_MCP_URL": values["SUPPLIER-MCP-URL"],
        "ZAVA_SHIPPING_MCP_URL": values["SHIPPING-MCP-URL"],
        "ZAVA_PRICING_MCP_URL": values["PRICING-MCP-URL"],
    }
    assert os.environ["GITHUB_TOKEN"] == "csi-token"


@pytest.mark.asyncio
async def test_missing_vault_secrets_are_skipped(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeCredential:
        def close(self) -> None:
            pass

    class FakeSecretClient:
        def __init__(self, *, vault_url: str, credential: object) -> None:
            pass

        def get_secret(self, name: str) -> SimpleNamespace:
            if name == "INVENTORY-MCP-URL":
                return SimpleNamespace(value="https://inventory.example/mcp")
            raise ResourceNotFoundError(name)

        def close(self) -> None:
            pass

    monkeypatch.setattr(azure.identity, "DefaultAzureCredential", FakeCredential)
    monkeypatch.setattr(azure.keyvault.secrets, "SecretClient", FakeSecretClient)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)

    hydrated = await hydrate_key_vault_secrets("https://vault.example")

    assert hydrated == {"ZAVA_INVENTORY_MCP_URL": "https://inventory.example/mcp"}
