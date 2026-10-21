"""Published course previews and account-bound home summaries."""
from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from learning_agent import api
from learning_agent.api import ChineseRoute, resolve_course_store
from learning_agent.course_catalog import list_courses, resolve_course
from learning_agent.course_graph import CourseGraphError
from learnmargin.rendering import markdown

router = APIRouter(route_class=ChineseRoute)


def available():
    # Catalog metadata may describe newer drafts. Only use it to locate stores;
    # every learner-facing field below comes from the released graph.
    for entry in list_courses(api.store):
        if entry["capabilities"]["learn"]:
            store = resolve_course(api.store, entry["id"])
            graph = store.load_graph()
            if graph:
                yield store, graph


def summary(store, graph):
    presentation = getattr(store, "config", {}).get("presentation", graph.get("presentation", {}))
    return dict(id=graph["id"], title=graph["title"],
                description=presentation.get("description", graph.get("overview", "")),
                label="验收示范课程" if getattr(store, "config", {}).get("delivery_mode") == "acceptance_demo" else presentation.get("label", "课程"),
                chapter_count=len(graph["chapters"]), node_count=len(graph["nodes"]))


@router.get("/api/explore/courses")
def catalog():
    return {"courses": [summary(store, graph) for store, graph in available()]}


@router.get("/api/explore/preview")
def preview(course_store=Depends(resolve_course_store)):
    graph = course_store.load_graph()
    if not graph:
        raise CourseGraphError("这门课程还在准备中。", 404)
    # Explicit fields: no learner records, answer keys, source file paths,
    # personal generated handouts or unpublished material enter public previews.
    return dict(course=summary(course_store, graph),
                chapters=[dict(id=c["id"], title=c["title"]) for c in graph["chapters"]],
                nodes=[dict(id=n["id"], chapter_id=n["chapter_id"], title=n["title"],
                            description=n.get("description", ""),
                            description_html=str(markdown(n.get("description", ""))),
                            paragraphs=[dict(heading=p.get("heading", ""), html=str(markdown(p.get("text", ""))))
                                        for p in n.get("lesson_content", [])]) for n in graph["nodes"]])


@router.get("/api/home/progress")
def progress(student_id: str):
    result = []
    for store, graph in available():
        learner = store.load_learner(student_id, graph)
        workspace = learner.get("workspace", {})
        lessons = workspace.get("lessons", [])
        current = next((item for item in lessons if item["id"] == workspace.get("current_lesson_id")), None)
        ids = {node["id"] for node in graph["nodes"]}
        title = next((node["title"] for node in graph["nodes"]
                      if current and node["id"] == current["node_id"]), "")
        result.append(dict(course_id=graph["id"], onboarded=bool(workspace.get("onboarded")),
                           studied=len({item["node_id"] for item in lessons if item["node_id"] in ids}),
                           passed=sum(learner.get("states", {}).get(node, {}).get("status") == "mastered" for node in ids),
                           total=len(ids), current_title=title,
                           current=bool(current and current.get("course_version") == graph["version"] and title),
                           last_active=max((item.get("created_at", "") for item in workspace.get("events", [])), default="")))
    return JSONResponse({"courses": result}, headers={"Cache-Control": "no-store"})
