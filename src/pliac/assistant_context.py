"""Read bounded, source-labelled context without changing course or learner state."""
import json
from urllib.parse import urlencode

from learning_agent import document_api
from learning_agent.api import resolve_course_store
from learning_agent.course_graph import CourseGraphError
from .margin import graph_for, storage, job_path, student_job
from .assistant_profile import rank_documents


def clean_context(value):
    if not isinstance(value, dict):
        raise CourseGraphError("页面信息格式无效。")
    result = {}
    for key in ("course_id", "document_id", "node_id", "job_id", "chapter_id", "page", "selection"):
        text = value.get(key, "")
        limit = 3000 if key == "selection" else 160
        if not isinstance(text, str) or len(text) > limit:
            raise CourseGraphError("页面信息过长或格式无效。")
        result[key] = text
    return result


def learner_context(student_id, course_id, node_id=""):
    """Use this account's course entry calibration as teaching context."""
    if not student_id or not course_id:
        return {}
    store = resolve_course_store(course_id)
    learner = store.load_learner(student_id, store.load_graph())
    workspace = learner.get("workspace", {})
    entry = workspace.get("journey", {}).get("active") or {}
    route = entry.get("route") or {}
    calibration = [item for item in route.get("calibration", [])
                   if not node_id or item["node_id"] == node_id]
    return dict(
        profile={key: learner["profile"].get(key) for key in ("goals", "background", "interests")},
        self_assessment=workspace.get("self_assessments", {}).get(node_id),
        entry_calibration=calibration[:6], teaching_approach=route.get("teaching_approach", ""),
        learning_focus=next((step for step in route.get("steps", []) if step["node_id"] == node_id), None),
    )


def context_for(context, question, student_id=""):
    references, notes = [], []

    def add(title, text, url, concept_id=""):
        if text and len(references) < 8:
            references.append(dict(id=f"S{len(references)+1}", title=str(title)[:160],
                                   text=str(text)[:2200], url=url, concept_id=concept_id))

    scores = {}

    def rank(node):
        return (100 if node.get("id") == context["node_id"] else 0) + scores.get(node.get("id"), 0)

    def index(nodes):
        values = rank_documents(question, [str(n.get("title", n.get("label", "")))*3 + " " +
            str(n.get("description", n.get("definition", ""))) + " " + str(n.get("misconception", "")) for n in nodes])
        scores.update({n.get("id"): score for n, score in zip(nodes, values)})

    if context["course_id"]:
        course = resolve_course_store(context["course_id"])
        graph, view = graph_for(course)
        notes.append(f"课程：{graph['title']}；版本：{graph['version']}；内容状态：{view}。")
        nodes = graph.get("nodes", [])
        index(nodes)
        if context["chapter_id"]:
            nodes = [n for n in nodes if n.get("chapter_id") == context["chapter_id"]]
        for node in sorted(nodes, key=rank, reverse=True)[:4]:
            if not rank(node):
                continue
            excerpt = {k: node[k] for k in ("title", "description", "check_question", "expected_answer", "misconception", "review_status", "lesson_content")
                       if k in node}
            excerpt["prerequisites"] = [e["source"] for e in graph.get("edges", [])
                                        if e["type"] == "prerequisite" and e["target"] == node["id"]]
            add(node["title"], json.dumps(excerpt, ensure_ascii=False),
                ("/author?" if view == "draft" else "/knowledge?") +
                urlencode(dict(course_id=graph["id"], node_id=node["id"])), node["id"])
        if not references:
            add(graph["title"] + " · 总览", json.dumps(dict(
                title=graph["title"], overview=graph.get("overview", ""),
                chapters=[c.get("title", c.get("name", "")) for c in graph.get("chapters", [])],
                concept_count=len(graph.get("nodes", []))), ensure_ascii=False),
                "/course-reader?" + urlencode(dict(course_id=graph["id"])))
        if context["job_id"]:
            store = storage(course)
            student_job(store, context["job_id"], student_id)
            lesson = json.loads(job_path(store, context["job_id"], "lesson.json").read_text(encoding="utf-8"))
            concept_map = json.loads(job_path(store, context["job_id"], "knowledge-map.json").read_text(encoding="utf-8"))
            index(concept_map.get("nodes", []))
            for node in sorted(concept_map.get("nodes", []), key=rank, reverse=True)[:2]:
                if rank(node):
                    add(node["title"], json.dumps(node, ensure_ascii=False),
                        "/course-reader?" + urlencode(dict(course_id=graph["id"], job_id=context["job_id"])), node["id"])
            index(lesson.get("sections", []))
            for section in sorted(lesson.get("sections", []), key=rank, reverse=True)[:3]:
                add(section.get("title", "讲义"),
                    json.dumps({k: section[k] for k in ("title", "explanation", "worked_example") if k in section},
                               ensure_ascii=False),
                    "/course-reader?" + urlencode(dict(course_id=graph["id"], job_id=context["job_id"])))
    if context["document_id"]:
        store = document_api.document_store
        job = store.status(context["document_id"])
        graph = store.graph(context["document_id"])
        notes.append(f"当前资料：{job['title']}；资料图谱包含待核验候选。")
        index(graph.get("nodes", []))
        for node in sorted(graph.get("nodes", []), key=rank, reverse=True)[:4]:
            if not rank(node):
                continue
            add(node.get("title", node.get("label", "资料知识点")), json.dumps(node, ensure_ascii=False),
                "/documents?" + urlencode(dict(id=context["document_id"], node_id=node["id"])), node["id"])
        if not references:
            add(job["title"] + " · 图谱总览", json.dumps(dict(title=job["title"],
                concept_count=len(graph.get("nodes", [])), relation_count=len(graph.get("edges", [])),
                sample_titles=[n.get("title", n.get("label", "")) for n in graph.get("nodes", [])[:20]],
                scope="知识点名称样例；详细解释可选择具体知识点后继续"), ensure_ascii=False),
                "/documents?" + urlencode(dict(id=context["document_id"])))
    if context["selection"]:
        notes.append("学习者在页面选中的文字（用户提供的引用）：\n" + context["selection"])
    return dict(summary="\n".join(notes), references=references, course_id=context["course_id"],
                document_id=context["document_id"], chapter_id=context["chapter_id"])
