"""Provider registry: named LLM profiles and the logic to apply one as the
global default or onto a single agent.

The registry (`agents/_providers.toml`, mode 600, server-side, gitignored —
like `_defaults.toml`) holds the secrets so switching never passes keys through
the API. Each profile is `[<name>] provider/model/api_key`. Applying a profile
writes those three fields into the target's `[llm]` table with tomlkit, which
preserves the rest of the file (comments, other sections, formatting).
"""

from __future__ import annotations

from pathlib import Path

try:
    import tomllib
except ImportError:  # pragma: no cover - Python 3.10 compatibility
    import tomli as tomllib

import tomlkit


def _registry_path(project_root: Path) -> Path:
    return project_root / "agents" / "_providers.toml"


def _defaults_path(project_root: Path) -> Path:
    return project_root / "agents" / "_defaults.toml"


def load_profiles(project_root: Path) -> dict[str, dict]:
    """All registry profiles as {name: {provider, model, api_key}}. Empty if the
    registry file is absent (the switch endpoints then 404/409 cleanly)."""
    path = _registry_path(project_root)
    if not path.exists():
        return {}
    return tomllib.loads(path.read_text())


def masked_profiles(project_root: Path) -> list[dict]:
    """Profiles for API responses — provider/model only, api_key never exposed
    (just whether one is set)."""
    out = []
    for name, p in sorted(load_profiles(project_root).items()):
        out.append(
            {
                "name": name,
                "provider": p.get("provider", ""),
                "model": p.get("model", ""),
                "api_key_set": bool(p.get("api_key")),
            }
        )
    return out


def current_default(project_root: Path) -> dict:
    """The provider/model currently in `_defaults.toml [llm]`, matched back to a
    profile name when one matches (provider+model)."""
    path = _defaults_path(project_root)
    llm = tomllib.loads(path.read_text()).get("llm", {}) if path.exists() else {}
    provider, model = llm.get("provider", ""), llm.get("model", "")
    name = None
    for pname, p in load_profiles(project_root).items():
        if p.get("provider") == provider and p.get("model") == model:
            name = pname
            break
    return {"profile": name, "provider": provider, "model": model}


def _apply_profile_to(path: Path, profile: dict) -> None:
    """Write provider/model/api_key into the `[llm]` table of the TOML at
    ``path`` (creating the table if absent), preserving everything else."""
    doc = tomlkit.parse(path.read_text()) if path.exists() else tomlkit.document()
    llm = doc.get("llm")
    if llm is None:
        llm = tomlkit.table()
        doc["llm"] = llm
    llm["provider"] = profile["provider"]
    llm["model"] = profile["model"]
    llm["api_key"] = profile.get("api_key", "")
    path.write_text(tomlkit.dumps(doc))


def set_default_provider(profile_name: str, project_root: Path) -> dict:
    """Point `_defaults.toml [llm]` at a registry profile. Affects NEW agents."""
    profiles = load_profiles(project_root)
    if profile_name not in profiles:
        raise KeyError(profile_name)
    _apply_profile_to(_defaults_path(project_root), profiles[profile_name])
    return current_default(project_root)


def set_agent_provider(profile_name: str, agent_name: str, project_root: Path) -> dict:
    """Write a registry profile into one agent's `agent.toml [llm]` (the source
    of truth re-rendered at provision time). Caller re-provisions the container
    so the change takes effect."""
    profiles = load_profiles(project_root)
    if profile_name not in profiles:
        raise KeyError(profile_name)
    agent_toml = project_root / "agents" / agent_name / "agent.toml"
    if not agent_toml.exists():
        raise FileNotFoundError(agent_toml)
    profile = profiles[profile_name]
    _apply_profile_to(agent_toml, profile)
    return {"provider": profile["provider"], "model": profile["model"]}
