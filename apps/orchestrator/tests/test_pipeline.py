import os
import subprocess
import sys

from apps.orchestrator.jobs import JobStore
from apps.orchestrator.models import CreateAgentRequest
from apps.orchestrator.pipeline import (
    _fetch_status,
    build_commands,
    build_create_cmd,
    run_pipeline,
)


def test_create_cmd_includes_flags():
    req = CreateAgentRequest(
        name="acme", display_name="Acme",
        slack={"bot_token": "xoxb-x", "app_token": "xapp-x", "channel_id": "C1"},
        composio={"mcp_api_key": "ck_x"},
    )
    cmd = build_create_cmd(req)
    assert cmd[0] == sys.executable
    assert cmd[1].endswith("zeroclawctl.py")
    assert os.path.isabs(cmd[1])
    assert cmd[2:4] == ["agents", "create"]
    assert "--name" in cmd and "acme" in cmd
    assert "--display-name" in cmd and "Acme" in cmd
    assert "--slack-bot-token" in cmd and "xoxb-x" in cmd
    assert "--slack-app-token" in cmd and "xapp-x" in cmd
    assert "--slack-channel-id" in cmd and "C1" in cmd
    assert "--composio-mcp-key" in cmd and "ck_x" in cmd


def test_create_cmd_omits_absent_optionals():
    req = CreateAgentRequest(name="acme")
    cmd = build_create_cmd(req)
    assert "--slack-bot-token" not in cmd
    assert "--composio-mcp-key" not in cmd
    assert "--display-name" not in cmd


def test_build_commands_order():
    req = CreateAgentRequest(name="acme")
    cmds = build_commands(req)
    assert [c[2:4] for c in cmds] == [
        ["agents", "create"],
        ["server", "deploy"],
        ["agents", "deploy"],
    ]


def test_run_pipeline_success(monkeypatch):
    calls = []

    def fake_run(cmd, **kw):
        calls.append(cmd[2:4])
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    # status lookup also shells out — stub it to a known container state
    monkeypatch.setattr(
        "apps.orchestrator.pipeline._fetch_status", lambda req: "running"
    )

    store = JobStore()
    job = store.create()
    req = CreateAgentRequest(name="acme")
    run_pipeline(store, job.job_id, req, server_ip="1.2.3.4")

    final = store.get(job.job_id)
    assert final.status == "succeeded"
    assert final.result.container_name == "zeroclaw-acme"
    assert final.result.server_ip == "1.2.3.4"
    assert [c for c in calls] == [["agents", "create"], ["server", "deploy"], ["agents", "deploy"]]


def test_run_pipeline_stops_on_failure(monkeypatch):
    def fake_run(cmd, **kw):
        rc = 0 if cmd[2:4] == ["agents", "create"] else 1
        return subprocess.CompletedProcess(cmd, rc, stdout="", stderr="pyinfra exploded")

    monkeypatch.setattr(subprocess, "run", fake_run)
    store = JobStore()
    job = store.create()
    run_pipeline(store, job.job_id, CreateAgentRequest(name="acme"), server_ip="1.2.3.4")

    final = store.get(job.job_id)
    assert final.status == "failed"
    # create succeeded, server_deploy failed, agent_deploy never ran
    assert final.steps[0].status == "succeeded"
    assert final.steps[1].status == "failed"
    assert "exploded" in final.steps[1].error
    assert len(final.steps) == 2


def test_fetch_status_parses_running(monkeypatch):
    def fake_run(cmd, **kw):
        stdout = '{"Name": "zeroclaw-acme", "State": "running", "Status": "Up 2 minutes"}\n'
        return subprocess.CompletedProcess(cmd, 0, stdout=stdout, stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    assert _fetch_status(CreateAgentRequest(name="acme")) == "running"


def test_fetch_status_falls_back_on_garbage(monkeypatch):
    def fake_run(cmd, **kw):
        return subprocess.CompletedProcess(cmd, 0, stdout="not json\n", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    assert _fetch_status(CreateAgentRequest(name="acme")) == "started"


def test_fetch_status_falls_back_on_exception(monkeypatch):
    def fake_run(cmd, **kw):
        raise OSError("boom")

    monkeypatch.setattr(subprocess, "run", fake_run)
    assert _fetch_status(CreateAgentRequest(name="acme")) == "started"
