"""Local research APIs; teacher routes are explicit but are not authentication."""
from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Depends, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from starlette.concurrency import run_in_threadpool

from .course_graph import MAX_JSON_BYTES, CourseGraphError, store, student_graph, validate_graph
from .course_catalog import create_course, list_courses, resolve_course

logger = logging.getLogger("learning_agent")


class ChineseRoute(APIRoute):
    def get_route_handler(self):
        handler = super().get_route_handler()

        async def guarded(request: Request):
            try:
                return await handler(request)
            except CourseGraphError as exc:
                return JSONResponse(status_code=exc.status_code, content={"detail": str(exc)})
            except RequestValidationError:
                return JSONResponse(status_code=422, content={"detail": "请求参数不完整或类型不正确，请检查提交内容。"})
            except Exception:
                logger.exception("Course operation failed")
                return JSONResponse(status_code=500, content={"detail": "操作未完成，请稍后重试；若持续失败，请维护者检查日志。技术异常不会记为能力不足。"})

        return guarded


router = APIRouter(prefix="/api/course-graph", tags=["课程图谱"], route_class=ChineseRoute)
courses_router = APIRouter(prefix="/api/courses", tags=["课程"], route_class=ChineseRoute)


def resolve_course_store(course_id: str = ""):
    # Read the module variable at request time so isolated stores stay isolated.
    return resolve_course(store, course_id)


async def _body(request):
    chunks, size = [], 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > MAX_JSON_BYTES + 4096:
            raise CourseGraphError("请求超过 2 MB，请缩小提交内容。", 413)
        chunks.append(chunk)
    try:
        body = json.loads(b"".join(chunks))
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise CourseGraphError("提交内容不是有效 JSON。") from exc
    if not isinstance(body, dict):
        raise CourseGraphError("提交内容须为 JSON 对象。")
    return body


@courses_router.get("")
def courses():
    return {"courses": list_courses(store)}


@courses_router.post("")
async def new_course(request: Request):
    body = await _body(request)
    return await run_in_threadpool(create_course, store, body.get("title"), body.get("chapter_title", "第一章"))


@router.get("")
def view(student_id: str = "", view: str = "published", course_store=Depends(resolve_course_store)):
    return course_store.view(student_id, view)


@router.put("")
async def save_graph(request: Request, course_store=Depends(resolve_course_store)):
    body = await _body(request)
    return await run_in_threadpool(course_store.save_graph, body.get("graph"), body.get("expected_version"))


@router.post("/publish")
async def publish(request: Request, course_store=Depends(resolve_course_store)):
    body = await _body(request)
    return await run_in_threadpool(course_store.publish, body.get("expected_version"), body.get("published_by"), body.get("note"))


@router.get("/export")
def export_graph(view: str = "published", course_store=Depends(resolve_course_store)):
    graph = course_store.load_graph(view)
    if view == "published":
        graph = student_graph(graph)
    return JSONResponse(graph, headers={"Content-Disposition": 'attachment; filename="course-graph.json"'})


@router.get("/teacher/export")
def export_teacher_graph(view: str = "published", course_store=Depends(resolve_course_store)):
    return JSONResponse(course_store.load_graph(view), headers={"Content-Disposition": 'attachment; filename="teacher-course-graph.json"'})


@router.post("/validate")
async def validate(request: Request, course_store=Depends(resolve_course_store)):
    body = await _body(request)
    return {"valid": True, "summary": validate_graph(body.get("graph"), allow_empty=True)}


@router.get("/teacher/audit")
def audit(view: str = "draft", course_store=Depends(resolve_course_store)):
    from .graph_audit import audit_graph
    graph = course_store.load_graph(view)
    if graph is None:
        raise CourseGraphError("课程尚未发布，请在草稿工作台核查。", 404)
    return audit_graph(graph)


@router.get("/learner/export")
def export_learner(student_id: str, course_store=Depends(resolve_course_store)):
    return JSONResponse(course_store.load_learner(student_id), headers={"Content-Disposition": 'attachment; filename="learner-evidence.json"'})


@router.post("/evidence")
async def evidence(request: Request, course_store=Depends(resolve_course_store)):
    return await run_in_threadpool(course_store.add_evidence, await _body(request))


@router.post("/diagnoses")
async def diagnosis(request: Request, course_store=Depends(resolve_course_store)):
    return await run_in_threadpool(course_store.add_diagnosis, await _body(request))


@router.put("/profile")
async def profile(request: Request, course_store=Depends(resolve_course_store)):
    return await run_in_threadpool(course_store.save_profile, await _body(request))


@router.get("/path")
def learning_path(target_id: str, student_id: str = "", view: str = "published", course_store=Depends(resolve_course_store)):
    return course_store.learning_path(target_id, student_id, view)


@router.get("/recommendations")
def recommendations(node_id: str, student_id: str = "", view: str = "published", course_store=Depends(resolve_course_store)):
    return course_store.recommendations(node_id, student_id, view)


@router.post("/resource-use")
async def resource_use(request: Request, course_store=Depends(resolve_course_store)):
    return await run_in_threadpool(course_store.record_resource_use, await _body(request))


@router.post("/extract")
async def extract(request: Request, course_store=Depends(resolve_course_store)):
    from .llm import extract_candidates
    return await run_in_threadpool(extract_candidates, await _body(request))
