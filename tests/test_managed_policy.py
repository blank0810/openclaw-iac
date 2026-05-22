from __future__ import annotations

import pytest

from lib.managed_policy import build_policy_block, inject_policy_block

POLICY_BEGIN = "<!-- BEGIN MANAGED SECURITY POLICY"
POLICY_END = "<!-- END MANAGED SECURITY POLICY"


def test_build_policy_block_includes_begin_end_markers():
    block = build_policy_block(approval_gates=(), denied_domains=())
    assert POLICY_BEGIN in block
    assert POLICY_END in block


def test_build_policy_block_includes_approval_gates():
    block = build_policy_block(approval_gates=("send_email",), denied_domains=())
    assert "send_email" in block


def test_inject_preserves_content_outside_block():
    existing = (
        "# Header\n\nIntro text.\n\n"
        "<!-- BEGIN MANAGED SECURITY POLICY -->\nOLD\n"
        "<!-- END MANAGED SECURITY POLICY -->\n\nFooter text."
    )
    new_block = build_policy_block(approval_gates=("delete_record",), denied_domains=())
    out = inject_policy_block(existing, new_block)
    assert "# Header" in out
    assert "Intro text." in out
    assert "Footer text." in out
    assert "OLD" not in out
    assert "delete_record" in out


def test_inject_creates_block_when_absent():
    existing = "# Header\n\nNo block here.\n"
    new_block = build_policy_block(approval_gates=(), denied_domains=())
    out = inject_policy_block(existing, new_block)
    assert POLICY_BEGIN in out
    assert "# Header" in out


def test_inject_raises_on_multiple_existing_blocks():
    existing = (
        "# Header\n"
        "<!-- BEGIN MANAGED SECURITY POLICY -->\nA\n<!-- END MANAGED SECURITY POLICY -->\n"
        "middle\n"
        "<!-- BEGIN MANAGED SECURITY POLICY -->\nB\n<!-- END MANAGED SECURITY POLICY -->\n"
    )
    new_block = build_policy_block(approval_gates=(), denied_domains=())
    with pytest.raises(ValueError, match="multiple"):
        inject_policy_block(existing, new_block)
