import os
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from fastapi.responses import Response
from starlette.concurrency import run_in_threadpool

from learning_agent.api import ChineseRoute, _body, resolve_course_store
from learning_agent.course_graph import CourseGraphError
from .media import MediaStore, capture_policy
from .media_timeline import activity_timeline

router = APIRouter(prefix="/api/media", tags=["可选摄像头"], route_class=ChineseRoute)


def owner(request, student):
    principal = getattr(request.state, "identity", None)
    if not principal or principal["role"] != "learner" or principal["student"] != student:
        raise CourseGraphError("摄像头操作须由已登录的学习者本人发起。", 403)


@router.get("/policy")
def policy():
    return capture_policy()


@router.post("/{operation}")
async def write(operation: str, request: Request, course_store=Depends(resolve_course_store)):
    body = await _body(request)
    owner(request, body.get("student_id"))
    service = MediaStore(course_store)
    handler = {"start": service.start, "control": service.control, "upload": service.upload}.get(operation)
    if not handler:
        raise CourseGraphError("不支持的摄像头操作。", 404)
    return await run_in_threadpool(handler, body)


@router.get("/session")
def session(request: Request, student_id: str, session_id: str, course_store=Depends(resolve_course_store)):
    owner(request, student_id)
    value = MediaStore(course_store).view(student_id, session_id)
    value["timeline"] = activity_timeline(course_store, student_id, value)
    return JSONResponse(value, headers={"Cache-Control": "no-store"})


@router.get("/sessions")
def sessions(request: Request, student_id: str, course_store=Depends(resolve_course_store)):
    owner(request, student_id)
    return MediaStore(course_store).list_sessions(student_id)


@router.get("/clip")
def clip(request: Request, student_id: str, session_id: str, sequence: int, course_store=Depends(resolve_course_store)):
    owner(request, student_id)
    content = MediaStore(course_store).read(student_id, session_id, sequence)
    return Response(content, media_type="video/webm", headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"})


@router.get("/review/{operation}")
def review(operation: str, request: Request, student_id: str, session_id: str = "", sequence: int = 0,
           course_store=Depends(resolve_course_store)):
    principal = getattr(request.state, "identity", None)
    if (os.environ.get("PLIAC_REQUIRE_AUTH") != "1" or os.environ.get("PLIAC_MEDIA_REVIEW_ENABLED") != "1"
            or not principal or principal["role"] != "admin"):
        raise CourseGraphError("媒体回看需要单独启用并使用管理身份。", 403)
    if operation not in {"sessions", "session", "clip"}:
        raise CourseGraphError("不支持的媒体回看操作。", 404)
    service = MediaStore(course_store)
    # Records an attempt, including an expired/revoked/missing target; no raw
    # media, credential or model data is placed in this audit record.
    service.audit_review(principal["student"], student_id, session_id, f"clip:{sequence}" if operation == "clip" else operation)
    if operation == "clip":
        return Response(service.read(student_id, session_id, sequence), media_type="video/webm",
                        headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"})
    value = service.list_sessions(student_id) if operation == "sessions" else service.view(student_id, session_id)
    if operation == "session":
        value["timeline"] = activity_timeline(course_store, student_id, value)
    return JSONResponse(value, headers={"Cache-Control": "no-store"})
