"""Direct tests for shipping MCP tools and request validation."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.mcp_servers.shipping.models import ShipmentQuote, ShipmentQuoteRequest
from src.mcp_servers.shipping.server import quote_shipment


@pytest.mark.asyncio
async def test_quote_shipment_returns_typed_shipment_quote() -> None:
    result = await quote_shipment(
        ShipmentQuoteRequest(po_id="PO-ZS1042-STORE101", destination_store_id="store-101", quantity=80)
    )

    assert isinstance(result, ShipmentQuote)
    assert result.po_id == "PO-ZS1042-STORE101"
    assert result.destination_store_id == "store-101"
    assert result.carrier
    assert result.eta_days >= 0
    assert result.cost > 0
    assert "PO-ZS1042-STORE101" in result.recommendation


def test_shipment_request_rejects_empty_po_id_before_tool_call() -> None:
    with pytest.raises(ValidationError):
        ShipmentQuoteRequest(po_id="", destination_store_id="store-101", quantity=80)
