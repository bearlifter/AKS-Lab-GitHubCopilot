# Extend the ZavaShop test suite and CI quality gates

## Goal
Extend the Lab 02–03 test suite without replacing its existing tests or six golden eval scenarios. Add only the missing per-agent cases, direct MCP tool tests, and ASGI loopback coverage for `/invoke`, then define an auditable Poe task graph and CI workflow. Keep unit and integration tests fully offline with fakes; make quota-consuming live evals opt-in in CI.

## Non-goals
- Rewrite, remove, or rename the existing agent, orchestrator, Key Vault, and six eval tests/scenarios.
- Call GitHub Copilot or any remote model from unit or integration tests.
- Run live Copilot evals on every push or pull request.
- Change agent, MCP, A2A, `/plan`, or `/invoke` production contracts.
- Change deployment workflow behavior in `.github/workflows/deploy.yml`.
- Add unrelated production dependencies or change application behavior to make tests pass.

## Personas
- **ZavaShop platform engineer:** gets fast, deterministic coverage for contracts, server routes, and configuration.
- **Agent maintainer:** sees prompt behavior and error handling regressions before merge without spending model quota.
- **Supply planner and store manager:** benefit from retained golden scenarios for stock-out, transfer, price, and regional-refusal behavior plus broader Lab 04 business cases.
- **Repository maintainer:** gets repeatable quality, security-audit, and opt-in live-eval jobs in GitHub Actions.

## Affected agents
- [x] `orchestrator` — extend unit tests for refusal/tool-error and add `/invoke` ASGI coverage; preserve current `/plan` refusal, ordering, replay, and failure tests.
- [x] `inventory` — retain its existing happy/refusal/tool-error coverage; add only any assertion needed by shared `/invoke` integration.
- [x] `supplier` — retain current happy/refusal coverage and add the missing tool-error unit case.
- [x] `logistics` — retain current happy/refusal coverage and add the missing tool-error unit case.
- [x] `pricing` — retain current happy/refusal coverage and add the missing tool-error unit case.
- MCP servers touched by tests: [x] `inventory` (`check_stock`), [x] `supplier` (`list_suppliers`, `draft_po`), [x] `shipping` (`quote_shipment`), [x] `pricing` (`recommend_price`).
- Test infrastructure: `tests/**`, `pyproject.toml` Poe tasks, and a new `.github/workflows/ci.yml`. CI workflow implementation is owned by `deploy-engineer` after the test-author phase.

Verified unit-test baseline — preserve existing tests and add only missing cases:

| Agent | Happy | Refusal | Tool error | Required action |
|---|---|---|---|---|
| inventory | Present | Present | Present | Keep all three existing tests. |
| supplier | Present | Present | Missing | Add one tool-error test. |
| logistics | Present | Present | Missing | Add one tool-error test. |
| pricing | Present | Present | Missing | Add one tool-error test. |
| orchestrator | Present | Missing at agent-unit layer | Missing at agent-unit layer | Add agent-unit refusal and tool-error tests. Keep existing `/plan` regional-refusal integration test; it does not replace the per-agent unit refusal case. |

## New / changed contracts

The eval JSONL schema remains the schema already parsed by `tests/evals/run_evals.py`. Each non-empty line is one independent JSON object. `store_id` is optional and may be omitted for scenarios that expect regional refusal. `expected_status` is optional and accepts only `"plan"` or `"refused"`; omission means `"plan"`.

```python
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class EvalScenario(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str = Field(min_length=1)
    goal: str = Field(min_length=1)
    sku: str = Field(min_length=1)
    store_id: str | None = Field(default=None, min_length=1)
    must_mention: list[str] = Field(default_factory=list)
    must_call: list[str] = Field(default_factory=list)
    forbid_call: list[str] = Field(default_factory=list)
    max_latency_s: float = Field(default=180, gt=0)
    expected_status: Literal["plan", "refused"] = "plan"
```

Field semantics and current runner behavior:
- Required: `id`, `goal`, `sku`; `store_id` may be absent or null.
- Optional with defaults: `must_mention`, `must_call`, `forbid_call`, `max_latency_s`, and `expected_status`.
- `must_mention` terms are checked against the flattened response; `expected_status` and the latency budget are pass-gate inputs.
- `must_call` and `forbid_call` are review metadata only: they are recorded in output notes, not verified by the eval pass gate. Enforce actual call/no-call expectations in tests.

Example JSONL row, with the optional store omitted for a refusal scenario:

```json
{"id":"regional-refusal","goal":"The Northeast region may stock out of SKU ZS-1042.","sku":"ZS-1042","must_mention":["single store","refuse"],"must_call":[],"forbid_call":["inventory","supplier","logistics","pricing"],"max_latency_s":60,"expected_status":"refused"}
```

## Acceptance criteria
1. Keep all existing tests under `tests/agents/`, `tests/shared/`, and `tests/agents/orchestrator/test_server.py`. In particular, preserve the current `/plan` refusal, zero-call, workflow ordering, deterministic replay, failure, and Key Vault hydration tests; additions must be additive.
2. Agent unit tests continue to use `MockChatClient` patched at each agent module's import site. No unit test makes a real Copilot/model or network call, uses `time.sleep`, or relies on exact natural-language generation. Inventory retains its current happy, refusal, and tool-error coverage.
3. Add exactly the missing tool-error unit case for supplier, logistics, and pricing agents. Each case proves the mocked model/tool exception propagates or is handled according to the existing agent contract; do not duplicate their existing happy or refusal tests.
4. Add orchestrator agent-unit tests for a refused response and a model/tool error using `MockChatClient`. Keep the separate existing `/plan` regional-refusal integration test because the orchestration agent's unit-level refusal and the endpoint's typed refusal are distinct behaviors.
5. Add `tests/mcp_servers/{inventory,supplier,shipping,pricing}/test_tools.py`. Directly invoke every registered tool function with its Pydantic request model and assert the corresponding typed result for a representative valid ZavaShop fixture. Required tool coverage is `check_stock`, `list_suppliers`, `draft_po`, `quote_shipment`, and `recommend_price`.
6. For tools whose request model contains `sku` (`check_stock`, `list_suppliers`, `draft_po`, and `recommend_price`), add a validation-error case using an empty SKU and assert Pydantic validation fails before business logic executes. The existing `quote_shipment` request has no SKU field; cover its validation error with an empty required `po_id` instead. Use in-memory fixtures/fakes; MCP tests must not start a network listener or access external systems.
7. Preserve and extend loopback integration coverage using FastAPI `ASGITransport` and fake Copilot/A2A clients only. Keep the existing successful and regional-refusal `/plan` cases and add a successful orchestrator `POST /invoke` case that validates the `InvokeResponse` envelope and returned run ID/output. Exercise the `/invoke` endpoint of each agent through its ASGI app with the Copilot SDK patched; no test in this layer contacts a real model or service.
8. Integration tests explicitly enter each app's lifespan where needed so startup initialization and readiness behavior are tested; the ASGI transport remains in-process and does not bind ports.
9. Keep the existing six rows in `tests/evals/scenarios.jsonl` unchanged and append at least five distinct Lab 04 scenarios covering: stock-out, demand spike, supplier delay, price war, and seasonal promotion. The resulting golden set therefore has at least eleven rows, unique non-empty `id` values, and valid JSON on every nonblank line.
10. Every eval row conforms to the schema in this spec. At least one row omits `store_id` and sets `expected_status` to `"refused"`; ordinary single-store plan scenarios set `store_id` and default to or explicitly use `expected_status: "plan"`. Use realistic multi-agent latency budgets, no lower than 60 seconds.
11. Define a Poe task graph with `check`, `audit`, and `evals`. `check` runs Ruff lint, Ruff format check, strict Pyright, and the complete offline pytest suite with `pytest-cov` enforcing at least 80% coverage for `src/agents/`; it must not invoke a live model or consume Copilot quota. `audit` runs Bandit against `src/` and `pip-audit` against the locked environment. `evals` runs `tests.evals.run_evals` against `ZAVA_ENDPOINT` and is a live/quota-consuming task, separate from `check`. Add `pytest-cov`, `bandit`, and `pip-audit` as development-only dependencies where needed.
12. Add `.github/workflows/ci.yml` for `push` and `pull_request`. Its normal `check` job sets up Python and uv, caches using `uv.lock`, runs `uv sync --frozen`, `uv run poe check`, and `uv run poe audit`, and requires no Copilot secret.
13. The CI `evals` job is skipped by default and runs only for a pull request carrying the `run-evals` label. It builds/starts the local Compose fleet, waits for readiness, runs `uv run poe evals`, and always tears the fleet down. Name the required repository secret `COPILOT_GITHUB_TOKEN` and map it to the process `GITHUB_TOKEN` expected by the app; do not use or mistake GitHub Actions' automatically supplied `GITHUB_TOKEN` for the Copilot credential. Do not expose the secret in logs or in the normal check job.
14. Keep all tests and tasks deterministic/offline except the explicitly opted-in live `evals` task. Document that one eval run consumes Copilot quota (approximately 30 requests per run) in the task/CI usage guidance, and fail clearly if the opt-in job lacks `COPILOT_GITHUB_TOKEN`.
15. Remove the stray empty `src/agents/inventory/tests/__init__.py` package directory after confirming no tests are stored there; keep the canonical inventory tests under `tests/agents/inventory/`.
16. `uv run poe check` and `uv run poe audit` pass locally. The opt-in `uv run poe evals` contract is validated against a running local Compose fleet when the user has supplied Copilot credentials; it is not required in ordinary CI.

## Eval scenarios

Keep the current six Lab 02–03 scenarios in `tests/evals/scenarios.jsonl` byte-for-byte unchanged. Append five new unique scenarios for the following coverage areas; preserve the current JSONL field names and scenario schema above:

```jsonl
{"id":"lab04-stockout-recovery","goal":"SKU ZS-1042 is at critical stock risk at store-101. Build a full recovery plan.","sku":"ZS-1042","store_id":"store-101","must_mention":["ZS-1042","store-101","stock","purchase","shipping"],"must_call":["inventory","supplier","logistics","pricing"],"forbid_call":[],"max_latency_s":240,"expected_status":"plan"}
{"id":"lab04-demand-spike","goal":"Demand for SKU ZS-1042 has spiked at store-101. Assess stock risk and coordinate replenishment and price protection.","sku":"ZS-1042","store_id":"store-101","must_mention":["ZS-1042","store-101","stock","price","next_actions"],"must_call":["inventory","supplier","logistics","pricing"],"forbid_call":[],"max_latency_s":240,"expected_status":"plan"}
{"id":"lab04-supplier-delay","goal":"The preferred supplier is delayed for SKU ZS-1042 at store-101. Compare recovery options and recommend next actions.","sku":"ZS-1042","store_id":"store-101","must_mention":["store-101","supplier","ETA","shipping","next_actions"],"must_call":["inventory","supplier","logistics"],"forbid_call":[],"max_latency_s":240,"expected_status":"plan"}
{"id":"lab04-price-war","goal":"A competitor has started a price war on SKU ZS-1042 at store-101 while inventory is critically low. Recommend a recovery plan.","sku":"ZS-1042","store_id":"store-101","must_mention":["ZS-1042","store-101","critical","price","stock"],"must_call":["inventory","pricing","supplier","logistics"],"forbid_call":[],"max_latency_s":240,"expected_status":"plan"}
{"id":"lab04-seasonal-promo","goal":"A seasonal promotion may increase demand for SKU ZS-1042 at store-101. Build a stock-aware plan with replenishment and pricing guidance.","sku":"ZS-1042","store_id":"store-101","must_mention":["ZS-1042","store-101","stock","purchase","price"],"must_call":["inventory","pricing","supplier","logistics"],"forbid_call":[],"max_latency_s":240,"expected_status":"plan"}
```

The `must_call` values are expected-participant review metadata; validate actual routing through the integration tests, not by treating these fields as an eval pass gate.

## Out of scope for this iteration
- Changing specialist prompts, agent runtime code, MCP business logic, or public API contracts.
- Making live evals a required job for every push or pull request.
- Adding production telemetry, dashboarding, or deployment gates unrelated to test quality.
- Removing any of the six existing golden scenarios or replacing existing test files with a new layout.

## Handoff
Hand off first to `test-author` with:

```text
Implement specs/lab-04-tests.md by extending the existing tests only. Preserve every current agent/server/Key Vault test and all six current JSONL eval rows. Add only missing agent unit cases identified in the coverage matrix, direct tests for every MCP tool, ASGI loopback /invoke coverage, five Lab 04 eval rows, and the check/audit/evals Poe task graph. All unit and integration tests must use fakes and never call Copilot. After the test-author phase, hand off the .github/workflows/ci.yml implementation to deploy-engineer; CI evals must require the run-evals PR label and repository secret COPILOT_GITHUB_TOKEN.
```
