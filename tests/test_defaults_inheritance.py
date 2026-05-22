"""agents/_defaults.toml inheritance.

Tests cover deep-merge behavior: per-agent agent.toml overrides defaults
field-by-field, nested sections recurse, lists replace wholesale, explicit
empty strings count as overrides.
"""
from __future__ import annotations

from pathlib import Path

from lib.config import _deep_merge, _load_defaults, load_config


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def _make_env(tmp_path: Path) -> None:
    _write(
        tmp_path / ".env",
        "SERVER_HOST=1.2.3.4\n"
        "DEPLOY_USER=overlord101\n"
        "SSH_PORT=2222\n"
        "DEPLOY_SSH_KEY_PATH=./key.pem\n"
        "ROOT_SSH_KEY_PATH=./key.pem\n"
        "ZEROCLAW_IMAGE=test:latest\n",
    )


def test_deep_merge_replaces_top_level_scalar():
    out = _deep_merge({"a": 1}, {"a": 2})
    assert out == {"a": 2}


def test_deep_merge_recurses_into_nested_dicts():
    out = _deep_merge(
        {"llm": {"provider": "anthropic", "model": "x"}},
        {"llm": {"model": "y"}},
    )
    assert out == {"llm": {"provider": "anthropic", "model": "y"}}


def test_deep_merge_lists_replace_wholesale():
    out = _deep_merge({"a": [1, 2, 3]}, {"a": [9]})
    assert out == {"a": [9]}


def test_deep_merge_empty_string_overrides_default():
    out = _deep_merge({"k": "default"}, {"k": ""})
    assert out["k"] == ""


def test_deep_merge_missing_key_uses_base():
    out = _deep_merge({"a": 1, "b": 2}, {"a": 9})
    assert out == {"a": 9, "b": 2}


def test_load_defaults_missing_returns_empty(tmp_path):
    assert _load_defaults(tmp_path) == {}


def test_load_defaults_parses_when_present(tmp_path):
    _write(tmp_path / "agents" / "_defaults.toml", '[llm]\nmodel = "shared"\n')
    out = _load_defaults(tmp_path)
    assert out == {"llm": {"model": "shared"}}


def test_load_config_inherits_from_defaults(tmp_path):
    _make_env(tmp_path)
    _write(
        tmp_path / "agents" / "_defaults.toml",
        '[llm]\napi_key = "sk-SHARED"\nmodel = "default-model"\n',
    )
    _write(
        tmp_path / "agents" / "alpha" / "agent.toml",
        '[identity]\nname = "alpha"\nstate_dir = "alpha"\n[llm]\nprovider = "anthropic"\n',
    )
    cfg = load_config(tmp_path)
    alpha = cfg.agents[0]
    assert alpha.llm.api_key == "sk-SHARED"
    assert alpha.llm.model == "default-model"
    assert alpha.llm.provider == "anthropic"


def test_load_config_agent_overrides_defaults(tmp_path):
    _make_env(tmp_path)
    _write(
        tmp_path / "agents" / "_defaults.toml",
        '[llm]\napi_key = "sk-SHARED"\nmodel = "default-model"\n',
    )
    _write(
        tmp_path / "agents" / "beta" / "agent.toml",
        '[identity]\nname = "beta"\nstate_dir = "beta"\n'
        '[llm]\nprovider = "anthropic"\napi_key = "sk-BETA"\nmodel = "beta-model"\n',
    )
    cfg = load_config(tmp_path)
    beta = cfg.agents[0]
    assert beta.llm.api_key == "sk-BETA"
    assert beta.llm.model == "beta-model"


def test_load_config_works_without_defaults_file(tmp_path):
    _make_env(tmp_path)
    _write(
        tmp_path / "agents" / "gamma" / "agent.toml",
        '[identity]\nname = "gamma"\nstate_dir = "gamma"\n'
        '[llm]\nprovider = "anthropic"\nmodel = "gamma-model"\n',
    )
    cfg = load_config(tmp_path)
    assert cfg.agents[0].llm.model == "gamma-model"


def test_load_config_autonomy_list_replaces_default(tmp_path):
    """Lists in agent.toml fully replace defaults (no concat).
    Operator-controlled auto_approve must be exact, not surprising."""
    _make_env(tmp_path)
    _write(
        tmp_path / "agents" / "_defaults.toml",
        '[llm]\nmodel = "x"\n[autonomy]\nauto_approve = ["default_a", "default_b"]\n',
    )
    _write(
        tmp_path / "agents" / "delta" / "agent.toml",
        '[identity]\nname = "delta"\nstate_dir = "delta"\n'
        '[autonomy]\nauto_approve = ["only_delta"]\n',
    )
    cfg = load_config(tmp_path)
    assert cfg.agents[0].autonomy.auto_approve == ("only_delta",)
