"""Interactive prompts + flag passthroughs in `zeroclawctl agents create`.

Tests inject fake `_input` and `_getpass` callables to simulate operator
keystrokes without blocking on real stdin / tty.
"""
from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

from lib.agents import cmd_create


REAL_TEMPLATE = """\
[identity]
name = "REPLACE_ME"
display_name = "REPLACE_ME"
enabled = true
state_dir = "REPLACE_ME"

[runtime]
host_port = 0

[llm]
provider = "anthropic"
model = "claude-sonnet-4-5"
api_key = ""
timeout_secs = 60

[slack]
enabled = false
bot_token = ""
app_token = ""
signing_secret = ""
channel_id = ""
allowed_users = ["*"]
mention_only = true
thread_replies = true
use_markdown_blocks = true
stream_drafts = false

[composio]
enabled = false
api_key = ""
allowed_tools = []
mcp_url = ""
mcp_api_key = ""
mcp_transport = "http"
mcp_auth_header = "x-consumer-api-key"

[autonomy]
level = "supervised"
auto_approve = []

[exec]
enabled = false

[policy]
require_approval_for = []
denied_domains = []
"""


def _scaffold_template(root: Path) -> None:
    base = root / "agents" / "_template"
    (base / "workspace").mkdir(parents=True)
    (base / "agent.toml").write_text(REAL_TEMPLATE)
    (base / "workspace" / "AGENTS.md").write_text("# REPLACE_ME\n")


def _make_prompter(responses: dict):
    """Build fake _input / _getpass that pulls from a prompt→answer map.

    Matches loosely: the first prompt-text substring that exists in `responses`
    wins. Lets tests stub multiple unrelated prompts without ordering coupling.
    """

    def _answer(prompt: str) -> str:
        for hint, answer in responses.items():
            if hint in prompt:
                return answer
        raise AssertionError(f"unexpected prompt: {prompt!r}")

    return _answer


def test_create_no_flags_keeps_legacy_behavior(tmp_path):
    """Without --slack/--composio, no prompts; agent.toml has enabled=false."""
    _scaffold_template(tmp_path)
    rc = cmd_create("plain", project_root=tmp_path)
    assert rc == 0
    toml = (tmp_path / "agents" / "plain" / "agent.toml").read_text()
    assert 'name = "plain"' in toml
    assert 'state_dir = "plain"' in toml
    # display_name defaults to slug
    assert 'display_name = "plain"' in toml
    # enabled flags stay false (no prompts triggered)
    assert "[slack]\nenabled = false" in toml
    assert "[composio]\nenabled = false" in toml


def test_create_slack_flag_prompts_for_tokens(tmp_path):
    _scaffold_template(tmp_path)
    prompter = _make_prompter(
        {
            "Display name": "Dispatch",
            "bot token": "xoxb-test-bot",
            "app token": "xapp-test-app",
            "channel ID": "",
        }
    )
    rc = cmd_create(
        "dispatch",
        slack=True,
        project_root=tmp_path,
        _input=prompter,
        _getpass=prompter,
    )
    assert rc == 0
    toml = (tmp_path / "agents" / "dispatch" / "agent.toml").read_text()
    assert 'display_name = "Dispatch"' in toml
    assert 'bot_token = "xoxb-test-bot"' in toml
    assert 'app_token = "xapp-test-app"' in toml
    # [slack].enabled flipped to true
    assert "[slack]\nenabled = true" in toml
    # [composio].enabled untouched (still false)
    assert "[composio]\nenabled = false" in toml


def test_create_flag_passthroughs_skip_prompts(tmp_path):
    _scaffold_template(tmp_path)

    def fail(prompt: str) -> str:
        raise AssertionError(f"unexpected prompt {prompt!r} - flags should have skipped")

    rc = cmd_create(
        "flagged",
        display_name="Flagged",
        slack_bot_token="xoxb-flag",
        slack_app_token="xapp-flag",
        project_root=tmp_path,
        _input=fail,
        _getpass=fail,
    )
    assert rc == 0
    toml = (tmp_path / "agents" / "flagged" / "agent.toml").read_text()
    assert 'display_name = "Flagged"' in toml
    assert 'bot_token = "xoxb-flag"' in toml
    assert 'app_token = "xapp-flag"' in toml
    assert "[slack]\nenabled = true" in toml


def test_create_slack_token_flag_implies_slack_enable(tmp_path):
    """Passing --slack-bot-token alone activates Slack but does NOT prompt for
    other fields (scripting mode — only set what was explicitly given)."""
    _scaffold_template(tmp_path)

    def fail(prompt: str) -> str:
        raise AssertionError(f"unexpected prompt {prompt!r} - no --slack means no prompts")

    rc = cmd_create(
        "implicit",
        slack_bot_token="xoxb-implicit",
        project_root=tmp_path,
        _input=fail,
        _getpass=fail,
    )
    assert rc == 0
    toml = (tmp_path / "agents" / "implicit" / "agent.toml").read_text()
    assert "[slack]\nenabled = true" in toml
    assert 'bot_token = "xoxb-implicit"' in toml
    # app_token NOT prompted; stays as template default
    assert 'app_token = ""' in toml


def test_create_slack_flag_with_partial_flags_prompts_for_rest(tmp_path):
    """`--slack` + `--slack-bot-token x` should still skip prompts (any passthrough
    indicates scripting). The --slack flag is for fully-interactive mode only."""
    _scaffold_template(tmp_path)

    def fail(prompt: str) -> str:
        raise AssertionError(f"unexpected prompt {prompt!r}")

    rc = cmd_create(
        "partial",
        slack=True,
        slack_bot_token="xoxb-partial",
        project_root=tmp_path,
        _input=fail,
        _getpass=fail,
    )
    assert rc == 0
    toml = (tmp_path / "agents" / "partial" / "agent.toml").read_text()
    assert "[slack]\nenabled = true" in toml
    assert 'bot_token = "xoxb-partial"' in toml
    assert 'app_token = ""' in toml


def test_create_composio_flag_prompts_for_mcp_key(tmp_path):
    _scaffold_template(tmp_path)
    prompter = _make_prompter(
        {"Display name": "ComposioBot", "MCP API key": "ck_test_mcp"}
    )
    rc = cmd_create(
        "composio-bot",
        composio=True,
        project_root=tmp_path,
        _input=prompter,
        _getpass=prompter,
    )
    assert rc == 0
    toml = (tmp_path / "agents" / "composio-bot" / "agent.toml").read_text()
    assert 'mcp_api_key = "ck_test_mcp"' in toml
    assert "[composio]\nenabled = true" in toml


def test_create_composio_blank_key_still_enables(tmp_path):
    """Blank MCP key (inherit from _defaults.toml) is valid - just flip enabled=true."""
    _scaffold_template(tmp_path)
    prompter = _make_prompter({"Display name": "Inherit", "MCP API key": ""})
    rc = cmd_create(
        "inherit",
        composio=True,
        project_root=tmp_path,
        _input=prompter,
        _getpass=prompter,
    )
    assert rc == 0
    toml = (tmp_path / "agents" / "inherit" / "agent.toml").read_text()
    assert "[composio]\nenabled = true" in toml
    # mcp_api_key stays empty (inherit from defaults)
    assert 'mcp_api_key = ""' in toml


def test_create_chmod_0600(tmp_path):
    _scaffold_template(tmp_path)
    rc = cmd_create("perms", project_root=tmp_path)
    assert rc == 0
    mode = stat.S_IMODE(os.stat(tmp_path / "agents" / "perms" / "agent.toml").st_mode)
    assert mode == 0o600


def test_create_abort_on_keyboard_interrupt_leaves_no_dir(tmp_path):
    _scaffold_template(tmp_path)

    def boom(prompt: str) -> str:
        raise KeyboardInterrupt

    rc = cmd_create(
        "aborted",
        slack=True,
        project_root=tmp_path,
        _input=boom,
        _getpass=boom,
    )
    assert rc == 1
    assert not (tmp_path / "agents" / "aborted").exists()


def test_create_warns_on_bad_token_prefix(tmp_path, capsys):
    _scaffold_template(tmp_path)
    prompter = _make_prompter(
        {
            "Display name": "Warned",
            "bot token": "BAD-PREFIX-bot",
            "app token": "xapp-good",
            "channel ID": "",
        }
    )
    cmd_create(
        "warned",
        slack=True,
        project_root=tmp_path,
        _input=prompter,
        _getpass=prompter,
    )
    captured = capsys.readouterr()
    assert "warning" in captured.out
    assert "xoxb-" in captured.out


def test_create_composio_inserts_key_when_template_omits_it(tmp_path):
    """Regression: previous template had `mcp_url = ""` which overrode the
    _defaults.toml URL via deep merge, breaking ComposioConfig validation.
    With the cleaner template that omits mcp_url, --composio must still
    produce a valid file by INSERTING the mcp_api_key key into the section
    rather than only replacing existing placeholders.
    """
    base = tmp_path / "agents" / "_template"
    (base / "workspace").mkdir(parents=True)
    # Minimal template that has [composio] but no mcp_api_key line
    (base / "agent.toml").write_text(
        '[identity]\n'
        'name = "REPLACE_ME"\n'
        'display_name = "REPLACE_ME"\n'
        'state_dir = "REPLACE_ME"\n'
        '\n[composio]\n'
        'enabled = false\n'
    )
    (base / "workspace" / "AGENTS.md").write_text("# REPLACE_ME\n")

    rc = cmd_create(
        "ck-test",
        composio_mcp_key="ck_test_FROM_FLAG",
        project_root=tmp_path,
    )
    assert rc == 0
    toml = (tmp_path / "agents" / "ck-test" / "agent.toml").read_text()
    # Both keys are present, even though only `enabled` had a placeholder
    assert "[composio]\nenabled = true" in toml
    assert 'mcp_api_key = "ck_test_FROM_FLAG"' in toml


def test_create_slack_inserts_tokens_when_template_omits_them(tmp_path):
    """Same regression for Slack tokens. Minimal template scaffolds without
    placeholders must still pick up tokens via insertion."""
    base = tmp_path / "agents" / "_template"
    (base / "workspace").mkdir(parents=True)
    (base / "agent.toml").write_text(
        '[identity]\n'
        'name = "REPLACE_ME"\n'
        'state_dir = "REPLACE_ME"\n'
        '\n[slack]\n'
        'enabled = false\n'
    )

    rc = cmd_create(
        "slim-bot",
        slack_bot_token="xoxb-slim",
        slack_app_token="xapp-slim",
        project_root=tmp_path,
    )
    assert rc == 0
    toml = (tmp_path / "agents" / "slim-bot" / "agent.toml").read_text()
    assert 'bot_token = "xoxb-slim"' in toml
    assert 'app_token = "xapp-slim"' in toml


def test_create_redacts_tokens_in_summary(tmp_path, capsys):
    """Summary output shows token only as prefix/suffix; the middle is masked."""
    _scaffold_template(tmp_path)
    cmd_create(
        "summary",
        display_name="Summary",
        slack_bot_token="xoxb-1234567890ABCDEF",
        slack_app_token="xapp-FEDCBA0987654321",
        project_root=tmp_path,
    )
    out = capsys.readouterr().out
    # Full token not in summary
    assert "xoxb-1234567890ABCDEF" not in out
    assert "xapp-FEDCBA0987654321" not in out
    # Redacted form present
    assert "xoxb-12" in out
    assert "ABCDEF" in out
