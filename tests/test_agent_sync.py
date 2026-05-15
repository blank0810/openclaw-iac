from __future__ import annotations

from lib.agent_sync import plan_agent_changes


def test_plan_agent_changes_sorts_create_keep_remove():
    plan = plan_agent_changes(
        desired={"globex", "acme"},
        actual={"acme", "oldco"},
    )
    assert plan == {
        "to_create": ["globex"],
        "to_keep": ["acme"],
        "to_remove": ["oldco"],
    }


def test_plan_agent_changes_handles_empty_sets():
    assert plan_agent_changes(set(), set()) == {
        "to_create": [],
        "to_keep": [],
        "to_remove": [],
    }
