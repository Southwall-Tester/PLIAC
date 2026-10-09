from fastapi import APIRouter, Depends, Request
from starlette.concurrency import run_in_threadpool

from learning_agent.api import ChineseRoute, _body, resolve_course_store
from learning_agent.course_graph import CourseGraphError
from learning_agent.course_package import packages, read
from .ml_lab import MLLab

router = APIRouter(prefix="/api/ml-lab", tags=["机器学习 Lab"], route_class=ChineseRoute)


def lab(course_id: str = ""):
    # Preserve the old standalone URL by using its configured default activity.
    if not course_id:
        candidates = [read(path) for path in packages().values()]
        defaults = [c["id"] for c in candidates if any(a.get("engine") == "classification_lab" and a.get("default_entry") for a in c.get("activities", []))]
        if len(defaults) != 1:
            raise CourseGraphError("请从课程入口进入实验。", 409)
        course_id = defaults[0]
    store = resolve_course_store(course_id)
    graph = store.load_graph()
    if not graph or not any(a.get("engine") == "classification_lab" for a in graph.get("activities", [])):
        raise CourseGraphError("当前课程没有配置此实验。", 404)
    return MLLab(store)


@router.get("")
def view(student_id: str, service=Depends(lab)):
    return service.hints(service.view(student_id))


@router.get("/export")
def export(student_id: str, service=Depends(lab)):
    return service.export(student_id)


@router.post("/{operation}")
async def act(operation: str, request: Request, service=Depends(lab)):
    return await run_in_threadpool(service.act, operation, await _body(request))
