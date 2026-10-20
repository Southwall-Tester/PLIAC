"""Install a versioned authored seed as an editable course, without publishing.

Existing work, reviews and learner records are never replaced. A matching seed
is a no-op; a changed existing draft must be edited through the normal API.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from learning_agent.course_catalog import COURSE_ID, _directory, metadata, resolve_course
from learning_agent.course_graph import CourseGraphError, CourseGraphStore, _atomic_json, validate_graph


def install(seed: Path, default_store: CourseGraphStore):
    graph = json.loads(seed.read_text(encoding="utf-8"))
    validate_graph(graph)
    if not COURSE_ID.fullmatch(graph["id"]):
        raise CourseGraphError("可编辑课程模板需要 32 位十六进制课程编号。")
    if any(item["review_status"] != "draft" for key in ("nodes", "edges", "resources") for item in graph[key]):
        raise CourseGraphError("模板安装仅接收待审核草稿；请通过课程管理核验并发布。")
    target = _directory(default_store, graph["id"])
    installed = False
    with default_store._writer():
        if target.exists():
            current = resolve_course(default_store, graph["id"]).load_graph("draft")
            if current != graph:
                raise CourseGraphError("同编号课程已有内容变更，已保留现有课程。请在课程管理中合并，不会覆盖。", 409)
        else:
            target.mkdir(parents=True, exist_ok=False)
            _atomic_json(target / "draft.json", graph)
            installed = True
    course = resolve_course(default_store, graph["id"])
    return {"installed": installed, "course": metadata(course), "path": str(target / "draft.json"),
            "author_path": "/author?course_id=" + graph["id"]}


def main():
    parser = argparse.ArgumentParser(description="将课程模板装入独立可编辑草稿，不覆盖已有课程。")
    parser.add_argument("seed", type=Path)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "outputs/course_graph")
    args = parser.parse_args()
    try:
        result = install(args.seed, CourseGraphStore(output_dir=args.output_dir))
    except (OSError, ValueError) as exc:
        print("安装未完成：" + str(exc), file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
