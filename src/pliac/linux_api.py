from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, Request
from starlette.concurrency import run_in_threadpool

from learning_agent.api import ChineseRoute, _body, resolve_course_store
from learning_agent.course_graph import CourseGraphError
from .linux_lab import LinuxLab

router = APIRouter(prefix="/api/linux-lab", tags=["LinuxLab 课程实训"], route_class=ChineseRoute)


def lab(course_id: str):
    return LinuxLab(resolve_course_store(course_id))


def local_request(request):
    if request.client and request.client.host not in ("127.0.0.1", "::1", "localhost", "testclient"):
        raise CourseGraphError("本机终端接入只接受本机请求。", 403)
    origin = request.headers.get("origin")
    if origin and urlsplit(origin).netloc != request.headers.get("host"):
        raise CourseGraphError("终端接入不接受跨站请求。", 403)


@router.get("")
def view(student_id: str, mode: str = "auto", service=Depends(lab)):
    return service.view(student_id, mode)


@router.get("/runs/{binding_id}")
def session(binding_id: str, student_id: str, service=Depends(lab)):
    return service.session(binding_id, student_id)


@router.post("/runs")
async def create(request: Request, service=Depends(lab)):
    local_request(request)
    return await run_in_threadpool(service.create, await _body(request))


@router.post("/runs/{binding_id}/{operation}")
async def act(binding_id: str, operation: str, request: Request, service=Depends(lab)):
    local_request(request)
    payload = await _body(request)
    if operation == "reflect":
        return await run_in_threadpool(service.reflect, binding_id, payload)
    if operation not in ("launch", "sync"):
        raise CourseGraphError("未知实训操作。", 404)
    return await run_in_threadpool(getattr(service, operation), binding_id, payload.get("student_id"))
