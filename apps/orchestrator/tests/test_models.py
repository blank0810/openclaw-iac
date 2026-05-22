import pytest
from pydantic import ValidationError

from apps.orchestrator.models import (
    AgentResult,
    CreateAgentRequest,
    JobState,
    StepState,
)


def test_valid_request_minimal():
    req = CreateAgentRequest(name="acme-bot", user_id="u_1")
    assert req.name == "acme-bot"
    assert req.display_name is None


def test_valid_request_full():
    req = CreateAgentRequest(
        name="acme-bot",
        user_id="u_1",
        display_name="Acme",
        slack={"bot_token": "xoxb-x", "app_token": "xapp-x"},
        composio={"mcp_api_key": "ck_x"},
        llm={"model": "claude-haiku-4-5"},
    )
    assert req.slack.bot_token == "xoxb-x"
    assert req.composio.mcp_api_key == "ck_x"
    assert req.llm.model == "claude-haiku-4-5"


def test_rejects_uppercase_slug():
    with pytest.raises(ValidationError):
        CreateAgentRequest(name="AcmeBot")


def test_rejects_underscore_slug():
    with pytest.raises(ValidationError):
        CreateAgentRequest(name="acme_bot")


def test_slack_requires_both_tokens():
    with pytest.raises(ValidationError):
        CreateAgentRequest(name="acme", slack={"bot_token": "xoxb-x"})


def test_agent_result_shape():
    r = AgentResult(
        user_id="u_1", name="acme", display_name="Acme",
        container_name="zeroclaw-acme", container_id="abc123",
        image="ghcr.io/zeroclaw-labs/zeroclaw:v0.7.3-debian",
        server_ip="1.2.3.4", host="1.2.3.4",
        gateway_port=42617, status="running",
    )
    assert r.container_name == "zeroclaw-acme"


def test_job_state_defaults():
    job = JobState(job_id="abc")
    assert job.status == "queued"
    assert job.steps == []
    assert job.result is None
    assert job.error is None


def test_step_state():
    s = StepState(name="create")
    assert s.status == "queued"


def test_create_agent_request_requires_user_id():
    with pytest.raises(ValidationError):
        CreateAgentRequest(name="acme-bot")


def test_create_agent_request_rejects_blank_user_id():
    with pytest.raises(ValidationError):
        CreateAgentRequest(name="acme-bot", user_id="")


def test_create_agent_request_rejects_control_char_user_id():
    with pytest.raises(ValidationError):
        CreateAgentRequest(name="acme-bot", user_id="u\x01bad")


def test_agent_result_includes_ownership_and_docker_info():
    r = AgentResult(
        user_id="u_1",
        name="acme",
        display_name="Acme",
        container_name="zeroclaw-acme",
        container_id="abc123def456",
        image="ghcr.io/zeroclaw-labs/zeroclaw:v0.7.3-debian",
        server_ip="1.2.3.4",
        host="1.2.3.4",
        gateway_port=42617,
        status="running",
    )
    assert r.user_id == "u_1"
    assert r.display_name == "Acme"
    assert r.container_id == "abc123def456"
    assert r.image == "ghcr.io/zeroclaw-labs/zeroclaw:v0.7.3-debian"
