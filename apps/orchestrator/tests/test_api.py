from fastapi.testclient import TestClient

from apps.orchestrator import main as main_module
from apps.orchestrator.main import create_app


def test_health():
    client = TestClient(create_app())
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_post_agents_returns_202_and_job_id(monkeypatch):
    # Stub the runner so no real pipeline fires; mark job succeeded synchronously.
    def fake_runner(store, job_id, req, *, server_ip):
        store.start_step(job_id, "create")
        store.finish_step(job_id, "create", ok=True)
        store.succeed(job_id, main_module._result_stub(req, server_ip))

    monkeypatch.setattr(main_module, "run_pipeline", fake_runner)
    monkeypatch.setattr(main_module, "_server_ip", lambda: "9.9.9.9")

    client = TestClient(create_app())
    resp = client.post("/agents", json={"name": "acme"})
    assert resp.status_code == 202
    job_id = resp.json()["job_id"]
    assert job_id

    poll = client.get(f"/jobs/{job_id}")
    assert poll.status_code == 200
    body = poll.json()
    assert body["status"] == "succeeded"
    assert body["result"]["container_name"] == "zeroclaw-acme"


def test_post_agents_bad_slug_422():
    client = TestClient(create_app())
    resp = client.post("/agents", json={"name": "BadName"})
    assert resp.status_code == 422


def test_get_unknown_job_404():
    client = TestClient(create_app())
    assert client.get("/jobs/nope").status_code == 404
