"""Optional Azure Key Vault secret hydration for service startup."""

from __future__ import annotations

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


async def hydrate_from_keyvault() -> None:
    """Hydrate unset environment variables from Key Vault when ZAVA_KV_URL is configured."""

    vault_url = os.environ.get("ZAVA_KV_URL")
    if not vault_url:
        return

    from azure.core.exceptions import ResourceNotFoundError  # noqa: PLC0415
    from azure.identity.aio import DefaultAzureCredential  # noqa: PLC0415
    from azure.keyvault.secrets.aio import SecretClient  # noqa: PLC0415

    credential = DefaultAzureCredential()
    async with credential:
        async with SecretClient(vault_url=vault_url, credential=credential) as client:
            for secret_name, environment_name in _SECRET_ENVIRONMENT_NAMES.items():
                if environment_name in os.environ:
                    continue
                try:
                    secret_value = (await client.get_secret(secret_name)).value
                except ResourceNotFoundError:
                    log.warning("keyvault.secret.missing", secret_name=secret_name)
                    continue
                if not secret_value:
                    raise ValueError(f"Key Vault secret {secret_name} has no value.")
                os.environ[environment_name] = secret_value
