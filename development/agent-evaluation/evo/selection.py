from __future__ import annotations

from typing import Any

from .spec import SPEC_SCHEMA


PLAN_SCHEMA = "agentbase-evo-plan/v1"


def build_plan(spec: dict[str, Any]) -> dict[str, Any]:
    combinations = {entry["id"]: entry for entry in spec["combinations"]}
    items = {entry["id"]: entry for entry in spec["evaluations"]["items"]}
    groups = {entry["id"]: entry for entry in spec["evaluations"]["groups"]}
    selection = spec.get("selection", {})
    combo_ids = selection.get("combinations", list(combinations))
    selected_groups = selection.get("groups")
    if selected_groups is None:
        selected_groups = [identity for identity, group in groups.items() if group.get("active", False)]
    replicates = selection.get("replicates", 1)

    item_groups: dict[str, list[str]] = {}
    for group_id in selected_groups:
        for item_id in groups[group_id]["items"]:
            item_groups.setdefault(item_id, []).append(group_id)

    jobs_by_key: dict[tuple[Any, ...], dict[str, Any]] = {}
    for combo_id in combo_ids:
        for item_id, group_ids in item_groups.items():
            item = items[item_id]
            observations = tuple(sorted(set(item.get("observations", []))))
            for replicate in range(1, replicates + 1):
                key = (combo_id, item_id, item["input_version"], item["protocol"], observations, replicate)
                jobs_by_key[key] = {
                    "id": f"j{len(jobs_by_key) + 1}",
                    "combination": combo_id,
                    "item": item_id,
                    "input_version": item["input_version"],
                    "protocol": item["protocol"],
                    "observations": list(observations),
                    "replicate": replicate,
                    "groups": sorted(group_ids),
                }
    jobs = list(jobs_by_key.values())
    return {
        "schema": PLAN_SCHEMA,
        "source": {"schema": SPEC_SCHEMA, "id": spec["id"], "version": spec["version"]},
        "selection": {"combinations": list(combo_ids), "groups": list(selected_groups), "replicates": replicates},
        "job_count": len(jobs),
        "jobs": jobs,
    }
