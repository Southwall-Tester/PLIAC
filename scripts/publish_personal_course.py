"""Publish a course for explicitly authorized personal use, retaining review status."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from learning_agent.course_catalog import resolve_course
from learning_agent.course_graph import CourseGraphStore


def main():
    parser = argparse.ArgumentParser(description="发布个人使用课程，保留真实审核状态")
    parser.add_argument("course_id")
    parser.add_argument("--published-by", required=True)
    parser.add_argument("--note", required=True)
    args = parser.parse_args()
    store = resolve_course(CourseGraphStore(), args.course_id)
    graph = store.load_graph("draft")
    presentation = graph.setdefault("presentation", {})
    if presentation.get("label") != "个人使用 · 已发布":
        presentation["label"] = "个人使用 · 已发布"
        graph = store.save_graph(graph, graph["version"])["graph"]
    result = store.publish(graph["version"], args.published_by, args.note, personal_use=True)
    print(json.dumps(result["publication"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
