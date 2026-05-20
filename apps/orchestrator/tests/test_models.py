import pytest
from pydantic import ValidationError

from apps.orchestrator.models import (
    AgentResult,
    CreateAgentRequest,
    JobState,
    StepState,
)


def test_valid_request_minimal():
    req = CreateAgentRequest(name="acme-bot")
    assert req.name == "acme-bot"
    assert req.display_name is None


def test_valid_request_full():
    req = CreateAgentRequest(
        name="acme-bot",
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
        name="acme", container_name="zeroclaw-acme",
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
