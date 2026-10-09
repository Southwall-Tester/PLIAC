"""Independent course workspaces, with the existing seed course kept in place."""
from __future__ import annotations

import re
import uuid

from .course_graph import (
    CourseGraphError, CourseGraphStore, _atomic_json, _text, graph_summary,
    safe_id, validate_graph,
)

COURSE_ID = re.compile(r"[0-9a-f]{32}\Z")


def _directory(default_store, course_id):
    """Only direct, non-redirected UUID descendants can be course workspaces."""
    root = default_store.output_dir / "courses"
    target = root / course_id
    if root.resolve() != root or target.resolve() != target:
        raise CourseGraphError("课程目录位置无效。")
    return target


def resolve_course(default_store, course_id=""):
    if course_id == "":
        return default_store
    from .course_package import PackagedCourseStore, packages
    package = packages().get(course_id)
    if package:
        return PackagedCourseStore(default_store, package)
    safe_id(course_id, "课程 ID")
    if course_id == default_store.load_graph("draft")["id"]:
        return default_store
    if not COURSE_ID.fullmatch(course_id):
        raise CourseGraphError("课程不存在。", 404)
    directory = _directory(default_store, course_id)
    draft_path = directory / "draft.json"
    if draft_path.resolve() != draft_path:
        raise CourseGraphError("课程目录位置无效。")
    if not draft_path.is_file():
        raise CourseGraphError("课程不存在。", 404)
    course = CourseGraphStore(seed_path=draft_path, output_dir=directory, clock=default_store.clock)
    if course.load_graph("draft")["id"] != course_id:
        raise CourseGraphError("课程编号与目录不一致。", 409)
    return course


def metadata(course_store, *, is_default=False):
    graph = course_store.load_graph("draft")
    publication = course_store.publication()
    summary = graph_summary(graph)
    presentation = getattr(course_store, "config", {}).get("presentation", graph.get("presentation", {}))
    available = publication["published_version"] is not None or not course_store.content_editable
    overview = graph.get("overview", "")
    description = presentation.get("description", overview if isinstance(overview, str) else "")
    stats = [{"value": summary[key], "label": label} for key, label in
             (("chapter_count", "章"), ("node_count", "个知识点"), ("edge_count", "条关系"))]
    source = course_store.source_summary() if hasattr(course_store, "source_summary") else None
    if source:
        stats += [{"value": source[key], "label": label} for key, label in
                  (("source_pages", "页资料"), ("candidate_nodes", "个候选术语"), ("candidate_edges", "条候选关系")) if key in source]
    return {
        "id": graph["id"], "title": graph["title"], "is_default": is_default,
        "node_count": summary["node_count"], "edge_count": summary["edge_count"],
        "chapter_count": summary["chapter_count"], "resource_count": summary["resource_count"],
        "draft_version": graph["version"], "published_version": publication["published_version"],
        "status": "published" if publication["published_version"] is not None else "draft",
        "has_drafts": summary["has_drafts"], "created_at": graph.get("created_at"),
        "delivery_mode": graph.get("delivery_mode", "formal"),
        "presentation": {"description": description, "label": presentation.get("label", "已发布" if available else "待发布"), "stats": stats},
        "capabilities": {"learn": available, "edit": course_store.content_editable, "generate_handouts": True,
                         "objective_assessment": bool(course_store.assessment)},
        "source_summary": source,
    }



def list_courses(default_store):
    result = [metadata(default_store, is_default=True)]
    from .course_package import PackagedCourseStore, packages
    result.extend(metadata(PackagedCourseStore(default_store, path)) for path in packages().values())
    root = default_store.output_dir / "courses"
    if root.is_dir():
        for directory in sorted(root.iterdir()):
            if COURSE_ID.fullmatch(directory.name) and (directory / "draft.json").is_file():
                result.append(metadata(resolve_course(default_store, directory.name)))
    return result


def create_course(default_store, title, chapter_title="第一章"):
    title = _text(title, "课程名称", 200).strip()
    chapter_title = _text(chapter_title, "章节名称", 200).strip()
    course_id = uuid.uuid4().hex
    graph = {
        "schema_version": 1, "id": course_id, "title": title, "version": 1,
        "created_at": default_store._stamp(),
        "chapters": [{"id": "chapter_1", "title": chapter_title, "description": ""}],
        "nodes": [], "edges": [], "resources": [], "sources": [],
        "review_policy": {"intervals_days": [1, 7, 30]},
    }
    validate_graph(graph, allow_empty=True)
    directory = _directory(default_store, course_id)
    # UUID allocation is exclusive; an existing workspace is never overwritten.
    directory.mkdir(parents=True, exist_ok=False)
    draft_path = directory / "draft.json"
    _atomic_json(draft_path, graph)
    course = CourseGraphStore(seed_path=draft_path, output_dir=directory, clock=default_store.clock)
    return {"course": metadata(course), "graph": graph}
