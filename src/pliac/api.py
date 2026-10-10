"""Local platform endpoints; deployment authentication remains a separate task."""
import hashlib
from fastapi import APIRouter, Depends, Request
from starlette.concurrency import run_in_threadpool

from learning_agent.api import ChineseRoute, _body, resolve_course_store
from learning_agent.course_graph import CourseGraphError, _dict, _list, _text
from .workspace import LearningWorkspace
from .reading_position import ReadingPositions, recent_reading

router = APIRouter(prefix="/api/learning", tags=["学习工作台"], route_class=ChineseRoute)


@router.get("")
def workspace(student_id: str, course_store=Depends(resolve_course_store)):
    return LearningWorkspace(course_store).view(student_id)


@router.get("/teacher")
def teacher(student_id: str, course_store=Depends(resolve_course_store)):
    return LearningWorkspace(course_store).teacher_view(student_id)


@router.get("/reading-position")
def reading_position(student_id: str, material_id: str, course_store=Depends(resolve_course_store)):
    return ReadingPositions(course_store).read(student_id, material_id)


@router.get("/continue")
def continue_reading(student_id: str):
    from learning_agent import api as course_api
    from learning_agent import document_api
    from fastapi.responses import JSONResponse
    return JSONResponse(recent_reading(course_api.store, student_id, document_api.document_store), headers={'Cache-Control': 'no-store'})


@router.get("/review-reminders")
def review_reminders(student_id: str):
    from fastapi.responses import JSONResponse
    from learning_agent import api as course_api
    from .review_reminders import review_reminders as collect
    return JSONResponse(collect(course_api.store, student_id), headers={"Cache-Control": "no-store"})


@router.post("/reading-position")
async def save_reading_position(request: Request, course_store=Depends(resolve_course_store)):
    return await run_in_threadpool(ReadingPositions(course_store).save, await _body(request))


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


@router.post("/teacher/task")
async def task(request: Request, course_store=Depends(resolve_course_store)):
    body = await _body(request)
    def save():
        graph = course_store.load_graph("draft")
        node = course_store._node(graph, body.get("node_id"))
        question = _text(body.get("question"), "诊断问题", 4000)
        answer = _text(body.get("expected_answer"), "参考答案", 4000)
        rubric = [_text(x, "判据", 2000) for x in _list(body.get("rubric"), "判据", 30)]
        hints = [_text(x, "分级提示", 2000) for x in _list(body.get("hint_levels"), "分级提示", 4)]
        if not rubric or len(hints) != 4:
            raise CourseGraphError("请至少填写一条判据和完整的四级提示。")
        previous = node.get("check_task", {})
        task_id = previous.get("id") or "diag_" + hashlib.sha256(node["id"].encode()).hexdigest()[:24]
        unchanged = (node.get("check_question") == question and node.get("expected_answer") == answer
                     and previous.get("rubric") == rubric and previous.get("hint_levels") == hints)
        version = previous.get("version", 0) + (0 if unchanged else 1)
        node.update(check_question=question, expected_answer=answer,
                    check_task={"id": task_id, "version": version, "rubric": rubric, "hint_levels": hints})
        node["task_ids"] = list(dict.fromkeys([*node.get("task_ids", []), task_id]))
        # save_graph invalidates stale node review; only a later real review can publish.
        return course_store.save_graph(graph, body.get("expected_version"))
    return await run_in_threadpool(save)


@router.post("/{operation}")
async def mutate(operation: str, request: Request, course_store=Depends(resolve_course_store)):
    if operation not in {"onboard", "preferences", "next", "draft", "hint", "answer", "ask", "annotate", "resource", "report", "study", "card", "mixed", "rest"}:
        raise CourseGraphError("不支持的学习操作。", 404)
    body = _dict(await _body(request), "学习请求")
    method = "next_lesson" if operation == "next" else operation
    return await run_in_threadpool(getattr(LearningWorkspace(course_store), method), body)
