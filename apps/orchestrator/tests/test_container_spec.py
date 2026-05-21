from docker.types import LogConfig, Ulimit

from apps.orchestrator.provisioner import GATEWAY_PORT, build_container_spec
from lib.config import load_config
from tests.test_config import _write_agent, _write_env


def _agent(tmp_path, **overrides):
    _write_env(tmp_path)
    _write_agent(tmp_path, "acme", **overrides)
    return load_config(tmp_path).agents[0]


def test_spec_core_identity(tmp_path):
    agent = _agent(tmp_path)
    spec = build_container_spec(
        agent,
        env={"ZEROCLAW_PROVIDER": "anthropic"},
        state_dir="/opt/zeroclaw/states/acme",
        image="img:1",
    )
    assert spec["name"] == "zeroclaw-acme"
    assert spec["image"] == "img:1"
    assert spec["detach"] is True


def test_spec_hardening_flags(tmp_path):
    agent = _agent(tmp_path)
    spec = build_container_spec(agent, env={}, state_dir="/s", image="i")
    assert spec["read_only"] is True
    assert spec["cap_drop"] == ["ALL"]
    assert spec["security_opt"] == ["no-new-privileges:true"]
    assert spec["user"] == "65534:65534"
    assert spec["tmpfs"] == {"/tmp": "rw,noexec,nosuid,size=64m"}
    assert spec["mem_limit"] == "512m"
    assert spec["pids_limit"] == 256
    assert spec["nano_cpus"] == 1_000_000_000
    assert spec["restart_policy"] == {"Name": "unless-stopped"}
    assert spec["network"] == "zc-acme"


def test_spec_ulimits_nofile(tmp_path):
    agent = _agent(tmp_path)
    spec = build_container_spec(agent, env={}, state_dir="/s", image="i")
    ulimits = spec["ulimits"]
    assert len(ulimits) == 1
    u = ulimits[0]
    assert isinstance(u, Ulimit)
    assert u["Name"] == "nofile"
    assert u["Soft"] == 1024
    assert u["Hard"] == 2048


def test_spec_log_config_json_file(tmp_path):
    agent = _agent(tmp_path)
    spec = build_container_spec(agent, env={}, state_dir="/s", image="i")
    lc = spec["log_config"]
    assert isinstance(lc, LogConfig)
    assert lc["Type"] == "json-file"
    assert lc["Config"] == {"max-size": "10m", "max-file": "5"}


def test_spec_volumes(tmp_path):
    agent = _agent(tmp_path)
    spec = build_container_spec(
        agent, env={}, state_dir="/opt/zeroclaw/states/acme", image="i"
    )
    vols = spec["volumes"]
    assert vols["/opt/zeroclaw/states/acme/.zeroclaw/config.toml"] == {
        "bind": "/zeroclaw-data/.zeroclaw/config.toml",
        "mode": "ro",
    }
    assert vols["/opt/zeroclaw/states/acme/workspace"] == {
        "bind": "/zeroclaw-data/workspace",
        "mode": "rw",
    }


def test_spec_env_passed_through(tmp_path):
    agent = _agent(tmp_path)
    spec = build_container_spec(
        agent, env={"ZEROCLAW_API_KEY": "sk-x"}, state_dir="/s", image="i"
    )
    assert spec["environment"]["ZEROCLAW_API_KEY"] == "sk-x"


def test_spec_no_ports_when_host_port_zero(tmp_path):
    agent = _agent(tmp_path)  # default host_port = 0
    spec = build_container_spec(agent, env={}, state_dir="/s", image="i")
    assert "ports" not in spec or spec.get("ports") in (None, {})


def test_spec_ports_bind_localhost_when_host_port_set(tmp_path):
    agent = _agent(tmp_path, host_port=42617)
    spec = build_container_spec(agent, env={}, state_dir="/s", image="i")
    assert spec["ports"] == {f"{GATEWAY_PORT}/tcp": ("127.0.0.1", 42617)}
