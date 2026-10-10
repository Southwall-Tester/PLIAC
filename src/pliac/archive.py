"""Read-only cross-course index of a learner's persisted artifacts."""
from learning_agent.course_catalog import list_courses, resolve_course
from learning_agent.acceptance_course import DEMO_ID
from learning_agent.course_graph import CourseGraphError, safe_id


def learning_archive(default_store, student_id):
    safe_id(student_id, "学习编号")
    courses = list_courses(default_store)
    if not any(course["id"] == DEMO_ID for course in courses):
        courses.append({"id": DEMO_ID})
    result = []
    for course in courses:
        store = resolve_course(default_store, course["id"])
        learner = store._read_learner(student_id)
        workspace = learner.get("workspace", {})
        items = []
        for turn in workspace.get("tutor_turns", []):
            proposal = turn["proposal"]
            items.append({"kind": "material", "id": turn["request_id"], "node_id": proposal["target_node_id"],
                "title": proposal["blocks"][0]["heading"] if proposal["blocks"] else "教学安排",
                "course_version": turn["course_version"], "created_at": turn["created_at"]})
        for lesson in workspace.get("lessons", []):
            items.append({"kind": "lesson", "id": lesson["id"], "node_id": lesson["node_id"],
                "title": lesson["title"], "course_version": lesson["course_version"], "created_at": lesson.get("created_at", "")})
        for node_id, versions in workspace.get("notes", {}).items():
            if versions:
                latest = versions[-1]
                items.append({"kind": "note", "id": latest["id"], "node_id": node_id, "title": "学习笔记",
                    "text": latest["text"], "revision": latest["revision"], "course_version": latest["course_version"],
                    "created_at": latest["created_at"]})
        for task in workspace.get("assessments", []):
            items.append({"kind": "assessment", "id": task["id"], "node_id": task["node_id"], "title": task["question"],
                "course_version": task["course_version"], "created_at": task["created_at"], "status": task["status"],
                "answer": task.get("answer"), "result": task.get("result")})
        for report in workspace.get("stage_reports", []):
            items.append({"kind": "report", "id": report["id"], "node_id": "", "title": report["title"],
                "course_version": report["course_version"], "created_at": report["created_at"]})
        for session in workspace.get("ml_lab", {}).get("sessions", []):
            items.append({"kind": "lab", "id": session["id"], "node_id": "",
                "title": session.get("presentation", {}).get("title", "历史实验"),
                "course_version": session["course_version"], "created_at": session["created_at"],
                "lab": {"contract_version": session.get("contract_version"), "step": session["step"],
                    "completed": bool(session.get("final")),
                    "runs": [{"number": run["number"], "config": dict(run["config"]),
                              "train_accuracy": run["result"]["train_accuracy"],
                              "validation_accuracy": run["result"]["validation_accuracy"]}
                             for run in session.get("runs", [])],
                    "checks": [{key: check.get(key) for key in ("task_id", "passed", "note", "feedback", "prompt_level")}
                               for check in session.get("checks", [])],
                    "test_accuracy": session["final"]["result"]["test_accuracy"] if session.get("final") else None}})
        if items:
            graph = store.load_graph()
            versions = {}
            for item in items:
                version = item["course_version"]
                if version not in versions:
                    try:
                        snapshot = store.load_graph(version=version)
                        versions[version] = {node["id"]: node["title"] for node in snapshot["nodes"]} if snapshot else {}
                    except CourseGraphError:
                        versions[version] = {}
                item["node_title"] = versions[version].get(item["node_id"], "历史知识点")
            result.append({"id": course["id"], "title": graph["title"] if graph else "历史课程",
                "items": sorted(items, key=lambda item: item["created_at"], reverse=True)})
    return {"courses": result}
