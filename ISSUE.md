# Add a deterministic `/plan` workflow to the orchestrator

We need a non-LLM, deterministic plan endpoint. Inputs: goal, sku, store_id.
The MAF Workflow runs stock + price in parallel, then PO, then shipping,
then reconciles into a Plan. Inter-agent calls go over A2A.
Also: hydrate GITHUB_TOKEN and four *_MCP_URL secrets from Azure Key Vault
when ZAVA_KV_URL is set.
