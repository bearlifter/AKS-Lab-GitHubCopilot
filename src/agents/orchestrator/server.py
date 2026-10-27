"""FastAPI entrypoint for the ZavaShop orchestrator agent."""

from __future__ import annotations

import structlog
from fastapi import FastAPI, HTTPException

from src.shared.server import make_app
from src.shared.settings import Settings

from .a2a import SpecialistClient, SpecialistInvoker
from .agent import build_agent
from .contracts import Goal, Plan, PlanRefusal
from .workflow import run_plan_workflow

log = structlog.get_logger(__name__)


def create_app(settings: Settings | None = None, specialist_client: SpecialistInvoker | None = None) -> FastAPI:
    """Create the orchestrator app with /invoke and deterministic /plan endpoints."""

    app_settings = settings or Settings()
    app = make_app(name="orchestrator", build=build_agent, settings=app_settings)
    client = specialist_client or SpecialistClient(settings=app_settings)

    @app.post("/plan", response_model=Plan | PlanRefusal)
    async def plan(goal: Goal) -> Plan | PlanRefusal:
        if goal.store_id is None:
            return PlanRefusal(reason="A recovery plan requires a single store; provide store_id.")

        try:
            return await run_plan_workflow(
                client=client,
                goal=goal.goal,
                sku=goal.sku,
                store_id=goal.store_id,
            )
        except Exception as exc:
            log.error("orchestrator.plan.failed", error_type=type(exc).__name__)
            raise HTTPException(status_code=502, detail="Plan workflow failed") from exc

    app.state.plan_endpoint = plan

    return app


app = create_app()
