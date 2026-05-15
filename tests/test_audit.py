from __future__ import annotations

import json
from datetime import datetime, timezone

from lib.audit import format_audit_line


def test_format_audit_line_returns_jsonl_with_expected_keys():
    ts = datetime(2026, 5, 15, 1, 2, 3, tzinfo=timezone.utc)
    line = format_audit_line(
        ts=ts,
        actor="operator",
        cmd="tenants deploy",
        tenant="acme",
        image="ghcr.io/example/zc:1",
        result="ok",
    )
    assert line.endswith("\n")
    obj = json.loads(line)
    assert obj == {
        "ts": "2026-05-15T01:02:03Z",
        "actor": "operator",
        "cmd": "tenants deploy",
        "tenant": "acme",
        "image": "ghcr.io/example/zc:1",
        "result": "ok",
    }


def test_format_audit_line_defaults_ts():
    line = format_audit_line(
        actor="operator",
        cmd="backup",
        tenant=None,
        image=None,
        result="ok",
    )
    obj = json.loads(line)
    assert obj["ts"].endswith("Z")
    assert obj["tenant"] is None
