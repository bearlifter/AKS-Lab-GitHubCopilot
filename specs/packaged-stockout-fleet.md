# Packaged ZavaShop Stock-Out Response Fleet

## Goal

Build a runnable ZavaShop fleet of five Microsoft Agent Framework agents and four MCP servers for one stock-out workflow identified by a SKU and store. Make the orchestrator's `POST /plan` accept the goal, SKU, and store ID and return a structured `Plan` with `stock_view`, `price_view`, `po_view`, `shipping_view`, and `summary` as top-level fields. Package and test the fleet locally, and prepare AKS/ACA deployment handoff artifacts without deploying cloud resources.

## Non-goals

- Do not add Azure OpenAI or any model provider other than the GitHub Copilot SDK with `model="gpt-5.5"`.
- Do not store secrets in checked-in files, Docker images, Helm values, or plaintext environment variables for cloud deployment.
- Do not replace the in-memory MCP data stores with Cosmos DB in this iteration.
- Do not build multi-store, regional, or replenishment-forecast workflows beyond one `(sku, store_id)` stock-out goal.
- Do not deploy cloud resources directly during domain implementation; deployment remains owned by `deploy-engineer` and `/ship-it`.

## Personas

- Store manager: needs a clear recommendation when a store is at risk of stocking out.
- Supply planner: needs supplier and purchase-order options tied to current stock.
- Logistics coordinator: needs transfer or shipment guidance for the chosen purchase-order path.
- Pricing analyst: needs price guidance that accounts for demand pressure during the stock-out window.
- Platform engineer: needs the fleet packaged consistently for local Docker Compose, AKS orchestrator deployment, and ACA specialist/MCP deployment.

## Affected agents

- [x] `orchestrator` — owns the `/plan` workflow, A2A fan-out, final `Plan`, local compose wiring, and AKS-facing service.
- [x] `inventory` — serves its specialist A2A `/invoke` endpoint, interprets stock risk using the inventory MCP server, and returns its result to the orchestrator over A2A.
- [x] `supplier` — serves its specialist A2A `/invoke` endpoint, gets supplier availability and purchase-order drafts from the supplier MCP server, and returns its result to the orchestrator over A2A.
- [x] `logistics` — serves its specialist A2A `/invoke` endpoint, gets shipment quotes and transfer guidance from the shipping MCP server, and returns its result to the orchestrator over A2A.
- [x] `pricing` — serves its specialist A2A `/invoke` endpoint, gets price recommendations from the pricing MCP server, and returns its result to the orchestrator over A2A.
- [x] MCP server `inventory` — exposes `check_stock(StockQuery) -> StockReport`.
- [x] MCP server `supplier` — exposes `list_suppliers(SupplierQuery) -> SupplierList` and `draft_po(PurchaseOrderRequest) -> PurchaseOrderDraft`.
- [x] MCP server `shipping` — exposes `quote_shipment(ShipmentQuoteRequest) -> ShipmentQuote`.
- [x] MCP server `pricing` — exposes `recommend_price(PricingQuery) -> PriceRecommendation`.
- [x] Deployment packaging — base image, one service image per agent/MCP, Docker Compose, ACA Bicep handoff, AKS Helm handoff, and `/ship-it` compatibility.
- [x] Tests — unit, MCP, integration, and eval coverage for every acceptance criterion.

## New / changed contracts

```python
from pydantic import BaseModel, ConfigDict, Field


class Goal(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    goal: str = Field(min_length=1, max_length=4000)
    sku: str = Field(min_length=1, max_length=128)
    store_id: str = Field(min_length=1, max_length=128)
```

```python
from pydantic import BaseModel, ConfigDict, Field


class StockQuery(BaseModel):
    model_config = ConfigDict(frozen=True)

    sku: str = Field(min_length=1)
    store_id: str = Field(min_length=1)


class StockLocation(BaseModel):
    model_config = ConfigDict(frozen=True)

    location_id: str
    on_hand: int = Field(ge=0)
    reserved: int = Field(ge=0)
    reorder_point: int = Field(ge=0)
    days_until_stockout: int = Field(ge=0)


class StockReport(BaseModel):
    model_config = ConfigDict(frozen=True)

    sku: str
    store_id: str
    target: StockLocation
    nearby_locations: list[StockLocation]
    risk_level: str
    recommendation: str
```

```python
from pydantic import BaseModel, ConfigDict, Field


class SupplierQuery(BaseModel):
    model_config = ConfigDict(frozen=True)

    sku: str = Field(min_length=1)


class SupplierOption(BaseModel):
    model_config = ConfigDict(frozen=True)

    supplier_id: str
    name: str
    available_qty: int = Field(ge=0)
    unit_cost: float = Field(gt=0)
    lead_time_days: int = Field(ge=0)
    reliability_score: float = Field(ge=0, le=1)


class SupplierList(BaseModel):
    model_config = ConfigDict(frozen=True)

    sku: str
    suppliers: list[SupplierOption]


class PurchaseOrderRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    sku: str = Field(min_length=1)
    store_id: str = Field(min_length=1)
    supplier_id: str = Field(min_length=1)
    quantity: int = Field(gt=0)


class PurchaseOrderDraft(BaseModel):
    model_config = ConfigDict(frozen=True)

    po_id: str
    sku: str
    store_id: str
    supplier_id: str
    quantity: int = Field(gt=0)
    estimated_total: float = Field(gt=0)
    eta_days: int = Field(ge=0)
    status: str
```

```python
from pydantic import BaseModel, ConfigDict, Field


class ShipmentQuoteRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    po_id: str = Field(min_length=1)
    destination_store_id: str = Field(min_length=1)
    quantity: int = Field(gt=0)


class ShipmentQuote(BaseModel):
    model_config = ConfigDict(frozen=True)

    po_id: str
    destination_store_id: str
    carrier: str
    service_level: str
    eta_days: int = Field(ge=0)
    cost: float = Field(gt=0)
    recommendation: str
```

```python
from pydantic import BaseModel, ConfigDict, Field


class PricingQuery(BaseModel):
    model_config = ConfigDict(frozen=True)

    sku: str = Field(min_length=1)
    store_id: str = Field(min_length=1)
    demand_signal: str = Field(min_length=1)
    stock_risk_level: str = Field(min_length=1)


class PriceRecommendation(BaseModel):
    model_config = ConfigDict(frozen=True)

    sku: str
    store_id: str
    current_price: float = Field(gt=0)
    recommended_price: float = Field(gt=0)
    margin_impact: str
    rationale: str
```

```python
from pydantic import BaseModel, ConfigDict, Field


class Plan(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    sku: str = Field(min_length=1)
    store_id: str = Field(min_length=1)
    stock_view: str = Field(min_length=1)
    price_view: str = Field(min_length=1)
    po_view: str = Field(min_length=1)
    shipping_view: str = Field(min_length=1)
    summary: str = Field(min_length=1)
    next_actions: list[str] = Field(min_length=1)
```

```python
from pydantic import BaseModel, ConfigDict, Field


class ServiceImage(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    repository: str
    tag: str = Field(pattern=r"^[0-9a-f]{7,40}$")
    runtime: str
    target: str


class FleetPackage(BaseModel):
    model_config = ConfigDict(frozen=True)

    base_image: ServiceImage
    service_images: list[ServiceImage]
    orchestrator_target: str = "aks"
    specialist_target: str = "aca"
    mcp_target: str = "aca"
```

## Acceptance criteria

1. Given a valid `Goal` containing `goal`, `sku="ZS-1042"`, and `store_id="store-101"`, `POST /plan` returns HTTP 200 with a JSON object validated as `Plan` directly (not nested under an `output` or other wrapper). The response contains non-empty top-level `stock_view`, `price_view`, `po_view`, `shipping_view`, and `summary` fields, plus the identifying `sku`, `store_id`, and at least one `next_actions` item.
2. The inventory MCP server returns a `StockReport` for `ZS-1042` with `store-101`, `store-202`, and `wh-east` represented in the seeded in-memory data.
3. The supplier MCP server can list suppliers for `ZS-1042` and draft a purchase order with a stable `po_id`, quantity, supplier, ETA, and estimated total.
4. The shipping MCP server can quote shipment for the drafted purchase order and destination store using a typed `ShipmentQuote`.
5. The pricing MCP server can recommend a price for `ZS-1042` at `store-101` using demand signal and stock risk level.
6. All five agents use `GitHubCopilotAgent` from `agent_framework.github`, created with `client=build_copilot_client()` and `GitHubCopilotOptions(model="gpt-5.5", timeout=settings.copilot_timeout_seconds, on_permission_request=_approve_all, mcp_servers={...})`; each agent has a role-scoped system prompt and refuses out-of-scope requests.
7. The orchestrator communicates with specialists only through A2A HTTP calls and does not import specialist Python modules.
8. External I/O lives in MCP servers; agent `tools.py` files do not contain database, supplier API, shipping API, or pricing-engine side effects.
9. Docker packaging builds one Python base image and nine service images (five agents and four MCP servers), all tagged with the current git SHA; no manifest or deployment helper references `:latest`.
10. Docker Compose starts the orchestrator, four specialists, and four MCP servers as one local fleet, with health checks and the required service endpoints; `docker compose up -d --build` completes successfully.
11. Deployment handoff artifacts specify the AKS Helm target for the orchestrator and ACA deployment target for all four specialists and all four MCP servers, with internal service communication and configured MCP/A2A endpoints.
12. Unit, MCP, A2A integration, and eval tests cover the acceptance criteria. `uv run poe check` passes, and `ZAVA_ENDPOINT=http://localhost:8000 uv run python -m tests.evals.run_evals` reports no failures before the final `/ship-it` handoff.
13. Cloud deployment is left to `/ship-it` and gated by the Lab 05 landing-zone checks: Entra ID, Azure RBAC, Workload Identity, Azure Policy, Container Insights, Defender for Cloud, Key Vault CSI, and git-SHA image tags.

## Eval scenarios

```jsonl
{"id":"stockout-zs1042-store101-structured-plan","goal":"Store 101 will stock out of SKU ZS-1042 by Friday. Build a recovery plan for this SKU and store.","sku":"ZS-1042","store_id":"store-101","must_mention":["ZS-1042","store-101","stock_view","price_view","po_view","shipping_view","summary"],"must_call":["inventory","supplier","logistics","pricing"],"forbid_call":[],"max_latency_s":180}
{"id":"stockout-transfer-and-po","goal":"For SKU ZS-1042 at store-101, compare nearby stock with supplier replenishment and produce the best action plan.","sku":"ZS-1042","store_id":"store-101","must_mention":["store-202","wh-east","supplier","ETA","next_actions"],"must_call":["inventory","supplier","logistics"],"forbid_call":[],"max_latency_s":180}
```

## Out of scope for this iteration

- Cosmos DB persistence for MCP data stores.
- Private AKS cluster, private ACA environment, or Application Gateway for Containers ingress.
- Multi-region active-active deployment.
- Human approval workflow for purchase-order submission.
- Real supplier, carrier, ERP, or pricing-engine integration.
- GitHub App token broker replacement for the lab PAT.
- Production alert rules, dashboards, or runbooks beyond the deployment handoff requirements.

## Handoff

Hand off to `mcp-builder` with:

```text
Implement specs/packaged-stockout-fleet.md for the four MCP servers only:
src/mcp_servers/inventory, src/mcp_servers/supplier,
src/mcp_servers/shipping, and src/mcp_servers/pricing.
Use the Pydantic contracts from the spec, seed ZS-1042/store-101/store-202/wh-east,
keep stores in memory with TODO comments for Cosmos DB, expose FastMCP streamable-http
servers, and run the MCP-focused checks before reporting. Stop after this MCP phase for
human review; do not proceed to agents, tests, or deployment without the next mode being
explicitly invoked. Once all implementation and verification phases are complete, leave
the fleet ready for the separate `/ship-it` handoff to deploy the orchestrator to AKS and
the specialists and MCP servers to ACA.
```
