from fastapi import APIRouter, Depends, Request
from starlette.concurrency import run_in_threadpool

from learning_agent.api import ChineseRoute, _body, resolve_course_store
from learning_agent.acceptance_course import DEMO_ID
from .ml_lab import MLLab

router = APIRouter(prefix="/api/ml-lab", tags=["机器学习 Lab"], route_class=ChineseRoute)


def lab():
    return MLLab(resolve_course_store(DEMO_ID))


@router.get("")
def view(student_id: str, service=Depends(lab)):
    return service.hints(service.view(student_id))


@router.get("/export")
def export(student_id: str, service=Depends(lab)):
    return service.export(student_id)


@router.post("/{operation}")
async def act(operation: str, request: Request, service=Depends(lab)):
    return await run_in_threadpool(service.act, operation, await _body(request))
