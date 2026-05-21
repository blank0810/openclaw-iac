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


def test_fail_sets_terminal_state():
    store = JobStore()
    job = store.create()
    store.start_step(job.job_id, "create")
    store.fail(job.job_id, error="boom")
    fetched = store.get(job.job_id)
    assert fetched.status == "failed"
    assert fetched.error == "boom"
    assert fetched.steps[-1].status == "failed"
    assert fetched.steps[-1].error == "boom"


def test_fail_with_no_steps_still_terminal():
    store = JobStore()
    job = store.create()
    store.fail(job.job_id, error="boom")
    fetched = store.get(job.job_id)
    assert fetched.status == "failed"
    assert fetched.error == "boom"
    assert fetched.steps == []


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


def test_create_stores_slug():
    store = JobStore()
    job = store.create(slug="acme")
    assert job.slug == "acme"


def test_create_slug_defaults_to_none():
    store = JobStore()
    job = store.create()
    assert job.slug is None


def test_claim_slug_first_wins():
    store = JobStore()
    job = store.create(slug="acme")
    assert store.active_job_for("acme") is job


def test_claim_slug_blocks_duplicate_while_active():
    store = JobStore()
    store.create(slug="acme")  # in-flight (queued)
    assert store.active_job_for("acme") is not None


def test_active_job_running_is_detectable():
    store = JobStore()
    job = store.create(slug="acme")
    store.start_step(job.job_id, "render_config")  # now running
    assert store.active_job_for("acme") is job


def test_slug_freed_after_failure():
    store = JobStore()
    job = store.create(slug="acme")
    store.start_step(job.job_id, "x")
    store.finish_step(job.job_id, "x", ok=False, error="e")
    assert store.active_job_for("acme") is None  # failed = no longer active


def test_slug_freed_after_success():
    store = JobStore()
    job = store.create(slug="acme")
    store.start_step(job.job_id, "x")
    store.finish_step(job.job_id, "x", ok=True)
    store.succeed(
        job.job_id,
        AgentResult(
            name="acme",
            container_name="zeroclaw-acme",
            server_ip="1.2.3.4",
            host="1.2.3.4",
            gateway_port=42617,
            status="running",
        ),
    )
    assert store.active_job_for("acme") is None  # succeeded = no longer active


def test_active_job_for_unknown_slug_is_none():
    store = JobStore()
    store.create(slug="acme")
    assert store.active_job_for("globex") is None


def test_active_job_for_does_not_match_none_slug():
    store = JobStore()
    store.create()  # slug is None
    assert store.active_job_for(None) is None
