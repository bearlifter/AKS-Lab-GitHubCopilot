# Deploy ZavaShop to AKS and Azure Container Apps

## Goal
Package the ZavaShop fleet as SHA-tagged container images and deploy the orchestrator to AKS plus eight specialist/MCP Container Apps. Make `/ship-it` and the GitHub Actions deploy workflow follow the same build, push, rollout, smoke, and evaluation sequence. Preserve the already-deployed environment and its verified 11/11 eval baseline while documenting the exact identity, RBAC, and waiver conditions required before automation is enabled.

## Non-goals
- Recreate or resize the existing Lab 01 landing zone, AKS cluster, ACR, Key Vault, UAMI, or Log Analytics workspace.
- Enable Defender for Cloud billing features waived by ADR 0001.
- Put credential values in `.env.lab`, a repository variable, a workflow file, Helm values, or a committed artifact.
- Use `:latest`, AKS admin credentials, long-lived Azure client secrets, or real Copilot credentials in smoke-test payloads.
- Change agent or MCP application behavior or introduce a second ACA deployment module.
- Enable the disabled deploy workflow before its RBAC preflight succeeds.

## Personas
- **ZavaShop platform operator:** can roll a named service or the full fleet reproducibly without relying on an incomplete Git diff.
- **Supply planner and store manager:** receive a healthy orchestrator backed by the four specialist agents and four MCP services.
- **Cloud administrator:** can provision the minimum GitHub OIDC and runtime permissions without creating an Entra group.
- **Repository maintainer:** gets the same quality, packaging, deployment, smoke, and eval sequence locally and on pushes to `main`.

## Affected agents
- [x] `orchestrator` — deploy the deterministic `/plan` service on AKS; application code remains outside this deployment specification.
- [x] `inventory`, [x] `supplier`, [x] `logistics`, [x] `pricing` — deploy the four specialist services to ACA.
- MCP servers: [x] `inventory-mcp`, [x] `supplier-mcp`, [x] `shipping-mcp`, [x] `pricing-mcp` — deploy the four independent MCP services to ACA.
- Deployment surfaces owned by `deploy-engineer`: `infra/aca/agent.bicep`, `infra/aca/deploy.sh`, `infra/aks/helm/zavashop/`, the `/ship-it` skill, and `.github/workflows/deploy.yml`. Do not modify `src/` as part of this deployment work.

## New / changed contracts

The deployment selector accepts explicit service names so an already-pushed change does not disappear from selection when `git diff origin/main...` is empty. `base` is a build prerequisite/image, not a deployable service. An empty `services` list means “derive changed services”; the operator may explicitly name one or more services, or request the complete fleet.

```python
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


ServiceName = Literal[
    "orchestrator",
    "inventory",
    "supplier",
    "logistics",
    "pricing",
    "inventory-mcp",
    "supplier-mcp",
    "shipping-mcp",
    "pricing-mcp",
]


class ShipItRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    git_sha: str = Field(min_length=7)
    services: list[ServiceName] = Field(default_factory=list)
    all_services: bool = False
```

All service image references have the form `$ACR.azurecr.io/zavashop/<service>:$GIT_SHA`; the base image is `$ACR.azurecr.io/zavashop/base:$GIT_SHA`. Never publish or deploy a mutable tag.

## Acceptance criteria
1. Record the deployed environment as follows: AKS cluster `aks-zavashop` in `northcentralus`, running two `Standard_B2as_v2` nodes within Azure for Students quota; ACR, Key Vault, UAMI, and Log Analytics are in `westus`; ACA environment is `cae-zavashop-workload`, using Workload Profiles/Consumption. Do not use the Express environment because it cannot provide the required Key Vault secret references. Treat the current deployment and 11/11 eval result as the operator-reported baseline, not as a substitute for rollout-time checks.
2. Package one reusable base image plus nine service images (orchestrator, four specialists, and four MCP servers). Use the same Git SHA in every image tag. Build and push the base image before any agent service image that consumes it; otherwise parallel service builds can race and try to pull `zavashop-base` from Docker Hub. Build each MCP image independently from its own `src/mcp_servers/<service>/Dockerfile`; MCP images do not inherit from the base image. A complete deployment publishes ten repositories: `base` and the nine service repositories.
3. Reuse `infra/aca/agent.bicep` for all eight ACA apps: `inventory`, `supplier`, `logistics`, `pricing`, `inventory-mcp`, `supplier-mcp`, `shipping-mcp`, and `pricing-mcp`. Use the shared UAMI, Key Vault secret reference for `GITHUB_TOKEN`, required MCP endpoint environment values, health/readiness probes, and SHA-pinned images. Set `minReplicas: 0` for every app to stay within the Azure for Students Consumption free grant; eight always-on apps would exceed it within days. Keep `maxReplicas: 10` and HTTP concurrency 30. Smoke and eval steps must tolerate scale-to-zero cold starts by using the eval runner's existing warmup request and configured per-request timeouts, and by allowing adequate readiness/health wait windows; do not raise minimum replicas just to hide cold-start latency. Use the `cae-zavashop-workload` environment; do not provision eight divergent Bicep templates.
4. Deploy only the orchestrator to AKS through `infra/aks/helm/zavashop/`. Preserve two replicas, `orchestrator-sa`, Workload Identity pod label/annotation, Key Vault CSI projection of `GITHUB-TOKEN` into `GITHUB_TOKEN`, non-root/read-only security contexts, resource requests/limits, `/healthz` and `/readyz` probes, and zone topology spread. Keep the token out of Helm values and the workflow. Use non-admin `az aks get-credentials`; after obtaining credentials run `kubelogin convert-kubeconfig -l azurecli` before `kubectl` or Helm operations.
5. Assume the Lab 01 baseline is already configured: Entra ID authentication, Azure RBAC for Kubernetes, Azure Policy, Container Insights/Log Analytics, and the Key Vault CSI provider. The AKS API must report Entra ID and Azure RBAC enabled, Azure Policy enabled, and the configured Log Analytics workspace. Do not recreate these resources as part of `/ship-it`.
6. The school tenant does not permit creating an Entra group. The AKS human administrator is a direct `Azure Kubernetes Service RBAC Cluster Admin` role assignment; document this as the existing human operator path. Do not replace it with an Entra group or grant Cluster Admin to the GitHub workflow UAMI.
7. Report Defender for Cloud as **waived (ADR 0001)**, not failed. Follow `docs/decisions/0001-defender-waiver.md` and the exception in `.github/skills/ship-it/SKILL.md`: skip AKS Defender security-monitoring, Defender `Containers`/`KeyVaults` pricing-tier, and `Microsoft.Security` provider-registration gates when that documented waiver applies. Entra ID, Azure RBAC, Azure Policy, and monitoring checks remain mandatory. Never require paid Defender tiers in preflight.
8. Configure GitHub OIDC with federated credential `gha-zavashop-production` on the UAMI and immutable subject `repo:bearlifter@114249644/AKS-Lab-GitHubCopilot@1435400667:environment:production`, audience `api://AzureADTokenExchange`. The deploy workflow uses the `production` environment, `permissions: id-token: write, contents: read`, and `azure/login@v2`; no Azure client secret is used.
9. Before enabling the deploy workflow, assign and verify only the required workflow permissions on the UAMI:
   - `AcrPush` on the ACR, for pushing image layers and manifests.
   - `Container Registry Tasks Contributor` on the ACR, in addition to `AcrPush`, because `az acr build` runs ACR Tasks.
   - A custom `ZavaShop Deployment Operator` role at the resource-group scope for `az deployment group create`. `Deployment Contributor` is not a built-in role, and `Container Apps Contributor` does not grant `Microsoft.Resources/deployments/*`; do not rely on either for resource-group deployments. Define the custom role with exactly these management-plane actions and no data actions or extra permissions:

     ```json
     {
       "Name": "ZavaShop Deployment Operator",
       "IsCustom": true,
       "Description": "Allows ZavaShop ACA resource-group deployments and resource-group read required by the deployment operation.",
       "Actions": [
         "Microsoft.Resources/deployments/*",
         "Microsoft.Resources/subscriptions/resourceGroups/read"
       ],
       "NotActions": [],
       "DataActions": [],
       "NotDataActions": [],
       "AssignableScopes": [
         "/subscriptions/<subscription-id>/resourceGroups/<resource-group-name>"
       ]
     }
     ```

     Replace the scope placeholders with the actual resource-group resource ID, and assign this role at that same resource-group scope.
   - `Container Apps Contributor` scoped to the ACA environment and the eight target Container Apps for ACA deployment/update; do not broaden it to subscription scope.
   - `Azure Kubernetes Service Cluster User Role` on the AKS cluster, required for `az aks get-credentials` without `--admin`.
   - `Azure Kubernetes Service RBAC Reader` at the AKS cluster scope for namespace discovery/read, and `Azure Kubernetes Service RBAC Writer` scoped to namespace `zavashop` for Helm-managed namespaced resources and rollout status. Pre-create `zavashop` with the direct human Cluster Admin assignment; do not give the workflow UAMI cluster-admin or namespace-create rights. The workflow must fail clearly if the namespace is absent.
   - `Managed Identity Operator` scoped to the UAMI resource itself, required to assign that identity to the ACA apps in Bicep; without it deployments fail with `LinkedAuthorizationFailed`.
   - Where the same UAMI is also the ACA runtime identity, separately retain `AcrPull` on ACR and `Key Vault Secrets User` scoped to the required vault/secrets for image pulls and Key Vault secret references. These runtime grants are not a substitute for the workflow roles above.
10. Ensure CI does not rely on the gitignored `.env.lab`. `infra/aca/deploy.sh` currently sources that file and requires `RG`, `ACR`, `CAE`, `KV`, `UAMI_RESOURCE_ID`, and `UAMI_CLIENT_ID`. Make the deployment entrypoint accept those values from the workflow environment, or create a short-lived, untracked `.env.lab` from GitHub repository variables for non-secret IDs/configuration (`AZURE_RESOURCE_GROUP`, `AZURE_CONTAINER_REGISTRY`, `AKS_CLUSTER`, `CONTAINER_APPS_ENV`, `KEY_VAULT_NAME`, `UAMI_NAME`, `UAMI_RESOURCE_ID`, `UAMI_CLIENT_ID`, `AZURE_TENANT_ID`, and `AZURE_SUBSCRIPTION_ID`) and remove it in cleanup. IDs are not secrets; never put tokens or credentials in `.env.lab` or variables. Use GitHub OIDC for Azure authentication and Key Vault/CSI/secret references for runtime tokens.
11. Implement one `/ship-it` sequence for local operations and CI: verify clean worktree, run `uv run poe check`, compute the short current Git SHA, preflight required baseline/RBAC, resolve deployment services, build and push base before dependent images and MCPs independently, deploy selected ACA services, Helm-upgrade the AKS orchestrator when selected/required, wait for ACA health and AKS rollout, then run smoke tests and evals. The workflow on push to `main` must execute the same sequence/entrypoint rather than maintaining a second divergent deploy procedure.
12. Service selection must union changes found relative to `origin/main` with services explicitly named by the operator/workflow, and allow explicit service selection even when the branch changes are already pushed and `git diff origin/main...` is empty. Support an explicit full-fleet request for first deployment or repair. Build the SHA-tagged base before selected agent images; build selected MCP images from their own Dockerfiles. Never skip a requested service because Git history yields no diff.
13. Re-enable `.github/workflows/deploy.yml` only after all UAMI RBAC assignments above and the namespace prerequisite have been verified. Until then keep it disabled and do not use workflow dispatch or push triggers to test privileged deployment. Once enabled, trigger on push to `main` after CI succeeds, use the production environment and OIDC subject above, and expose no `.env.lab` dependency.
14. Smoke checks must wait for all eight ACA apps to become healthy and for the two AKS orchestrator replicas to roll out. Verify `/healthz`, `/readyz`, and a single-store `/plan` request for SKU `ZS-1042` at `store-101`; then run the golden eval suite and report passed/total, with the current known baseline 11/11. Do not report a rollout successful when smoke or evals fail.
15. No deployment image or manifest may use `:latest`. Fail before rollout if a requested ACR image is missing, if mandatory baseline/RBAC checks fail, if the AKS namespace is unavailable, or if checks/tests fail. Record the Git SHA, explicit/derived services, image references, ACA revisions, AKS rollout, smoke result, eval result, and waiver status in the deployment report.

## Eval scenarios

Use the existing eval dataset and runner schema in `tests/evals/scenarios.jsonl` and `tests/evals/run_evals.py`. One example deployment smoke/eval scenario is:

```jsonl
{"id":"stockout-zs1042-store101","goal":"Store 101 will stock out of SKU ZS-1042 by Friday.","sku":"ZS-1042","store_id":"store-101","must_mention":["ZS-1042","store-101"],"must_call":["inventory","supplier","logistics","pricing"],"forbid_call":[],"max_latency_s":240,"expected_status":"plan"}
```

Run the current 11-scenario golden set; the `must_call` and `forbid_call` fields are recorded review metadata, while deterministic routing and refusal gates are asserted by tests.

## Out of scope for this iteration
- Recreating Lab 01 Azure resources or changing the existing cluster size/regions.
- Enabling Defender for Cloud spend waived by ADR 0001.
- Granting the CI UAMI AKS cluster-admin, broad Owner/Contributor at subscription scope, or permissions to create Entra groups.
- Replacing the eight ACA apps with separate per-service Bicep modules.
- Changing application APIs, agent prompts, or business logic.

## Handoff
Hand off to `deploy-engineer` with:

```text
Implement specs/lab-05-deploy.md. Preserve the deployed AKS/ACA environment described in the spec. Verify UAMI RBAC and the pre-created zavashop namespace before re-enabling .github/workflows/deploy.yml. Apply the documented ADR 0001 Defender waiver; add kubelogin conversion after AKS credentials; grant ACR Tasks capability in addition to AcrPush; avoid CI dependence on .env.lab; build the base image before agent services and build MCP images independently. Ensure /ship-it and push-to-main automation share the same build/push/deploy/smoke/eval sequence and accept explicitly named services when origin/main has no diff. Use SHA tags only and report rollout plus the 11-scenario eval result.
```
