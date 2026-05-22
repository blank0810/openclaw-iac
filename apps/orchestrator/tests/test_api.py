from pathlib import Path

import docker
import pytest
from fastapi.testclient import TestClient

from apps.orchestrator import main as main_module
from apps.orchestrator.main import build_agent_definition, create_app
from apps.orchestrator.models import AgentResult, CreateAgentRequest
from tests.test_config import _write_env


def _write_defaults(tmp_path: Path) -> None:
    """Minimal agents/_defaults.toml so load_config can resolve llm.model when
    the request doesn't carry one. Mirrors prod, where _defaults.toml is the
    single source of LLM defaults (model/provider/api_key)."""
    (tmp_path / "agents").mkdir(parents=True, exist_ok=True)
    (tmp_path / "agents" / "_defaults.toml").write_text(
        '[llm]\nprovider = "anthropic"\n'
        'model = "claude-haiku-4-5"\n'
        'api_key = "sk-ant-test"\n'
        "\n[composio]\n"
        'mcp_url = "https://connect.composio.dev/mcp"\n'
    )


class _FakeContainers:
    """Models client.containers.get: NotFound by default; flip exists=True to
    simulate a container already on the daemon."""

    def __init__(self, exists: bool = False):
        self.exists = exists
        self.got: list[str] = []

    def get(self, name):
        self.got.append(name)
        if self.exists:
            return object()  # stand-in container
        raise docker.errors.NotFound(f"no such container: {name}")


class _FakeClient:
    """Stand-in for a docker.DockerClient — provision is stubbed, so only
    containers.get (the existence guard) is exercised."""

    def __init__(self, container_exists: bool = False):
        self.containers = _FakeContainers(exists=container_exists)


def _wire_app(tmp_path, monkeypatch, *, container_exists=False):
    """Build an app pointed entirely at tmp_path with a fake docker client and a
    stubbed provisioner that drives the job to succeeded synchronously."""
    _write_env(tmp_path)
    _write_defaults(tmp_path)

    def fake_provision(client, store, job_id, agent, *, image, states_base,
                       project_root, server_ip):
        store.start_step(job_id, "render_config")
        store.finish_step(job_id, "render_config", ok=True)
        store.succeed(job_id, AgentResult(
            user_id=agent.user_id,
            name=agent.name,
            display_name=agent.display_name,
            container_name=f"zeroclaw-{agent.name}",
            container_id="fakecid123",
            image=image,
            server_ip=server_ip,
            host=server_ip,
            gateway_port=42617,
            status="running",
        ))

    monkeypatch.setattr(main_module, "provision_agent", fake_provision)
    monkeypatch.setattr(main_module, "_server_ip", lambda: "9.9.9.9")

    app = create_app()
    app.state.project_root = tmp_path
    app.state.states_base = tmp_path / "states"
    app.state.docker_client_factory = lambda: _FakeClient(
        container_exists=container_exists
    )
    return app


def test_health():
    client = TestClient(create_app())
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_post_agents_provisions_via_injected_client(tmp_path, monkeypatch):
    app = _wire_app(tmp_path, monkeypatch)
    client = TestClient(app)

    resp = client.post("/agents", json={"name": "acme", "user_id": "u_test"})
    assert resp.status_code == 202
    job_id = resp.json()["job_id"]
    assert job_id

    poll = client.get(f"/jobs/{job_id}")
    assert poll.status_code == 200
    body = poll.json()
    assert body["status"] == "succeeded"
    assert body["result"]["container_name"] == "zeroclaw-acme"
    assert body["result"]["server_ip"] == "9.9.9.9"


def test_post_duplicate_slug_returns_409(tmp_path, monkeypatch):
    app = _wire_app(tmp_path, monkeypatch)
    # An in-flight job already claims the slug; provisioner never runs so it
    # stays queued/running and blocks the second submit.
    app.state.store.create(slug="acme")
    client = TestClient(app)

    resp = client.post("/agents", json={"name": "acme", "user_id": "u_test"})
    assert resp.status_code == 409
    assert "acme" in resp.json()["detail"]


def test_post_existing_container_returns_409(tmp_path, monkeypatch):
    app = _wire_app(tmp_path, monkeypatch, container_exists=True)
    client = TestClient(app)

    resp = client.post("/agents", json={"name": "acme", "user_id": "u_test"})
    assert resp.status_code == 409
    assert "already exists" in resp.json()["detail"]
    # guard fires before any disk write or job creation
    assert not (tmp_path / "agents" / "acme" / "agent.toml").exists()
    assert len(app.state.store._jobs) == 0


def test_post_bad_token_returns_422_and_writes_nothing(tmp_path, monkeypatch):
    app = _wire_app(tmp_path, monkeypatch)
    client = TestClient(app)

    resp = client.post(
        "/agents",
        json={
            "name": "acme",
            "slack": {"bot_token": "xoxb-\x1bevil", "app_token": "xapp-1"},
        },
    )
    assert resp.status_code == 422
    # Pydantic rejects before create_agent runs — no agent.toml on disk.
    assert not (tmp_path / "agents" / "acme" / "agent.toml").exists()
    assert len(app.state.store._jobs) == 0


def test_post_agents_bad_slug_422():
    client = TestClient(create_app())
    resp = client.post("/agents", json={"name": "BadName"})
    assert resp.status_code == 422


def test_get_unknown_job_404():
    client = TestClient(create_app())
    assert client.get("/jobs/nope").status_code == 404


def test_build_agent_definition_serializes_request(tmp_path):
    _write_env(tmp_path)
    _write_defaults(tmp_path)
    req = CreateAgentRequest(
        name="acme",
        user_id="u_42",
        display_name="Acme Bot",
        slack={"bot_token": "xoxb-1", "app_token": "xapp-1", "channel_id": "C1"},
        composio={"mcp_api_key": "ck_1"},
        llm={"provider": "litellm", "model": "gpt-4o"},
    )
    agent = build_agent_definition(req, project_root=tmp_path)

    assert agent.name == "acme"
    assert agent.user_id == "u_42"
    assert agent.display_name == "Acme Bot"
    assert agent.llm.provider == "litellm"
    assert agent.llm.model == "gpt-4o"
    assert agent.slack.enabled is True
    assert agent.slack.bot_token == "xoxb-1"
    assert agent.slack.app_token == "xapp-1"
    assert agent.slack.channel_id == "C1"
    assert agent.composio.enabled is True
    assert agent.composio.mcp_api_key == "ck_1"
    # api_key is never carried by the request — it inherits from _defaults.toml.
    assert agent.llm.api_key == "sk-ant-test"
    # agent.toml persisted as the source of truth
    assert (tmp_path / "agents" / "acme" / "agent.toml").exists()


def test_build_agent_definition_request_only_inherits_defaults(tmp_path):
    """A bare request (no llm/slack/composio) must merge defaults cleanly."""
    _write_env(tmp_path)
    _write_defaults(tmp_path)
    req = CreateAgentRequest(name="globex", user_id="u_1")
    agent = build_agent_definition(req, project_root=tmp_path)

    assert agent.name == "globex"
    assert agent.display_name == "globex"
    assert agent.llm.model == "claude-haiku-4-5"  # from _defaults.toml
    assert agent.llm.provider == "anthropic"
    assert agent.slack.enabled is False
    assert agent.composio.enabled is False


def test_build_agent_definition_carries_fields_through_to_env(tmp_path):
    """The built definition must feed the real provisioner: env reflects llm,
    and config rendering would pick up slack/composio (validated by load_config)."""
    from lib.agent_env import build_agent_env

    _write_env(tmp_path)
    _write_defaults(tmp_path)
    req = CreateAgentRequest(
        name="acme",
        user_id="u_1",
        slack={"bot_token": "xoxb-1", "app_token": "xapp-1"},
        llm={"provider": "litellm", "model": "gpt-4o"},
    )
    agent = build_agent_definition(req, project_root=tmp_path)
    env = build_agent_env(agent)
    assert env["ZEROCLAW_PROVIDER"] == "litellm"
    assert env["ZEROCLAW_MODEL"] == "gpt-4o"
    assert env["ZEROCLAW_API_KEY"] == "sk-ant-test"  # inherited
