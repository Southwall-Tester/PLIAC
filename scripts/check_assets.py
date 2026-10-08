"""Check references between course content, diagnostic tasks and draft training assets."""
from __future__ import annotations

from collections import Counter
import json
import re
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from learning_agent.course_graph import validate_graph


def main():
    shared_scripts = ("network-layout", "network-view", "network-pixi", "graph-encoding")
    versions = {}
    for name in ("index.html", "documents.html"):
        html = (ROOT / "static" / name).read_text(encoding="utf-8")
        for script in shared_scripts:
            version = re.search(rf'{script}\.js\?v=(\d+)', html)
            assert version, (name, script)
            if script in versions:
                assert versions[script] == version[1], f"Mixed shared script versions: {script} in {name}"
            versions[script] = version[1]
    graph = json.loads((ROOT / "data/courses/ml_classification.json").read_text(encoding="utf-8"))
    assets = json.loads((ROOT / "data/training_blueprints.json").read_text(encoding="utf-8"))
    summary = validate_graph(graph)
    assert 30 <= len(graph["nodes"]) <= 40 and len(graph["chapters"]) == 2
    assert assets["course_id"] == graph["id"]
    assert assets["runtime_status"] == "not_implemented"
    nodes = {n["id"] for n in graph["nodes"]}
    resources = {r["id"] for r in graph["resources"]}
    blueprints = {b["id"]: b for b in assets["blueprints"]}
    assert len(blueprints) >= 3
    tasks = set()
    for node in graph["nodes"]:
        assert set(node.get("resource_ids", [])).issubset(resources), node["id"]
        assert set(node.get("blueprint_ids", [])).issubset(blueprints), node["id"]
        for ident in node.get("blueprint_ids", []):
            assert node["id"] in blueprints[ident]["target_node_ids"], (node["id"], ident)
        if "check_task" in node:
            task = node["check_task"]
            assert task["id"] not in tasks and task["version"] >= 1
            tasks.add(task["id"])
            assert task["rubric"] and len(task["hint_levels"]) == 4
    for blueprint in blueprints.values():
        assert blueprint["course_id"] == graph["id"]
        assert set(blueprint["target_node_ids"] + blueprint["prerequisite_ids"]).issubset(nodes)
        assert blueprint["review_status"] == "draft" and blueprint["runtime_status"] == "not_implemented"
        errors = {e["id"] for e in blueprint["error_types"]}
        for step in blueprint["steps"]:
            assert set(step["error_type_ids"]).issubset(errors)
            assert len(step["hints"]) == 4
            assert step["judge_spec"]["parameters_required"]
        for error in blueprint["error_types"]:
            assert set(error["node_ids"]).issubset(nodes)
    result = {"passed": True, "summary": summary, "relations": dict(Counter(e["type"] for e in graph["edges"])),
              "diagnostic_tasks": len(tasks), "training_blueprints": len(blueprints), "all_training_assets_are_drafts": True}
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
