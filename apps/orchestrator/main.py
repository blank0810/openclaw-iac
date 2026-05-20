from __future__ import annotations

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException

from apps.orchestrator.jobs import JobStore
from apps.orchestrator.models import AgentResult, CreateAgentRequest, JobState
from apps.orchestrator.pipeline import GATEWAY_PORT, run_pipeline
from lib.config import load_config


def verify_request() -> None:
    """Auth seam — no-op for the local MVP. Swap for Firebase JWT later."""
    return None


def _server_ip() -> str:
    return load_config().server_host


def _result_stub(req: CreateAgentRequest, server_ip: str) -> AgentResult:
    return AgentResult(
        name=req.name, container_name=f"zeroclaw-{req.name}",
        server_ip=server_ip, host=server_ip,
        gateway_port=GATEWAY_PORT, status="started",
    )


def create_app(store: JobStore | None = None) -> FastAPI:
    app = FastAPI(title="ZeroClaw Orchestrator")
    app.state.store = store or JobStore()

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok"}

    @app.post("/agents", status_code=202, dependencies=[Depends(verify_request)])
    def create_agent(req: CreateAgentRequest, bg: BackgroundTasks) -> dict:
        job = app.state.store.create()
        bg.add_task(run_pipeline, app.state.store, job.job_id, req, server_ip=_server_ip())
        return {"job_id": job.job_id}

    @app.get("/jobs/{job_id}", response_model=JobState)
    def get_job(job_id: str) -> JobState:
        job = app.state.store.get(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="job not found")
        return job

    return app
