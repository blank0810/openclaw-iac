from __future__ import annotations

from lib.tenant_sync import plan_tenant_changes


def test_plan_tenant_changes_sorts_create_keep_remove():
    plan = plan_tenant_changes(
        desired={"globex", "acme"},
        actual={"acme", "oldco"},
    )
    assert plan == {
        "to_create": ["globex"],
        "to_keep": ["acme"],
        "to_remove": ["oldco"],
    }


def test_plan_tenant_changes_handles_empty_sets():
    assert plan_tenant_changes(set(), set()) == {
        "to_create": [],
        "to_keep": [],
        "to_remove": [],
    }
