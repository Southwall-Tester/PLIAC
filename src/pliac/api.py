"""Local platform endpoints; deployment authentication remains a separate task."""
from fastapi import APIRouter, Depends, Request
from starlette.concurrency import run_in_threadpool

from learning_agent.api import ChineseRoute, _body, resolve_course_store
from learning_agent.course_graph import CourseGraphError, _dict, _text
from .workspace import LearningWorkspace

router = APIRouter(prefix="/api/learning", tags=["学习工作台"], route_class=ChineseRoute)


@router.get("")
def workspace(student_id: str, course_store=Depends(resolve_course_store)):
    return LearningWorkspace(course_store).view(student_id)


@router.get("/teacher")
def teacher(student_id: str, course_store=Depends(resolve_course_store)):
    return LearningWorkspace(course_store).teacher_view(student_id)


@router.post("/teacher/chapter-policy")
async def policy(request: Request, course_store=Depends(resolve_course_store)):
    body = await _body(request)
    def save():
        graph = course_store.load_graph("draft")
        chapter = next((c for c in graph["chapters"] if c["id"] == body.get("chapter_id")), None)
        if not chapter:
            raise CourseGraphError("章节不存在。", 404)
        chapter["completion_policy"] = {"mode": "all_required_mastered", "required_node_ids": body.get("required_node_ids"),
                                        "configured_by": _text(body.get("configured_by"), "规则制定人", 200),
                                        "basis": _text(body.get("basis"), "规则依据", 2000)}
        return course_store.save_graph(graph, body.get("expected_version"))
    return await run_in_threadpool(save)


@router.post("/{operation}")
async def mutate(operation: str, request: Request, course_store=Depends(resolve_course_store)):
    if operation not in {"onboard", "next", "draft", "hint", "answer", "annotate", "resource", "report"}:
        raise CourseGraphError("不支持的学习操作。", 404)
    body = _dict(await _body(request), "学习请求")
    method = "next_lesson" if operation == "next" else operation
    return await run_in_threadpool(getattr(LearningWorkspace(course_store), method), body)
