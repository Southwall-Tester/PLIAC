"""Read-only reminders derived from current evidence, not new diagnoses."""
from learning_agent.course_catalog import list_courses, resolve_course
from learning_agent.acceptance_course import DEMO_ID
from learning_agent.course_graph import safe_id


def review_reminders(default_store, student):
    safe_id(student, "学习编号")
    courses = list_courses(default_store)
    if not any(course["id"] == DEMO_ID for course in courses):
        courses.append({"id": DEMO_ID})
    items = []
    for course in courses:
        store = resolve_course(default_store, course["id"])
        graph = store.load_graph()
        if not graph:
            continue
        learner = store._derive(store._read_learner(student), graph)
        for node in graph["nodes"]:
            state = learner["states"][node["id"]]
            if not state["evidence_ids"] and not state["diagnosis_ids"]:
                continue
            kind = ("version_changed" if state["version_changed"] else "review_due" if state["due"]
                    else "needs_work" if state["status"] == "needs_review"
                    else "needs_check" if state["status"] == "uncertain" else None)
            if kind:
                items.append({"course_id": graph["id"], "course_title": graph["title"], "course_version": graph["version"],
                    "node_id": node["id"], "title": node["title"], "kind": kind, "reason": state["reason"],
                    "due_at": state["due_at"]})
    priority = {"needs_work": 0, "version_changed": 1, "review_due": 2, "needs_check": 3}
    items.sort(key=lambda item: (priority[item["kind"]], item["due_at"] or "", item["course_id"], item["node_id"]))
    return {"items": items}
