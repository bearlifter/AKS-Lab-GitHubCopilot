---
name: ship-it
description: "Package and roll the current SHA to ACR + ACA + AKS, with quality, landing zone, and smoke gates."
disable-model-invocation: true
---

# Workflow: Ship It

## Inputs

`.env.lab` sourced. `kubectl` and `az` already authenticated.

## Steps (you run these via `runCommands`, do not just print them)

1. Refuse if `git status --porcelain` is non-empty.
2. `uv run poe check`. Refuse if red.
3. Compute `GIT_SHA=$(git rev-parse --short HEAD)` and the changed-services list:
   ```bash
   git diff --name-only origin/main... | awk -F/ '/^src\/(agents|mcp_servers)\//{print $3}' | sort -u
   ```
   Add to that list any service the user explicitly names in the invocation, and any
   ACA app whose latest revision is unhealthy, crash-looping, or failing `/healthz`.
4. If this is a first deployment or the changed-services list is empty but no live revisions exist, package the whole app: base image + all 9 services.
5. Before changing live workloads, verify the Lab 01 landing zone baseline:
   - AKS `aadProfile.managed` is `true` (Microsoft Entra ID) and `aadProfile.enableAzureRbac`
     is `true` (Azure RBAC). JMESPath is case-sensitive: use `enableAzureRbac`.
   - AKS Azure Policy add-on is enabled.
   - AKS Defender security monitoring is enabled.
   - Defender for Cloud `Containers` and `KeyVaults` pricing tiers are `Standard`.
   - Do not use `az aks get-credentials --admin`.

   **Documented exception: Defender (course low-cost edition).** If
   `docs/decisions/0001-defender-waiver.md` exists and cites the instructor guidance in
   `docs/instructor/lab01-low-cost-edition.md`, treat the Defender checks as WAIVED, not
   failed: AKS `securityProfile.defender`, Defender for Cloud pricing tiers (Containers,
   KeyVaults), and `Microsoft.Security` provider registration. Report them as
   "waived (ADR 0001)". Entra ID, Azure RBAC, and Azure Policy remain mandatory.

6. For each changed service, build and push `$ACR.azurecr.io/zavashop/<svc>:$GIT_SHA`.
7. For each changed specialist or MCP → `az containerapp update --image …`.
8. If `src/agents/orchestrator/` changed, or no `zavashop` Helm release / orchestrator
   deployment exists on AKS yet → `helm upgrade --install zavashop infra/aks/helm/zavashop --set image.tag=$GIT_SHA …` and `kubectl rollout status`.
9. Smoke + evals against the public orchestrator IP.
10. Report SHA, services updated, landing zone gate results, revisions, eval result.

## Refuse to

- Push if `:latest` appears in any built tag.
- Update a workload whose image does not exist in ACR.
- Continue if Entra ID, Azure RBAC, or Azure Policy checks fail, unless the user explicitly says the subscription is governed by equivalent central policy and provides the evidence.
- Continue if Defender checks fail, unless the documented exception in step 5 applies or the user provides equivalent evidence.
- Continue past a failed smoke test — instead, switch to `deploy-engineer` mode for triage.
