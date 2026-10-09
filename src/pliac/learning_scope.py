"""Resolve bounded learning units from course data and saved, grounded graphs."""
import hashlib
import json
from urllib.parse import urlencode

from learning_agent.course_graph import CourseGraphError
from learnmargin.models import Document, SourceUnit

FIELDS = ("chapter_id", "section_id", "node_id", "source_job_id", "concept_id")


def saved(store, job_id, filename):
    try:
        job = store.job(job_id)
        path = store.directory("jobs", job_id) / filename
        if job["status"] != "completed" or path.resolve() != path or not path.is_file():
            raise ValueError()
        return json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, FileNotFoundError):
        raise CourseGraphError("原学习单元不存在、尚未完成或不属于当前课程。", 404) from None


def key(selection):
    return hashlib.sha256(json.dumps([selection.get(field, "") for field in FIELDS], ensure_ascii=False).encode()).hexdigest()[:24]


def job_scope(job):
    return job.get("scope", {"chapter_id": job.get("chapter_id", "")})


def url(course_id, selection=None):
    return "/course-reader?" + urlencode({"course_id": course_id, **{k: v for k, v in (selection or {}).items() if k in FIELDS and v}})


def resolve(graph, selection, store):
    values = {field: selection.get(field, "") for field in FIELDS}
    if any(not isinstance(value, str) or len(value) > 200 for value in values.values()):
        raise CourseGraphError("学习范围编号无效。")
    chapter = next((c for c in graph["chapters"] if c["id"] == values["chapter_id"]), None)
    if values["chapter_id"] and not chapter:
        raise CourseGraphError("课程章节不存在。", 404)
    nodes = [n for n in graph["nodes"] if not chapter or n["chapter_id"] == chapter["id"]]
    title, kind, parent = (chapter["title"], "chapter", {}) if chapter else (graph["title"], "course", None)
    ranges = [r for c in graph["chapters"] if not chapter or c["id"] == chapter["id"] for r in c.get("source_ranges", [])]
    if values["section_id"]:
        hierarchy = (chapter or {}).get("document_hierarchy", {})
        structure = hierarchy.get("nodes", [])
        section = next((n for n in structure if n["id"] == values["section_id"] and n.get("kind") != "book"), None)
        if not section:
            raise CourseGraphError("该章节下没有此目录单元。", 404)
        descendants = {section["id"]}
        while True:
            expanded = descendants | {n["id"] for n in structure if n.get("parent_id") in descendants}
            if expanded == descendants:
                break
            descendants = expanded
        members = {m["target"] for m in hierarchy.get("memberships", []) if m["source"] in descendants}
        nodes = [n for n in nodes if n["id"] in members]
        title, kind, parent, ranges = section["title"], "section", {"chapter_id": chapter["id"]}, []
    if values["node_id"]:
        node = next((n for n in nodes if n["id"] == values["node_id"]), None)
        if not node:
            raise CourseGraphError("当前范围内没有此知识点。", 404)
        values["chapter_id"] = node["chapter_id"]
        parent = {"chapter_id": node["chapter_id"], "section_id": values["section_id"]}
        title, kind, nodes, ranges = node["title"], "node", [node], []
    refs, focus = [], ""
    if values["source_job_id"] or values["concept_id"]:
        if not values["source_job_id"] or not values["concept_id"] or values["node_id"] or values["section_id"]:
            raise CourseGraphError("请选择一份图谱中的单个知识点。")
        concept_map = saved(store, values["source_job_id"], "knowledge-map.json")
        source_job = store.job(values["source_job_id"])
        if not source_job or source_job.get("course_id") != graph["id"]:
            raise CourseGraphError("原图谱不属于当前课程。", 404)
        concept = next((n for n in concept_map["nodes"] if n["id"] == values["concept_id"]), None)
        if not concept:
            raise CourseGraphError("原图谱中没有这个知识点。", 404)
        parent = {**job_scope(source_job)}
        values["chapter_id"] = source_job.get("chapter_id", "")
        title, kind, ranges = concept["title"], "concept", []
        refs = list(concept.get("source_refs", []))
        lesson = saved(store, values["source_job_id"], "lesson.json")
        if not refs:
            refs = list(dict.fromkeys(ref for s in lesson["sections"] if s["id"] in concept.get("section_ids", []) for ref in s["source_refs"]))
        if not refs:
            raise CourseGraphError("该知识点没有可定位的资料，请先补充来源。", 409)
        focus = concept.get("definition", "")
        # A concept in a handout is not automatically an assessed course node.
        nodes = []
    ids = {n["id"] for n in nodes}
    prerequisites = [n for n in graph["nodes"] if n["id"] not in ids and any(
        e["type"] == "prerequisite" and e["source"] == n["id"] and e["target"] in ids for e in graph["edges"])]
    return {**values, "key": key(values), "kind": kind, "title": title, "course_id": graph["id"],
            "course_version": graph["version"], "node_ids": [n["id"] for n in nodes], "source_refs": refs,
            "source_ranges": ranges, "focus": focus, "url": url(graph["id"], values),
            "parent_url": (url(graph["id"], parent) + ("&job_id=" + values["source_job_id"] if kind == "concept" else "")) if parent is not None else "/courses",
            "prerequisites": [{"id": n["id"], "title": n["title"], "url": url(graph["id"], {"node_id": n["id"]})} for n in prerequisites]}


def concept_materials(scope, store):
    snapshot = saved(store, scope["source_job_id"], "materials.json")
    wanted = set(scope["source_refs"])
    documents, found = [], set()
    for doc in snapshot["documents"]:
        units = []
        for unit in doc["units"]:
            ref = f"{doc['id']}:{unit['index']}"
            if ref in wanted:
                # Cached text only: never accept a caller's path or broaden scope.
                units.append(SourceUnit(index=unit["index"], label=unit["label"], text=unit["text"]))
                found.add(ref)
        if units:
            documents.append(Document(id=doc["id"], name=doc["name"], kind="course_material", unit_label="资料单元", units=units))
    if found != wanted or not documents:
        raise CourseGraphError("知识点的部分来源不在原讲义材料中，请先修复来源。", 409)
    origins = {ref: value for ref, value in snapshot.get("origins", {}).items() if ref in found}
    return documents, origins
