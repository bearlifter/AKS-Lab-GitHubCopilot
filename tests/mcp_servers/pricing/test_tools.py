"""Direct tests for pricing MCP tools and request validation."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.mcp_servers.pricing.models import PriceRecommendation, PricingQuery
from src.mcp_servers.pricing.server import recommend_price


@pytest.mark.asyncio
async def test_recommend_price_returns_typed_price_recommendation() -> None:
    result = await recommend_price(
        PricingQuery(
            sku="ZS-1042",
            store_id="store-101",
            demand_signal="demand spike",
            stock_risk_level="critical",
        )
    )

    assert isinstance(result, PriceRecommendation)
    assert result.sku == "ZS-1042"
    assert result.store_id == "store-101"
    assert result.current_price > 0
    assert result.recommended_price > 0
    assert "ZS-1042" in result.rationale


def test_pricing_query_rejects_empty_sku_before_tool_call() -> None:
    with pytest.raises(ValidationError):
        PricingQuery(sku="", store_id="store-101", demand_signal="stable", stock_risk_level="low")
