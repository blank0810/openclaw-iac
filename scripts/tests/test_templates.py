from pathlib import Path

from jinja2 import Environment, FileSystemLoader
import yaml
try:
    import tomllib
except ImportError:
    import tomli as tomllib


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


def test_config_toml_renders_litellm_provider():
    out = render(
        "docker/agent/config/config.toml.j2",
        provider="litellm",
        anthropic_api_key="",
        litellm_base_url="http://10.0.0.4:4000/v1",
        litellm_api_key="sk-test",
        zeroclaw_model="claude-haiku-4-5",
        slack_bot_token="xoxb-test",
        slack_app_token="xapp-test",
        slack_channel_id="",
        slack_allowed_users="",
        slack_mention_only="false",
        slack_thread_replies="true",
        slack_use_markdown_blocks="true",
        slack_stream_drafts="false",
        composio_api_key="",
        composio_entity_id="default",
        composio_mcp_url="",
        composio_mcp_transport="sse",
        composio_mcp_auth_header="Authorization",
        composio_mcp_api_key="",
    )
    parsed = tomllib.loads(out)
    assert parsed["default_provider"] == "custom:http://10.0.0.4:4000/v1"
    assert parsed["api_key"] == "sk-test"
    assert parsed["default_model"] == "claude-haiku-4-5"
    assert parsed["channels_config"]["slack"]["bot_token"] == "xoxb-test"
