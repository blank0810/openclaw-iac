from __future__ import annotations


def plan_agent_changes(desired: set[str], actual: set[str]) -> dict[str, list[str]]:
    return {
        "to_create": sorted(desired - actual),
        "to_keep": sorted(desired & actual),
        "to_remove": sorted(actual - desired),
    }
