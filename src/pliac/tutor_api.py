"""Local teaching API; authenticated deployment is tracked separately."""
import copy

from fastapi import APIRouter, Depends, Request
from starlette.concurrency import run_in_threadpool

from learning_agent.api import ChineseRoute, _body, resolve_course_store
from learning_agent.course_graph import CourseGraphError, _text, _integer, safe_id
from .margin import configured_api
from .tutor import generate_teaching, teaching_context
from .workspace import LearningWorkspace
from .assessment import AssessmentService, evaluate_answer

router = APIRouter(prefix="/api/tutor", route_class=ChineseRoute)


@router.get('/resources')
async def resources(student_id: str, node_id: str, course_store=Depends(resolve_course_store)):
    from fastapi.responses import JSONResponse
    from .resources import resource_choices
    value = await run_in_threadpool(resource_choices, course_store, student_id, node_id)
    return JSONResponse(value, headers={'Cache-Control': 'no-store'})


@router.get('/resource-position')
async def resource_position(student_id: str, resource_id: str, course_store=Depends(resolve_course_store)):
    from fastapi.responses import JSONResponse
    from .resource_position import ResourcePositions
    value = await run_in_threadpool(ResourcePositions(course_store).read, student_id, resource_id)
    return JSONResponse(value, headers={'Cache-Control': 'no-store'})


@router.get('/resource-document')
async def resource_document(student_id: str, resource_id: str, course_store=Depends(resolve_course_store)):
    from fastapi.responses import JSONResponse
    from learning_agent import document_api
    from .resource_document import ResourceDocument
    value = await run_in_threadpool(ResourceDocument(course_store, document_api.document_store).read, student_id, resource_id)
    return JSONResponse(value, headers={'Cache-Control': 'no-store'})


@router.get('/resource-document-page')
async def resource_document_page(student_id: str, resource_id: str, page: int, signature: str,
                                 mode: str = 'page', course_store=Depends(resolve_course_store)):
    from fastapi.responses import JSONResponse, Response
    from learning_agent import document_api
    from .resource_document import ResourceDocument
    value = await run_in_threadpool(ResourceDocument(course_store, document_api.document_store).page,
                                   student_id, resource_id, page, signature, mode)
    headers = {'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff'}
    return JSONResponse(value, headers=headers) if mode == 'text' else Response(value, media_type='image/png', headers=headers)


@router.post('/resource-document-position')
async def save_resource_document_position(request: Request, course_store=Depends(resolve_course_store)):
    from fastapi.responses import JSONResponse
    from learning_agent import document_api
    from .resource_document import ResourceDocument
    value = await run_in_threadpool(ResourceDocument(course_store, document_api.document_store).save, await _body(request))
    return JSONResponse(value, headers={'Cache-Control': 'no-store'})


@router.post('/resource-position')
async def save_resource_position(request: Request, course_store=Depends(resolve_course_store)):
    from .resource_position import ResourcePositions
    return await run_in_threadpool(ResourcePositions(course_store).save, await _body(request))


@router.post("/flow")
async def teaching_flow(request: Request, course_store=Depends(resolve_course_store)):
    from .teaching_flow import TeachingFlow
    return await run_in_threadpool(TeachingFlow(course_store).command, await _body(request))


@router.post("/plan")
async def learning_plan(request: Request, course_store=Depends(resolve_course_store)):
    from .learning_plan import LearningPlans, PlanProposal, plan_context, generate_plan
    from .teaching_jobs import durable_generation
    body = await _body(request)
    student = safe_id(body.get("student_id"), "学习编号")
    ident = safe_id(body.get("plan_request_id"), "规划触发编号")
    expected = _integer(body.get("expected_version"), "预期版本")
    version = _integer(body.get("course_version"), "课程版本", 1)
    body["request_id"] = f"plan-{ident}-v{expected}"
    service = LearningPlans(course_store)
    def prepare():
        graph = course_store._require_graph()
        learner = course_store.load_learner(student, graph)
        workspace = learner.get("workspace", {})
        previous = next((item for item in workspace.get("learning_plans", []) if item["id"] == body["request_id"]), None)
        if previous:
            if previous["course_version"] != version:
                raise CourseGraphError("相同规划请求不能用于不同课程版本。", 409)
            return None, previous
        course_store._expected(learner, expected)
        flow = workspace.get("teaching_flow", {})
        if not flow.get("enabled"):
            raise CourseGraphError("自动规划已暂停，请调整目标后再开始。", 409)
        pending = flow.get("plan_request")
        if graph["version"] != version or not pending or pending["id"] != ident or pending["course_version"] != version:
            raise CourseGraphError("目标或课程版本已更新，请重新查看学习起点。", 409)
        return plan_context(graph, learner, pending), None
    context, previous = await run_in_threadpool(prepare)
    if previous:
        return {"plan": previous, "state": await run_in_threadpool(service.view, student)}
    proposal, metadata = await durable_generation(course_store, body, context,
        lambda: generate_plan(context, configured_api()), result_type=PlanProposal)
    state = await run_in_threadpool(service.save_proposal, body, proposal, metadata, context)
    return {"plan": next(item for item in state["workspace"]["learning_plans"] if item["id"] == body["request_id"]), "state": state}


@router.post("/plan/apply")
async def apply_learning_plan(request: Request, course_store=Depends(resolve_course_store)):
    from .learning_plan import LearningPlans
    return await run_in_threadpool(LearningPlans(course_store).accept, await _body(request))


@router.get("/jobs/{request_id}")
async def teaching_job(request_id: str, student_id: str, course_store=Depends(resolve_course_store)):
    from .teaching_jobs import TeachingJobs
    from fastapi.responses import JSONResponse
    state = await run_in_threadpool(TeachingJobs(course_store).status, student_id, request_id)
    return JSONResponse(state, headers={"Cache-Control": "no-store"})


@router.get('/source-page-image')
async def source_image(student_id: str, material_id: str, source_id: str, course_store=Depends(resolve_course_store)):
    from fastapi.responses import Response
    from learning_agent import document_api
    from .source_preview import source_page_image
    content = await run_in_threadpool(source_page_image, course_store, document_api.document_store, student_id, material_id, source_id)
    return Response(content, media_type='image/png', headers={'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff'})


@router.get('/source-position')
async def source_position(student_id: str, material_id: str, source_id: str, course_store=Depends(resolve_course_store)):
    from fastapi.responses import JSONResponse
    from learning_agent import document_api
    from .source_reading import SourceReading
    value = await run_in_threadpool(SourceReading(course_store, document_api.document_store).read, student_id, material_id, source_id)
    return JSONResponse(value, headers={'Cache-Control': 'no-store'})


@router.post('/source-position')
async def save_source_position(request: Request, course_store=Depends(resolve_course_store)):
    from learning_agent import document_api
    from .source_reading import SourceReading
    return await run_in_threadpool(SourceReading(course_store, document_api.document_store).save, await _body(request))


@router.post('/job-recovery')
async def recover_job(request: Request, course_store=Depends(resolve_course_store)):
    from .teaching_jobs import TeachingJobs
    principal = getattr(request.state, 'identity', None)
    if not principal or principal['role'] != 'admin':
        raise CourseGraphError('任务恢复需要受保护的管理身份。', 403)
    return await run_in_threadpool(TeachingJobs(course_store).recover, principal['student'], await _body(request))


@router.get("/export/pdf")
async def export_pdf(student_id: str, kind: str, artifact_id: str, course_store=Depends(resolve_course_store)):
    from fastapi.responses import Response
    from .personal_export import saved_snapshot, render_pdf
    record = await run_in_threadpool(saved_snapshot, course_store, student_id, kind, artifact_id)
    content = await render_pdf(kind, record)
    return Response(content, media_type="application/pdf", headers={
        "Content-Disposition": f'attachment; filename="{kind}-{artifact_id}.pdf"',
        "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"})


@router.get('/textbook')
def textbook(student_id: str, report_id: str, course_store=Depends(resolve_course_store)):
    from fastapi.responses import JSONResponse
    from .personal_export import saved_snapshot
    return JSONResponse(saved_snapshot(course_store, student_id, 'textbook', report_id),
                        headers={'Cache-Control': 'no-store'})
      

@router.get("/export/word")
async def export_word(student_id: str, kind: str, artifact_id: str, course_store=Depends(resolve_course_store)):
    from fastapi.responses import Response
    from .personal_export import saved_snapshot
    from .word_export import render_word
    record = await run_in_threadpool(saved_snapshot, course_store, student_id, kind, artifact_id)
    content = await render_word(kind, record)
    return Response(content, media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document", headers={
        "Content-Disposition": f'attachment; filename="{kind}-{artifact_id}.docx"',
        "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"})


@router.post("/report")
async def stage_report(request: Request, course_store=Depends(resolve_course_store)):
    from .reports import StageReports
    return await run_in_threadpool(StageReports(course_store).save, await _body(request))


@router.get("/archive")
def archive(student_id: str):
    from learning_agent import api
    from .archive import learning_archive
    return learning_archive(api.store, student_id)


@router.get("/source-preview")
def preview_source(student_id: str, material_id: str, source_id: str, course_store=Depends(resolve_course_store)):
    from learning_agent.document_api import document_store
    from .source_preview import source_preview
    return source_preview(course_store, document_store, student_id, material_id, source_id)


@router.post("/notes")
async def save_note(request: Request, course_store=Depends(resolve_course_store)):
    from .notebook import Notebook
    return await run_in_threadpool(Notebook(course_store).save, await _body(request))


@router.post("/assessment/start")
async def assessment_start(request: Request, course_store=Depends(resolve_course_store)):
    return await run_in_threadpool(AssessmentService(course_store).start, await _body(request))


@router.post("/assessment/submit")
async def assessment_submit(request: Request, course_store=Depends(resolve_course_store)):
    # Commit the raw answer before making a potentially failing model request.
    return await run_in_threadpool(AssessmentService(course_store).submit, await _body(request))


@router.post("/assessment/evaluate")
async def assessment_evaluate(request: Request, course_store=Depends(resolve_course_store)):
    body = await _body(request)
    student = safe_id(body.get("student_id"), "学习编号")
    safe_id(body.get("request_id"), "请求编号")
    ident = safe_id(body.get("assessment_id"), "评价编号")
    expected = _integer(body.get("expected_version"), "预期版本")
    version = _integer(body.get("course_version"), "课程版本", 1)
    service = AssessmentService(course_store)
    record, current_course, current_version = await run_in_threadpool(service.assessment_snapshot, student, ident)
    if version != current_course:
        raise CourseGraphError("课程版本已变化，请重新载入。", 409)
    if record["status"] == "assessed":
        return await run_in_threadpool(service.view, student)
    if expected != current_version:
        raise CourseGraphError("学习记录已变化，原始作答仍保留，请重新载入后评价。", 409)
    if record.get("answer_key"):
        proposal, metadata = await evaluate_answer(record, None)
    else:
        from .teaching_jobs import durable_generation
        from .tutor import AssessmentProposal, assess_evidence

        async def generate_assessment():
            result, metadata = await evaluate_answer(record, configured_api())
            # Reject invalid evidence before caching, so an explicit retry can
            # obtain a corrected evaluation instead of reusing a bad result.
            assess_evidence(result, rubric=record["rubric"], answer=record["answer"],
                            assistance_level=record["prompt_level"], exposed=record["exposed"], independent_task=True)
            return result, metadata

        # Different tabs evaluating the same saved answer share the paid call.
        job_body = body | {"request_id": f"assessment-{ident}-v{expected}"}
        proposal, metadata = await durable_generation(course_store, job_body,
            {"operation": "assessment", "record": record}, generate_assessment, result_type=AssessmentProposal)
    return await run_in_threadpool(service.save_result, body, proposal, metadata)


@router.get('/activation-status')
async def activation_status(course_store=Depends(resolve_course_store)):
    from fastapi.responses import JSONResponse
    from learning_agent.document_api import document_store
    from .knowledge_activation import activation_context, activation_task
    from .teaching_jobs import TeachingJobs
    if getattr(course_store, 'is_demo', False):
        raise CourseGraphError('验收演示课程不需要重新生效。', 409)
    snapshot = await run_in_threadpool(course_store.load_graph, 'draft')
    context = await run_in_threadpool(activation_context, snapshot, document_store)
    job, _ = activation_task(snapshot, context)
    try:
        status = await run_in_threadpool(TeachingJobs(course_store).status, job['student_id'], job['request_id'])
    except CourseGraphError as error:
        if error.status_code != 404:
            raise
        status = {'status': 'not_started', 'attempts': 0, 'retry_limit': 3, 'retry_remaining': 3}
    published = await run_in_threadpool(course_store.load_graph)
    return JSONResponse(status | {'job_id': job['request_id'], 'job_owner': job['student_id'], 'course_version': snapshot['version'],
                                 'course_title': snapshot['title'], 'published_version': published['version'] if published else None}, headers={'Cache-Control': 'no-store'})


@router.post("/activate")
async def activate(request: Request, course_store=Depends(resolve_course_store)):
    from learning_agent.document_api import document_store
    from .knowledge_activation import activation_context, audit_knowledge, activate_snapshot, validate_audit, KnowledgeAudit, activation_task
    from .teaching_jobs import durable_generation
    body = await _body(request)
    version = _integer(body.get("expected_version"), "课程草稿版本", 1)
    if getattr(course_store, "is_demo", False):
        raise CourseGraphError("验收演示课程固定不变，不能改为正式课程。", 409)
    snapshot = await run_in_threadpool(course_store.load_graph, "draft")
    if snapshot["version"] != version:
        raise CourseGraphError("课程草稿版本已变化。", 409)
    context = await run_in_threadpool(activation_context, snapshot, document_store)
    job, job_context = activation_task(snapshot, context)
    async def generate():
        result, metadata = await audit_knowledge(context, configured_api())
        validate_audit(result, context)
        return result, metadata
    audit, metadata = await durable_generation(course_store, job, job_context, generate, result_type=KnowledgeAudit)
    fresh_context = await run_in_threadpool(activation_context, snapshot, document_store)
    if fresh_context != context:
        raise CourseGraphError('核验期间来源正文已变化，请重新核验；原可用版本未改变。', 409)
    return await run_in_threadpool(activate_snapshot, course_store, snapshot, context, audit, metadata)


@router.post("/reply")
@router.post("/advance")
async def reply(request: Request, course_store=Depends(resolve_course_store)):
    body = await _body(request)
    intent = "advance" if request.url.path.endswith("/advance") else "reply"
    if intent == "advance":
        body["message"] = "请根据我的目标、当前学习证据和未完成活动，安排下一步学习。"
    safe_id(body.get("student_id"), "学习编号")
    safe_id(body.get("request_id"), "请求编号")
    _integer(body.get("expected_version"), "预期版本")
    _integer(body.get("course_version"), "课程版本", 1)
    if "trigger_id" in body:
        if intent != "advance":
            raise CourseGraphError("教学触发只用于下一步安排。", 400)
        trigger = safe_id(body["trigger_id"], "教学触发编号")
        body["request_id"] = f"flow-{trigger}-v{body['expected_version']}"
    message = _text(body.get("message"), "学习问题", 4000)
    node_id = _text(body.get("node_id"), "知识点", 120)
    lab_session = safe_id(body["lab_session_id"], "实验轮次") if body.get("lab_session_id") else None
    workspace = LearningWorkspace(course_store)

    def prepare():
        graph = course_store.load_graph()
        if graph is None:
            raise CourseGraphError("课程知识尚未可用。", 409)
        learner = course_store.load_learner(body.get("student_id"), graph)
        previous = next((t for t in learner.get("workspace", {}).get("tutor_turns", []) if t["request_id"] == body.get("request_id")), None)
        if previous:
            if previous.get("intent", "reply") != intent or previous["message"] != message or previous["node_id"] != node_id or previous["course_version"] != body.get("course_version") or previous.get("lab_session_id") != lab_session:
                raise CourseGraphError("相同请求编号不能用于不同问题。", 409)
            return None, previous
        course_store._expected(learner, body.get("expected_version"))
        if graph["version"] != body.get("course_version"):
            raise CourseGraphError("课程版本已变化，请保留问题并重新载入。", 409)
        trigger = None
        if body.get("trigger_id"):
            from .teaching_flow import validate_trigger
            trigger = validate_trigger(learner.get("workspace", {}), graph, body)
        from learning_agent.document_api import document_store
        from .learning_plan import plan_focus
        focus = plan_focus(graph, learner, node_id, trigger)
        context = teaching_context(graph, learner, focus, message, document_store)
        context["intent"] = intent
        if lab_session:
            from .lab_context import validate_lab_request
            validate_lab_request(context, lab_session)
            task = context["lab"]["active"]["task"]
            if task and task["nodes"]:
                context = teaching_context(graph, learner, task["nodes"][0], message, document_store)
                context["intent"] = intent
            context["lab_help"] = True
        if trigger:
            context["trigger"] = copy.deepcopy(trigger)
        return context, None

    context, previous = await run_in_threadpool(prepare)
    if previous:
        return {"turn": previous, "state": await run_in_threadpool(workspace.view, body["student_id"])}
    from .teaching_jobs import durable_generation
    from .tutor import check_resource_recommendations
    async def generate_with_resources():
        generated, details = await generate_teaching(context, configured_api())
        check_resource_recommendations(generated, context)
        return generated, details
    proposal, metadata = await durable_generation(course_store, body, context,
                                                 generate_with_resources)
    check_resource_recommendations(proposal, context)
    turn = {"request_id": body.get("request_id"), "node_id": node_id, "message": message, "intent": intent,
            "lab_session_id": lab_session,
            "course_version": body["course_version"], "proposal": proposal.model_dump(), "generation": metadata}

    def commit():
        def apply(graph, learner, state):
            if body.get("trigger_id"):
                from .teaching_flow import validate_trigger
                validate_trigger(state, graph, body)
            if not any(node["id"] == node_id for node in graph["nodes"]):
                raise CourseGraphError("知识点已变化，请重新载入。", 409)
            record = copy.deepcopy(turn)
            if lab_session:
                from .lab_context import record_lab_help
                record_lab_help(state, lab_session, record["request_id"])
            record["created_at"] = course_store._stamp()
            if body.get("trigger_id"):
                record["trigger"] = copy.deepcopy(context["trigger"])
            record["source_refs"] = [citation.model_dump() for block in proposal.blocks for citation in block.citations]
            cited = {item["source_id"] for item in record["source_refs"]}
            record["source_catalog"] = [{key: value for key, value in source.items() if key != "text"}
                for source in context["sources"] if source["id"] in cited]
            recommended = {item.resource_id for item in proposal.recommended_resources}
            record['resource_catalog'] = [copy.deepcopy(item) for item in context['resources'] if item['id'] in recommended]
            state.setdefault("tutor_turns", []).append(record)
            if intent == "advance" and proposal.action == "lab":
                from .ml_lab import MLLab
                MLLab.binding(graph)
                record["activity"] = {"type": "lab", "node_id": proposal.target_node_id,
                    "notice": "进入实验后选择情境或继续原轮次；实验结果与解释证据分别记录。"}
            if intent == "advance" and proposal.action in {"probe", "practice"}:
                target = course_store._node(graph, proposal.target_node_id)
                if target.get("check_task", {}).get("rubric"):
                    task = AssessmentService(course_store).create_task(graph, state, target["id"], resume=True)
                    if "initiating_turn" not in task:
                        task["initiating_turn"] = record["request_id"]
                        # A lesson shown alongside a new check is assistance; a
                        # bare task assignment is not a hint or learner evidence.
                        task["prompt_level"] = max(task["prompt_level"], 1 if proposal.blocks else 0)
                    record["activity"] = {"type": "assessment", "id": task["id"], "node_id": target["id"], "status": task["status"]}
                else:
                    record["activity"] = {"type": "discussion", "node_id": target["id"],
                        "notice": "当前知识点尚无预设评价任务，本次追问用于学习讨论，不据此认定掌握。"}
            workspace._event(state, "tutor_replied", node_id=node_id, request_id=body["request_id"])
            if body.get("trigger_id"):
                state["teaching_flow"].update(pending=None, current_turn_id=record["request_id"])
        # Generation happens outside the lock; revision checks prevent stale writes.
        state = workspace._mutate(body, "tutor_reply", apply)
        saved = next(t for t in state["workspace"]["tutor_turns"] if t["request_id"] == body["request_id"])
        return {"turn": saved, "state": state}

    return await run_in_threadpool(commit)
