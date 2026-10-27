"""Optional Azure Key Vault secret hydration for service startup."""

from __future__ import annotations

import asyncio
import os

import structlog

log = structlog.get_logger(__name__)

_SECRET_ENVIRONMENT_NAMES = {
    "GITHUB-TOKEN": "GITHUB_TOKEN",
    "INVENTORY-MCP-URL": "ZAVA_INVENTORY_MCP_URL",
    "SUPPLIER-MCP-URL": "ZAVA_SUPPLIER_MCP_URL",
    "SHIPPING-MCP-URL": "ZAVA_SHIPPING_MCP_URL",
    "PRICING-MCP-URL": "ZAVA_PRICING_MCP_URL",
}

_ENVIRONMENT_SETTINGS = {
    "ZAVA_INVENTORY_MCP_URL": "inventory_mcp_url",
    "ZAVA_SUPPLIER_MCP_URL": "supplier_mcp_url",
    "ZAVA_SHIPPING_MCP_URL": "shipping_mcp_url",
    "ZAVA_PRICING_MCP_URL": "pricing_mcp_url",
}


async def hydrate_key_vault_secrets(kv_url: str | None) -> dict[str, str]:
    """Hydrate configured secrets from Key Vault, returning hydrated environment values."""

    if not kv_url:
        return {}

    from azure.core.exceptions import ResourceNotFoundError  # noqa: PLC0415
    from azure.identity import DefaultAzureCredential  # noqa: PLC0415
    from azure.keyvault.secrets import SecretClient  # noqa: PLC0415

    def read_secrets() -> dict[str, str]:
        credential = DefaultAzureCredential()
        client = SecretClient(vault_url=kv_url, credential=credential)
        hydrated: dict[str, str] = {}
        try:
            for secret_name, environment_name in _SECRET_ENVIRONMENT_NAMES.items():
                if environment_name == "GITHUB_TOKEN" and os.getenv(environment_name):
                    continue
                try:
                    secret_value = client.get_secret(secret_name).value
                except ResourceNotFoundError:
                    log.warning("keyvault.secret.missing", secret_name=secret_name)
                    continue
                if not secret_value:
                    raise ValueError(f"Key Vault secret {secret_name} has no value.")
                os.environ[environment_name] = secret_value
                hydrated[environment_name] = secret_value
        except Exception:
            log.exception("keyvault.hydration.failed")
            raise
        finally:
            client.close()
            credential.close()
        return hydrated

    return await asyncio.to_thread(read_secrets)
