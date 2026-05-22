from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

# Ensure project root is on sys.path so `import lib...` works in tests.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


@pytest.fixture
def isolated_env(monkeypatch, tmp_path):
    """Wipe project-relevant env vars so tests don't see operator's real .env."""
    prefixes = (
        "ZEROCLAW_",
        "ANTHROPIC_",
        "LITELLM_",
        "SLACK_",
        "COMPOSIO_",
        "SERVER_",
        "DEPLOY_",
    )
    for key in list(os.environ.keys()):
        if key.startswith(prefixes):
            monkeypatch.delenv(key, raising=False)
    return tmp_path
