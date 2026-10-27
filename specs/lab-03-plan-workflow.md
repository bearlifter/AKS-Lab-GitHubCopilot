# Add a deterministic `/plan` workflow to the orchestrator

## Goal
Implement `/plan` as a deterministic Microsoft Agent Framework workflow that coordinates the existing inventory, pricing, supplier, and logistics specialists over A2A. Preserve the deployed `Goal`, `Plan`, and `PlanRefusal` contracts, including regional-request refusal before any A2A call. Optionally hydrate the Copilot token and specialist MCP URL environment values from Azure Key Vault when `ZAVA_KV_URL` is configured, without disturbing the AKS Key Vault CSI token mount.

```text
Goal -> [store_id check -> PlanRefusal] -> (inventory || pricing) -> supplier -> logistics -> reconcile -> Plan
```

For requests with a `store_id`, the bracketed refusal branch is skipped and workflow execution begins with the parallel inventory and pricing stages. Requests without a `store_id` return `PlanRefusal` before any workflow stage or A2A call.

## Non-goals
- Change the public `/plan` request or `Plan` response fields.
- Replace A2A communication with direct specialist imports, direct MCP access, or model-generated orchestration.
- Change specialist or MCP server contracts or implementations.
- Make Key Vault required in local or AKS configurations where `ZAVA_KV_URL` is unset.
- Replace, remount, or overwrite the AKS Key Vault CSI-projected `GITHUB_TOKEN`.
- Add regional or multi-store planning; requests without a single `store_id` remain refused.
- Add new top-level dependencies without justifying them in the implementation handoff.

## Personas
- **Store manager:** receives a coordinated recovery plan for a specific store and SKU.
- **Supply planner:** sees inventory risk, supplier replenishment, shipping, and pricing views reconciled into one plan.
- **Platform operator:** can run the orchestrator with existing AKS A2A settings and optionally configure Key Vault hydration without changing deployed setting names.

## Affected agents
- [x] `orchestrator` — owns `/plan`, the deterministic MAF workflow, and optional startup secret hydration; calls specialists through their existing A2A HTTP endpoints.
- [ ] `inventory` — its existing A2A endpoint is called for the stock stage; no agent implementation or contract changes.
- [ ] `supplier` — its existing A2A endpoint is called after stock and price complete; no agent implementation or contract changes.
- [ ] `logistics` — its existing A2A endpoint is called after the purchase-order stage; no agent implementation or contract changes.
- [ ] `pricing` — its existing A2A endpoint is called in parallel with inventory; no agent implementation or contract changes.
- MCP servers touched: none. MCP URL values may be hydrated into the orchestrator process environment, but all specialist external I/O remains behind the existing specialist-to-MCP boundary.

## New / changed contracts

The public JSON contracts remain unchanged. `store_id` stays optional on input so that a regional request reaches the existing refusal behavior rather than failing request validation. Successful plans keep the same top-level fields and refusal responses remain typed.

```python
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class Goal(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    goal: str = Field(min_length=1)
    sku: str = Field(min_length=1)
    store_id: str | None = Field(default=None)


class Plan(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    sku: str
    store_id: str
    stock_view: str
    price_view: str
    po_view: str
    shipping_view: str
    summary: str
    next_actions: list[str]


class PlanRefusal(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    status: Literal["refused"] = "refused"
    reason: str = Field(min_length=1)
```

Configuration compatibility requirements:
- Keep `ZAVA_INVENTORY_A2A_URL`, `ZAVA_SUPPLIER_A2A_URL`, `ZAVA_LOGISTICS_A2A_URL`, and `ZAVA_PRICING_A2A_URL` as the specialist endpoint setting names, and keep `ZAVA_KV_URL` as the optional Key Vault setting name.
- When Key Vault hydration is enabled, use these exact Key Vault secret-to-environment mappings: `GITHUB-TOKEN` → `GITHUB_TOKEN`, `INVENTORY-MCP-URL` → `ZAVA_INVENTORY_MCP_URL`, `SUPPLIER-MCP-URL` → `ZAVA_SUPPLIER_MCP_URL`, `SHIPPING-MCP-URL` → `ZAVA_SHIPPING_MCP_URL`, and `PRICING-MCP-URL` → `ZAVA_PRICING_MCP_URL`. Only `GITHUB-TOKEN` currently exists in the vault; each missing secret is skipped and logged by secret name only, without logging its value, and is not fatal.
- Preserve an already-provided `GITHUB_TOKEN`, including the value exported from the AKS CSI mount. Hydration must not change the CSI volume, mount path, or deployment entrypoint.

## Acceptance criteria
1. `Goal.store_id` remains optional. A request with a valid `goal` and `sku` but no `store_id` is accepted by request validation and returns a `PlanRefusal` with `status="refused"` and a non-empty reason explaining that a single store is required.
2. The regional-request check runs before constructing or executing the MAF workflow. An integration test verifies zero calls to inventory, pricing, supplier, and logistics A2A endpoints for an omitted-`store_id` request.
3. For a valid single-store request, `/plan` executes a deterministic MAF Workflow and does not ask a language model to select stages, order calls, or synthesize the plan.
4. The workflow invokes inventory and pricing concurrently through their existing A2A URLs. A workflow integration test verifies both start before either completes, and verifies that supplier is not invoked until both parallel stages have completed.
5. The workflow invokes supplier through its existing A2A URL after the inventory and pricing stage, then invokes logistics through its existing A2A URL only after the supplier result is available. Tests assert this dependency order and that each stage is invoked once per request. Remove the existing `call_specialists` all-at-once fan-out helper from `a2a.py` and replace it with the workflow's ordered stage invocations; retain `SpecialistClient`, the `SpecialistInvoker` protocol, and the shared per-agent A2A HTTP invocation behavior.
6. The workflow reconciles successful stage outputs into a top-level `Plan` with the unchanged `sku`, `store_id`, `stock_view`, `price_view`, `po_view`, `shipping_view`, `summary`, and `next_actions` fields. The response is JSON validated as `Plan`, not wrapped in an agent output envelope.
7. Plan reconciliation is deterministic: given the same input and the same specialist outputs, repeated workflow executions produce equal `Plan` values, including `summary` and `next_actions`.
8. A failed A2A stage is surfaced as an explicit request failure using the repository's standard error handling; it does not yield a successful-looking partial `Plan` or silently fabricated specialist output.
9. With `ZAVA_KV_URL` unset, startup performs no Key Vault credential or network operation and leaves existing environment values unchanged. The local and AKS deployments remain usable with their current configuration.
10. With `ZAVA_KV_URL` set, async startup hydration reads the configured secrets using the repository's Azure identity pattern and exact mappings above. A secret not found in the vault is skipped, logged by its secret name only, and does not fail startup; other Key Vault/authentication errors are surfaced explicitly without logging secret values. An already-present CSI-provided `GITHUB_TOKEN` is preserved, and tests verify that no filesystem mount or CSI configuration is replaced.
11. The existing A2A setting names and `ZAVA_KV_URL` setting name remain supported. No specialist is imported directly, no A2A URL is renamed, and MCP calls remain owned by the specialist agents.
12. The eval dataset retains all four current Lab 02 scenarios unchanged and adds at least two workflow-specific scenarios. The eval suite passes all six or more cases; workflow order, no-model orchestration, deterministic replay, and regional zero-call behavior are additionally enforced by integration/unit tests because `must_call` and `forbid_call` are review metadata, not eval pass gates.
13. `uv run poe check` passes, and live `/plan` smoke plus the full eval suite pass before deployment handoff.

## Eval scenarios

Retain these four existing scenarios unchanged:

```jsonl
{"id":"stockout-zs1042-store101","goal":"Store 101 will stock out of SKU ZS-1042 by Friday. Build a recovery plan for store-101.","sku":"ZS-1042","store_id":"store-101","must_mention":["ZS-1042","store-101","stock","purchase","shipping","price"],"must_call":["inventory","supplier","logistics","pricing"],"forbid_call":[],"max_latency_s":180}
{"id":"stockout-transfer-and-po","goal":"For SKU ZS-1042 at store-101, compare nearby stock with supplier replenishment and produce the best action plan.","sku":"ZS-1042","store_id":"store-101","must_mention":["store-202","wh-east","supplier","ETA","next_actions"],"must_call":["inventory","supplier","logistics"],"forbid_call":[],"max_latency_s":180}
{"id":"stockout-price-protection","goal":"SKU ZS-1042 at store-101 has high demand and critical stock risk. Recommend a recovery plan with price protection.","sku":"ZS-1042","store_id":"store-101","must_mention":["42.79","critical","Fabrikam RapidShip","sup-northstar"],"must_call":["inventory","supplier","logistics","pricing"],"forbid_call":[],"max_latency_s":180}
{"id":"stockout-no-regional-plan","goal":"The Northeast region may stock out of SKU ZS-1042. Build a regional recovery plan.","sku":"ZS-1042","must_mention":["single store","store_id","refuse"],"must_call":[],"forbid_call":["supplier","logistics","pricing"],"max_latency_s":60,"expected_status":"refused"}
```

Add at least these two workflow eval scenarios:

```jsonl
{"id":"workflow-reconcile-parallel-stock-and-price","goal":"Build a deterministic recovery plan for SKU ZS-1042 at store-101, considering stock risk and price protection.","sku":"ZS-1042","store_id":"store-101","must_mention":["stock_view","price_view","po_view","shipping_view","summary","next_actions"],"must_call":["inventory","pricing","supplier","logistics"],"forbid_call":[],"max_latency_s":240}
{"id":"workflow-reconcile-po-before-shipping","goal":"For SKU ZS-1042 at store-101, include the supplier purchase-order recommendation and the shipment recommendation to that store.","sku":"ZS-1042","store_id":"store-101","must_mention":["store-101","po_view","shipping_view","supplier","ETA"],"must_call":["inventory","pricing","supplier","logistics"],"forbid_call":[],"max_latency_s":240}
```

The JSONL `must_call` entries document the intended A2A participants for review; tests, not those fields, enforce parallelism and ordering.

## Out of scope for this iteration
- Changing any specialist's A2A endpoint or MCP integration.
- Adding new workflow stages, agents, MCP servers, or business capabilities.
- Replacing Workload Identity / `DefaultAzureCredential` with client secrets or checked-in credentials.
- Updating AKS CSI configuration or replacing its `GITHUB-TOKEN` mount.
- Changes to deployment infrastructure, image tags, or cloud resources; hand off deployment separately after implementation and validation.

## Handoff
Hand off to `orchestrator-architect` with:

```text
Implement specs/lab-03-plan-workflow.md. Keep Goal.store_id optional and preserve the existing Plan and PlanRefusal contracts. Add the deterministic MAF /plan workflow with inventory and pricing in parallel, then supplier, then logistics, and deterministic Plan reconciliation; retain all ZAVA_*_A2A_URL and ZAVA_KV_URL names. Remove the `call_specialists` all-at-once fan-out helper and replace it with ordered workflow stage calls while keeping the shared A2A client. Make Key Vault hydration optional and non-destructive to the AKS CSI-provided GITHUB_TOKEN; use the exact secret mappings in the spec and skip/log missing secrets by name without failing startup. Preserve all four existing eval scenarios and add the two workflow scenarios from the spec; ensure workflow ordering, deterministic replay, and zero-A2A regional refusal are enforced by tests.
```
