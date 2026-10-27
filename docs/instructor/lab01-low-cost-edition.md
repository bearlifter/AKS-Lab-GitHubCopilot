# Instructor guidance: Lab 01 low-cost edition (verbatim excerpt)

Source: https://claude.ai/artifact/4SCXNaqxtwJZbatt6Rjh2P (shared by the course instructor)

> Track B: budget Azure
> Use an Azure for Students subscription (credit, no card) or a free account. Run the original sections 1–7 with these changes:
>
> | Original step | Original command | Change to |
> |---|---|---|
> | 2. ACR | --sku Standard | --sku Basic |
> | 2. Log Analytics | default | add --quota 0.1 (GB/day cap), or skip it entirely |
> | 4. AKS | --node-count 2 --node-vm-size Standard_D4s_v6 | --tier free --node-count 1 --node-vm-size $NODE_SIZE |
> | 4. AKS | --enable-addons monitoring,azure-policy --workspace-resource-id $LAW_ID | remove both flags |
> | 4. AKS | (none) | add --enable-addons azure-keyvault-secrets-provider (needed for the CSI secret in Lab 05) |
> | 7.5 Defender | az security pricing create ... --tier Standard (×2) and az aks update --enable-defender | skip all three commands |
>
> Verification (both tracks)
> Drop the four Defender/Policy checks from the original verification block.
