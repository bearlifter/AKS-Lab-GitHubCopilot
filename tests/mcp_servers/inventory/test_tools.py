"""Direct tests for inventory MCP tools and request validation."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.mcp_servers.inventory.models import StockQuery, StockReport
from src.mcp_servers.inventory.server import check_stock

EXPECTED_ON_HAND = 6


@pytest.mark.asyncio
async def test_check_stock_returns_typed_stock_report() -> None:
    result = await check_stock(StockQuery(sku="ZS-1042", store_id="store-101"))

    assert isinstance(result, StockReport)
    assert result.sku == "ZS-1042"
    assert result.store_id == "store-101"
    assert result.target.on_hand == EXPECTED_ON_HAND
    assert result.risk_level == "critical"
    assert any(location.location_id == "store-202" for location in result.nearby_locations)


def test_stock_query_rejects_empty_sku_before_tool_call() -> None:
    with pytest.raises(ValidationError):
        StockQuery(sku="", store_id="store-101")
