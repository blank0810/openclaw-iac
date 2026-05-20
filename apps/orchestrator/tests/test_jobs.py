from apps.orchestrator.jobs import JobStore
from apps.orchestrator.models import AgentResult


def test_create_returns_unique_ids():
    store = JobStore()
    a = store.create()
    b = store.create()
    assert a.job_id != b.job_id
    assert a.status == "queued"


def test_get_returns_job():
    store = JobStore()
    job = store.create()
    assert store.get(job.job_id) is job


def test_get_unknown_returns_none():
    store = JobStore()
    assert store.get("nope") is None


def test_set_status_and_steps():
    store = JobStore()
    job = store.create()
    store.start_step(job.job_id, "create")
    fetched = store.get(job.job_id)
    assert fetched.status == "running"
    assert fetched.steps[-1].name == "create"
    assert fetched.steps[-1].status == "running"

    store.finish_step(job.job_id, "create", ok=True)
    assert store.get(job.job_id).steps[-1].status == "succeeded"


def test_finish_step_failure_records_error():
    store = JobStore()
    job = store.create()
    store.start_step(job.job_id, "create")
    store.finish_step(job.job_id, "create", ok=False, error="boom")
    fetched = store.get(job.job_id)
    assert fetched.steps[-1].status == "failed"
    assert fetched.steps[-1].error == "boom"
    assert fetched.status == "failed"


def test_succeed_sets_result():
    store = JobStore()
    job = store.create()
    store.start_step(job.job_id, "create")
    store.finish_step(job.job_id, "create", ok=True)
    result = AgentResult(
        name="acme",
        container_name="zeroclaw-acme",
        server_ip="1.2.3.4",
        host="1.2.3.4",
        gateway_port=42617,
        status="running",
    )
    store.succeed(job.job_id, result)
    fetched = store.get(job.job_id)
    assert fetched.status == "succeeded"
    assert fetched.result is result


def test_multi_step_sequence():
    store = JobStore()
    job = store.create()
    store.start_step(job.job_id, "create")
    store.finish_step(job.job_id, "create", ok=True)
    store.start_step(job.job_id, "server_deploy")
    store.finish_step(job.job_id, "server_deploy", ok=True)
    fetched = store.get(job.job_id)
    assert len(fetched.steps) == 2
    assert [s.name for s in fetched.steps] == ["create", "server_deploy"]
    assert all(s.status == "succeeded" for s in fetched.steps)
