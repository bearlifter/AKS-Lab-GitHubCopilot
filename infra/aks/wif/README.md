# AKS Workload Identity and CSI Handoff

This guide documents identity and secret projection for the ZavaShop orchestrator on `aks-zavashop` in `northcentralus`. The ACR, Key Vault, UAMI, and Log Analytics workspace are in `westus`. Resource identifiers are loaded from the local, gitignored `.env.lab`; never put secret values in that file.

## 1. Federation

Lab 01 §4 creates the AKS OIDC issuer and federates the UAMI to the orchestrator Kubernetes service account. See [Lab 01, §4: Create the AKS cluster](../../../labs/lab-01-environment-setup/README.md#4-create-the-aks-cluster-with-oidc--workload-identity). The AKS federated credential is named `fc-orchestrator` and must match this subject exactly:

```text
system:serviceaccount:zavashop:orchestrator-sa
```

Check the issuer and credential:

```bash
source .env.lab
AKS_OIDC=$(az aks show -g "$RG" -n "$AKS" --query oidcIssuerProfile.issuerUrl -o tsv)
az identity federated-credential list \
  --identity-name "$UAMI" -g "$RG" \
  --query "[].{name:name,issuer:issuer,subject:subject,audiences:audiences}" -o table
```

The same UAMI has a separate GitHub Actions federated credential named `gha-zavashop-production`. Its subject is the immutable repository-ID/environment form, not the classic owner/repository form:

```text
repo:bearlifter@114249644/AKS-Lab-GitHubCopilot@1435400667:environment:production
```

Create or update that credential with the exact production environment subject:

```bash
az identity federated-credential create \
  --name gha-zavashop-production \
  --identity-name "$UAMI" \
  --resource-group "$RG" \
  --issuer https://token.actions.githubusercontent.com \
  --subject 'repo:bearlifter@114249644/AKS-Lab-GitHubCopilot@1435400667:environment:production' \
  --audiences api://AzureADTokenExchange
```

The classic subject `repo:OWNER/REPO:environment:production` does not match this repository's immutable IDs and fails with `AADSTS700213`. If `azure/login` fails, inspect the failed run log to compare the requested subject with the configured federation; do not print or upload an OIDC token:

```bash
gh run view "$RUN_ID" --log | grep -E -C 3 'AADSTS700213|subject|Subject|federated identity'
```

Use the subject shown by the failed Azure login diagnostic when correcting the credential, preserving the `production` environment subject required by the workflow.

## 2. Secrets Store CSI add-on

The Secrets Store CSI Driver and Azure Key Vault provider are enabled through the AKS add-on, not installed separately with Helm:

```bash
az aks enable-addons \
  -a azure-keyvault-secrets-provider \
  -g "$RG" -n "$AKS"
```

Verify the CSI custom resource definition and add-on pods:

```bash
kubectl get crd secretproviderclasses.secrets-store.csi.x-k8s.io
kubectl get pods -n kube-system | grep -E 'secrets-store|azure'
```

The orchestrator Helm chart mounts `SecretProviderClass` `zavashop-github-token` and reads `GITHUB-TOKEN` from Key Vault into the process environment as `GITHUB_TOKEN`. Do not replace the AKS-managed add-on with an independent Helm release.

## 3. Seed Key Vault secrets safely

The token must be present in the shell but must not be echoed, placed in `.env.lab`, or printed by the Azure CLI. Check it before writing, and use `-o none` because the default CLI output contains the secret value:

```bash
: "${GITHUB_TOKEN:?GITHUB_TOKEN must be non-empty before seeding Key Vault}"
az keyvault secret set \
  --vault-name "$KV" \
  --name GITHUB-TOKEN \
  --value "$GITHUB_TOKEN" \
  -o none
```

The five secret names used by this fleet are:

| Key Vault secret | Purpose |
|---|---|
| `GITHUB-TOKEN` | Copilot SDK token projected into `GITHUB_TOKEN`. |
| `INVENTORY-MCP-URL` | Inventory MCP endpoint. |
| `SUPPLIER-MCP-URL` | Supplier MCP endpoint. |
| `SHIPPING-MCP-URL` | Shipping MCP endpoint. |
| `PRICING-MCP-URL` | Pricing MCP endpoint. |

Seed the four endpoint secrets from the ACA FQDNs written by `infra/aca/deploy.sh` to `.env.fqdns`. Source that generated file after deployment and use `-o none` for every value:

```bash
set -a
source .env.fqdns
set +a
: "${ZAVA_INVENTORY_MCP_URL:?inventory MCP URL is required}"
: "${ZAVA_SUPPLIER_MCP_URL:?supplier MCP URL is required}"
: "${ZAVA_SHIPPING_MCP_URL:?shipping MCP URL is required}"
: "${ZAVA_PRICING_MCP_URL:?pricing MCP URL is required}"

az keyvault secret set --vault-name "$KV" --name INVENTORY-MCP-URL --value "$ZAVA_INVENTORY_MCP_URL" -o none
az keyvault secret set --vault-name "$KV" --name SUPPLIER-MCP-URL --value "$ZAVA_SUPPLIER_MCP_URL" -o none
az keyvault secret set --vault-name "$KV" --name SHIPPING-MCP-URL --value "$ZAVA_SHIPPING_MCP_URL" -o none
az keyvault secret set --vault-name "$KV" --name PRICING-MCP-URL --value "$ZAVA_PRICING_MCP_URL" -o none
```

The orchestrator currently consumes the Copilot token through CSI. Keep token values out of command output, source control, and deployment metadata.

## 4. Human AKS access

The school tenant does not allow creating Entra groups. Human cluster administration therefore uses a direct `Azure Kubernetes Service RBAC Cluster Admin` assignment to the operator's Entra object ID; do not substitute a group or grant this role to the GitHub Actions UAMI.

```bash
source .env.lab
AKS_ID=$(az aks show -g "$RG" -n "$AKS" --query id -o tsv)
MY_OID=$(az ad signed-in-user show --query id -o tsv)
az role assignment create \
  --assignee "$MY_OID" \
  --role 'Azure Kubernetes Service RBAC Cluster Admin' \
  --scope "$AKS_ID"

az aks get-credentials -g "$RG" -n "$AKS" --overwrite-existing
kubelogin convert-kubeconfig -l azurecli
kubectl auth can-i get pods -n zavashop
kubectl auth can-i create deployments -n zavashop
kubectl auth can-i get nodes
```

The first two authorization checks should return `yes` for the operator. `kubelogin convert-kubeconfig -l azurecli` is required after `get-credentials` so CI and local kubectl use the active Azure CLI identity rather than an interactive device-code flow.

## 5. Landing-zone validation

Validate Entra ID/Azure RBAC and the required baseline add-ons on `aks-zavashop`:

```bash
source .env.lab
az aks show -g "$RG" -n "$AKS" --query aadProfile -o yaml
az aks show -g "$RG" -n "$AKS" --query addonProfiles.azurepolicy.enabled -o tsv
az aks show -g "$RG" -n "$AKS" \
  --query addonProfiles.omsagent.config.logAnalyticsWorkspaceResourceID -o tsv
```

Azure Policy must be enabled and Container Insights must point to the deployed Log Analytics workspace. Defender for Cloud is **waived (ADR 0001)** for this Azure for Students low-cost deployment; it is not a failed gate. See [ADR 0001: Defender waiver](../../../docs/decisions/0001-defender-waiver.md). Do not enable paid Defender plans as part of this verification.

## 6. Production identity migration

The lab uses one UAMI for the GitHub Actions CI/deployment identity and AKS/ACA runtime identity. This is a lab simplification, not the production target. Production should split them:

- A CI/deployment UAMI federated only to the GitHub `production` environment, with narrowly scoped ACR build/push, ACA deployment, AKS credential/namespace deployment, and resource-read permissions.
- A runtime UAMI federated to the AKS service account and assigned only the Key Vault secret access, ACR pull, and service-specific permissions needed by workloads.

The intended long-term credential flow is a GitHub App plus an OIDC-backed token broker that issues short-lived Copilot credentials to the runtime. This broker is a migration stub/design direction; the current deployment still projects the Key Vault `GITHUB-TOKEN` secret through CSI.
