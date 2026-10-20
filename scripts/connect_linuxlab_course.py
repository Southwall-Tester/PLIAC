"""Add the authored LinuxLab alignment to an installed draft, preserving edits.

Existing concepts/relations/resources and all learner/publication data survive.
New-ID conflicts stop the migration instead of overwriting authored work.
"""
import copy
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "scripts")]
from build_linux_course import build, COURSE_ID, NODES, PREREQUISITES, CONFUSABLE, RELATED
from learning_agent.course_catalog import resolve_course
from learning_agent.course_graph import CourseGraphStore, CourseGraphError


def connect(default):
    store = resolve_course(default, COURSE_ID)
    current = store.load_graph("draft")
    target = copy.deepcopy(current)
    authored, audit = build()
    old_nodes = {r[0] for r in NODES}
    old_edges = {f"{kind}_{a}_{b}" for kind, rows in (("prerequisite", PREREQUISITES), ("confusable", CONFUSABLE), ("related", RELATED)) for a, b, _ in rows}
    old_sources = {source for n in authored["nodes"] if n["id"] in old_nodes for source in n["source_ids"]}
    original = {"nodes": old_nodes, "edges": old_edges, "sources": old_sources, "resources": {"resource_" + s for s in old_sources}}
    for key, ids in original.items():
        existing = {v["id"]: v for v in target[key]}
        for item in authored[key]:
            if item["id"] in ids:
                if key == "resources" and item["id"] in existing and existing[item["id"]].get("url") == item.get("url"):
                    for node_id in item["node_ids"]:
                        if node_id not in old_nodes and node_id not in existing[item["id"]]["node_ids"]:
                            existing[item["id"]]["node_ids"].append(node_id)
                continue
            if item["id"] in existing:
                # Once added, even later teacher edits are not overwritten.
                if existing[item["id"]] != item and not any(a.get("engine") == "linuxlab" for a in current.get("activities", [])):
                    raise CourseGraphError("新增知识项编号与已有内容冲突：" + item["id"])
            else:
                target[key].append(item)
    activities = target.setdefault("activities", [])
    existing = next((a for a in activities if a.get("id") == "linuxlab"), None)
    if existing and existing != authored["activities"][0]:
        raise CourseGraphError("已有 LinuxLab 映射发生变化，需人工合并。")
    if not existing:
        activities.append(authored["activities"][0])
        # Do not replace the original overview: it may contain teacher edits.
        overview = current.get("overview", "")
        original_overview = "面向初学者的 8 单元课程：40 个知识点，逐点中文解释、操作示例、自检题、评分参考与来源。以 Bash 和 GNU 工具为主要环境；图谱与教学材料由智能体编写，等待教师审核。"
        target["overview"] = (authored["overview"] if overview == original_overview else overview + "\n已关联 LinuxLab 九关实训，并补充日志语义、tail、Vim、键值配置、top 和副本完整性知识。")
    if target == current:
        return {"changed": False, "version": current["version"]}
    result = store.save_graph(target, current["version"])
    return {"changed": True, "version": result["graph"]["version"], "summary": result["summary"], "publication": result["publication"]}


if __name__ == "__main__":
    print(json.dumps(connect(CourseGraphStore()), ensure_ascii=False, indent=2))
