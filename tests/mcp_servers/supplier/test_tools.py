"""Direct tests for supplier MCP tools and request validation."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.mcp_servers.supplier.models import (
    PurchaseOrderDraft,
    PurchaseOrderRequest,
    SupplierList,
    SupplierQuery,
)
from src.mcp_servers.supplier.server import draft_po, list_suppliers

ORDER_QUANTITY = 80


@pytest.mark.asyncio
async def test_list_suppliers_returns_typed_ranked_supplier_list() -> None:
    result = await list_suppliers(SupplierQuery(sku="ZS-1042"))

    assert isinstance(result, SupplierList)
    assert result.sku == "ZS-1042"
    assert result.suppliers
    assert result.suppliers[0].supplier_id == "sup-northstar"


@pytest.mark.asyncio
async def test_draft_po_returns_typed_purchase_order() -> None:
    result = await draft_po(
        PurchaseOrderRequest(
            sku="ZS-1042",
            store_id="store-101",
            supplier_id="sup-northstar",
            quantity=ORDER_QUANTITY,
        )
    )

    assert isinstance(result, PurchaseOrderDraft)
    assert result.po_id.startswith("PO-")
    assert result.sku == "ZS-1042"
    assert result.store_id == "store-101"
    assert result.quantity == ORDER_QUANTITY
    assert result.estimated_total > 0
    assert result.status == "draft"


def test_supplier_requests_reject_empty_sku_before_tool_call() -> None:
    with pytest.raises(ValidationError):
        SupplierQuery(sku="")
    with pytest.raises(ValidationError):
        PurchaseOrderRequest(sku="", store_id="store-101", supplier_id="sup-northstar", quantity=ORDER_QUANTITY)
