from pathlib import Path

from jinja2 import Environment, FileSystemLoader
import yaml


REPO_ROOT = Path(__file__).resolve().parents[2]


def render(template_path: str, **ctx) -> str:
    env = Environment(loader=FileSystemLoader(REPO_ROOT))
    return env.get_template(template_path).render(**ctx)


def test_compose_renders_with_agent_name():
    out = render("docker/agent/docker-compose.yml.j2", agent_name="agent-edgar")
    parsed = yaml.safe_load(out)
    assert parsed["services"]["agent"]["container_name"] == "agent-edgar"
    volumes = parsed["services"]["agent"]["volumes"]
    assert any("/opt/agent-edgar/data" in v for v in volumes)
    assert parsed["services"]["agent"]["read_only"] is True
    assert "ALL" in parsed["services"]["agent"]["cap_drop"]
    assert "ports" not in parsed["services"]["agent"]


def test_compose_no_hardcoded_zeroclaw_path():
    out = render("docker/agent/docker-compose.yml.j2", agent_name="agent-x")
    assert "/opt/zeroclaw/" not in out
