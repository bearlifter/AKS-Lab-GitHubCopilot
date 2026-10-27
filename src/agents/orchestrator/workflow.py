"""Deterministic MAF workflow for assembling orchestrator plans."""

from __future__ import annotations

from typing import Literal

from agent_framework import Executor, Workflow, WorkflowBuilder, WorkflowContext, handler
from pydantic import BaseModel, ConfigDict

from .a2a import SpecialistInvoker, build_specialist_goals
from .contracts import Plan


class PlanWorkflowInput(BaseModel):
    """Immutable input passed through the deterministic plan workflow."""

    model_config = ConfigDict(frozen=True)

    goal: str
    sku: str
    store_id: str


class ParallelStageResult(BaseModel):
    """Result from either parallel inventory or pricing stage."""

    model_config = ConfigDict(frozen=True)

    stage: Literal["inventory", "pricing"]
    request: PlanWorkflowInput
    output: str


class SupplierStageResult(BaseModel):
    """Collected stock and price results plus the supplier result."""

    model_config = ConfigDict(frozen=True)

    request: PlanWorkflowInput
    stock_view: str
    price_view: str
    po_view: str


class PlanStageResults(BaseModel):
    """All specialist results required for deterministic plan reconciliation."""

    model_config = ConfigDict(frozen=True)

    request: PlanWorkflowInput
    stock_view: str
    price_view: str
    po_view: str
    shipping_view: str


class _StartPlan(Executor):
    def __init__(self) -> None:
        super().__init__(id="plan_start")

    @handler
    async def start(self, message: PlanWorkflowInput, context: WorkflowContext[PlanWorkflowInput]) -> None:
        await context.send_message(message)


class _InventoryStage(Executor):
    def __init__(self, client: SpecialistInvoker) -> None:
        super().__init__(id="inventory_stage")
        self._client = client

    @handler
    async def check_stock(self, message: PlanWorkflowInput, context: WorkflowContext[ParallelStageResult]) -> None:
        settings = self._client.settings
        goals = build_specialist_goals(sku=message.sku, store_id=message.store_id)
        output = await self._client.invoke(
            name="inventory",
            url=settings.inventory_a2a_url,
            goal=f"{goals.inventory} Request context: {message.goal}",
        )
        await context.send_message(ParallelStageResult(stage="inventory", request=message, output=output))


class _PricingStage(Executor):
    def __init__(self, client: SpecialistInvoker) -> None:
        super().__init__(id="pricing_stage")
        self._client = client

    @handler
    async def recommend_price(self, message: PlanWorkflowInput, context: WorkflowContext[ParallelStageResult]) -> None:
        settings = self._client.settings
        goals = build_specialist_goals(sku=message.sku, store_id=message.store_id)
        output = await self._client.invoke(
            name="pricing",
            url=settings.pricing_a2a_url,
            goal=f"{goals.pricing} Request context: {message.goal}",
        )
        await context.send_message(ParallelStageResult(stage="pricing", request=message, output=output))


class _SupplierStage(Executor):
    def __init__(self, client: SpecialistInvoker) -> None:
        super().__init__(id="supplier_stage")
        self._client = client

    @handler
    async def draft_purchase_order(
        self, messages: list[ParallelStageResult], context: WorkflowContext[SupplierStageResult]
    ) -> None:
        results = {message.stage: message for message in messages}
        if set(results) != {"inventory", "pricing"}:
            raise RuntimeError("The supplier stage requires inventory and pricing results.")

        inventory = results["inventory"]
        pricing = results["pricing"]
        request = inventory.request
        if pricing.request != request:
            raise RuntimeError("Parallel stage results belong to different plan requests.")

        settings = self._client.settings
        goals = build_specialist_goals(sku=request.sku, store_id=request.store_id)
        po_view = await self._client.invoke(
            name="supplier",
            url=settings.supplier_a2a_url,
            goal=(f"{goals.supplier} Inventory assessment: {inventory.output} Price recommendation: {pricing.output}"),
        )
        await context.send_message(
            SupplierStageResult(
                request=request,
                stock_view=inventory.output,
                price_view=pricing.output,
                po_view=po_view,
            )
        )


class _LogisticsStage(Executor):
    def __init__(self, client: SpecialistInvoker) -> None:
        super().__init__(id="logistics_stage")
        self._client = client

    @handler
    async def quote_shipping(self, message: SupplierStageResult, context: WorkflowContext[PlanStageResults]) -> None:
        settings = self._client.settings
        goals = build_specialist_goals(sku=message.request.sku, store_id=message.request.store_id)
        shipping_view = await self._client.invoke(
            name="logistics",
            url=settings.logistics_a2a_url,
            goal=f"{goals.logistics} Purchase-order result: {message.po_view}",
        )
        await context.send_message(
            PlanStageResults(
                request=message.request,
                stock_view=message.stock_view,
                price_view=message.price_view,
                po_view=message.po_view,
                shipping_view=shipping_view,
            )
        )


class _ReconcilePlan(Executor):
    def __init__(self) -> None:
        super().__init__(id="plan_reconcile")

    @handler
    async def reconcile(self, message: PlanStageResults, context: WorkflowContext[None, Plan]) -> None:
        request = message.request
        await context.yield_output(
            Plan(
                sku=request.sku,
                store_id=request.store_id,
                stock_view=message.stock_view,
                price_view=message.price_view,
                po_view=message.po_view,
                shipping_view=message.shipping_view,
                summary=(
                    f"Recovery plan for {request.sku} at {request.store_id}: protect stock, place replenishment, "
                    "ship quickly, and tune price during the stock-out window."
                ),
                next_actions=[
                    "Approve the recommended replenishment purchase order.",
                    "Book the recommended shipment to the target store.",
                    "Apply the price recommendation until stock risk clears.",
                ],
            )
        )


def build_plan_workflow(client: SpecialistInvoker) -> Workflow:
    """Build the fixed parallel-stock-and-price then replenish and ship workflow."""

    start = _StartPlan()
    inventory = _InventoryStage(client)
    pricing = _PricingStage(client)
    supplier = _SupplierStage(client)
    logistics = _LogisticsStage(client)
    reconcile = _ReconcilePlan()

    return (
        WorkflowBuilder(start_executor=start, output_from=[reconcile])
        .add_fan_out_edges(start, [inventory, pricing])
        .add_fan_in_edges([inventory, pricing], supplier)
        .add_chain([supplier, logistics, reconcile])
        .build()
    )


async def run_plan_workflow(*, client: SpecialistInvoker, goal: str, sku: str, store_id: str) -> Plan:
    """Execute the deterministic workflow and return its single reconciled plan."""

    workflow = build_plan_workflow(client)
    result = await workflow.run(PlanWorkflowInput(goal=goal, sku=sku, store_id=store_id))
    outputs = result.get_outputs()
    if len(outputs) != 1 or not isinstance(outputs[0], Plan):
        raise RuntimeError("Plan workflow completed without exactly one reconciled Plan output.")
    return outputs[0]
