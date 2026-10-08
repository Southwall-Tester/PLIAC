"""Local research APIs; teacher routes are explicit but are not authentication."""
from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from starlette.concurrency import run_in_threadpool

from .course_graph import MAX_JSON_BYTES, CourseGraphError, store, student_graph, validate_graph

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


@router.get("")
def view(student_id: str = "", view: str = "published"):
    return store.view(student_id, view)


@router.put("")
async def save_graph(request: Request):
    body = await _body(request)
    return await run_in_threadpool(store.save_graph, body.get("graph"), body.get("expected_version"))


@router.post("/publish")
async def publish(request: Request):
    body = await _body(request)
    return await run_in_threadpool(store.publish, body.get("expected_version"), body.get("published_by"), body.get("note"))


@router.get("/export")
def export_graph(view: str = "published"):
    graph = store.load_graph(view)
    if view == "published":
        graph = student_graph(graph)
    return JSONResponse(graph, headers={"Content-Disposition": 'attachment; filename="course-graph.json"'})


@router.get("/teacher/export")
def export_teacher_graph(view: str = "published"):
    return JSONResponse(store.load_graph(view), headers={"Content-Disposition": 'attachment; filename="teacher-course-graph.json"'})


@router.post("/validate")
async def validate(request: Request):
    body = await _body(request)
    return {"valid": True, "summary": validate_graph(body.get("graph"))}


@router.get("/teacher/audit")
def audit(view: str = "draft"):
    from .graph_audit import audit_graph
    graph = store.load_graph(view)
    if graph is None:
        raise CourseGraphError("课程尚未发布，请在草稿工作台核查。", 404)
    return audit_graph(graph)


@router.get("/learner/export")
def export_learner(student_id: str):
    return JSONResponse(store.load_learner(student_id), headers={"Content-Disposition": 'attachment; filename="learner-evidence.json"'})


@router.post("/evidence")
async def evidence(request: Request):
    return await run_in_threadpool(store.add_evidence, await _body(request))


@router.post("/diagnoses")
async def diagnosis(request: Request):
    return await run_in_threadpool(store.add_diagnosis, await _body(request))


@router.put("/profile")
async def profile(request: Request):
    return await run_in_threadpool(store.save_profile, await _body(request))


@router.get("/path")
def learning_path(target_id: str, student_id: str = "", view: str = "published"):
    return store.learning_path(target_id, student_id, view)


@router.get("/recommendations")
def recommendations(node_id: str, student_id: str = "", view: str = "published"):
    return store.recommendations(node_id, student_id, view)


@router.post("/resource-use")
async def resource_use(request: Request):
    return await run_in_threadpool(store.record_resource_use, await _body(request))


@router.post("/extract")
async def extract(request: Request):
    from .llm import extract_candidates
    return await run_in_threadpool(extract_candidates, await _body(request))
