from __future__ import annotations

import uuid

from apps.orchestrator.models import AgentResult, JobState, StepState


class JobStore:
    def __init__(self) -> None:
        self._jobs: dict[str, JobState] = {}

    def create(self, slug: str | None = None) -> JobState:
        job = JobState(job_id=uuid.uuid4().hex, slug=slug)
        self._jobs[job.job_id] = job
        return job

    def get(self, job_id: str) -> JobState | None:
        return self._jobs.get(job_id)

    def active_job_for(self, slug: str | None) -> JobState | None:
        """Return the in-flight (queued/running) job claiming ``slug``, else None.

        A None slug never claims anything, so unkeyed jobs (created without a
        slug) cannot block a real create. Used by POST /agents to reject a
        double-submit for the same agent while one is still provisioning."""
        if slug is None:
            return None
        for job in self._jobs.values():
            if job.slug == slug and job.status in ("queued", "running"):
                return job
        return None

    def start_step(self, job_id: str, name: str) -> None:
        job = self._jobs[job_id]
        job.status = "running"
        job.steps.append(StepState(name=name, status="running"))

    def finish_step(self, job_id: str, name: str, *, ok: bool, error: str | None = None) -> None:
        job = self._jobs[job_id]
        assert job.steps[-1].name == name, f"finish_step({name!r}) but last step is {job.steps[-1].name!r}"
        step = job.steps[-1]
        step.status = "succeeded" if ok else "failed"
        step.error = error
        if not ok:
            job.status = "failed"
            job.error = error

    def fail(self, job_id: str, *, error: str) -> None:
        job = self._jobs[job_id]
        if job.steps and job.steps[-1].status == "running":
            job.steps[-1].status = "failed"
            job.steps[-1].error = error
        job.status = "failed"
        job.error = error

    def succeed(self, job_id: str, result: AgentResult) -> None:
        job = self._jobs[job_id]
        job.status = "succeeded"
        job.result = result
