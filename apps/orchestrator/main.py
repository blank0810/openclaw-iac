from __future__ import annotations

from fastapi import FastAPI

from apps.orchestrator.jobs import JobStore


def verify_request() -> None:
    """Auth seam — no-op for the local MVP. Swap for Firebase JWT later."""
    return None


def create_app(store: JobStore | None = None) -> FastAPI:
    app = FastAPI(title="ZeroClaw Orchestrator")
    app.state.store = store or JobStore()

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok"}

    return app
