"""FastAPI entrypoint for the ZavaShop orchestrator agent."""

from __future__ import annotations

from fastapi import FastAPI

from src.shared.server import make_app
from src.shared.settings import Settings

from .a2a import SpecialistClient, SpecialistInvoker, call_specialists
from .agent import build_agent
from .contracts import Goal, Plan, PlanRefusal


def create_app(settings: Settings | None = None, specialist_client: SpecialistInvoker | None = None) -> FastAPI:
    """Create the orchestrator app with /invoke and /plan endpoints."""

    app_settings = settings or Settings()
    app = make_app(name="orchestrator", build=build_agent, settings=app_settings)
    client = specialist_client or SpecialistClient(settings=app_settings)

    @app.post("/plan", response_model=Plan | PlanRefusal)
    async def plan(goal: Goal) -> Plan | PlanRefusal:
        if goal.store_id is None:
            return PlanRefusal(reason="A recovery plan requires a single store; provide store_id.")

        outputs = await call_specialists(client=client, sku=goal.sku, store_id=goal.store_id)
        return Plan(
            sku=goal.sku,
            store_id=goal.store_id,
            stock_view=outputs.inventory,
            po_view=outputs.supplier,
            shipping_view=outputs.logistics,
            price_view=outputs.pricing,
            summary=(
                f"Recovery plan for {goal.sku} at {goal.store_id}: protect stock, place replenishment, "
                "ship quickly, and tune price during the stock-out window."
            ),
            next_actions=[
                "Approve the recommended replenishment purchase order.",
                "Book the recommended shipment to the target store.",
                "Apply the price recommendation until stock risk clears.",
            ],
        )

    app.state.plan_endpoint = plan

    return app


app = create_app()
