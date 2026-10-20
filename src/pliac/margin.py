"""Course-owned LearnMargin handouts. Reuse existing material; no second upload system."""
import asyncio
import hashlib
import json
import re
from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.responses import FileResponse
from pydantic import ValidationError
from learning_agent.api import ChineseRoute, _body, resolve_course_store
from learning_agent.course_graph import CourseGraphError, ROOT, safe_id, _text
from learning_agent import document_api
from learnmargin.config import default_api, resolve_api
from learnmargin.models import APIConfig, Document, SourceUnit, GenerateRequest, Scope, Lesson, LessonPlan, LessonSection
from learnmargin.pipeline import generate_lesson, validate_material, make_units
from learnmargin.provider import Provider
from learnmargin.rendering import render_lesson
from learnmargin.storage import Store, atomic_json, new_id, now
from .margin_graph import generate_map
from . import learning_scope, handout_practice

router = APIRouter(prefix="/api/handouts", route_class=ChineseRoute)
TASKS = {}
ENGINE = "LearnMargin 63dba8f + model controls 49f1f5e"
ARTIFACTS = {"lesson.json":"application/json", "knowledge-map.json":"application/json",
             "lesson.html":"text/html", "lesson.pdf":"application/pdf", "validation.json":"application/json"}


def storage(course):
    return Store(course.ensure_handouts())


def graph_for(course):
    graph = course.load_graph()
    return (graph, graph.get("delivery_mode", "published")) if graph else (course.load_graph("draft"), "draft")


def materials(graph, chapter_id="", documents=None, scope=None):
    """Snapshot complete cached source units explicitly linked to this course scope."""
    documents = documents or document_api.document_store
    if chapter_id and chapter_id not in {c["id"] for c in graph["chapters"]}:
        raise CourseGraphError("课程章节不存在。", 404)
    nodes = [n for n in graph["nodes"] if not chapter_id or n["chapter_id"] == chapter_id]
    if scope:
        nodes = [n for n in nodes if n["id"] in scope["node_ids"]]
    pages, authored = {}, []
    for entry in (scope or {}).get("source_ranges", []):
        start, end = entry.get("start_page"), entry.get("end_page")
        if type(start) is not int or type(end) is not int or not 1 <= start <= end or end-start > 2000:
            raise CourseGraphError("章节资料页码范围无效。", 409)
        pages.setdefault(entry["document_id"], set()).update(range(start, end+1))
    bounded_documents = set(pages)
    for node in nodes:
        ident = node.get("document_id")
        evidence = node.get("document_evidence", [])
        if ident and evidence:
            selected = pages.setdefault(ident, set())
            if ident not in bounded_documents:
                selected.update(e["page"] for e in evidence if type(e.get("page")) is int)
        else:
            content = [node["title"], node.get("description", "")]
            content += [p.get("heading", "")+"\n"+p.get("text", "") for p in node.get("lesson_content", [])]
            content += node.get("objectives", [])
            content += [node.get("misconception", "")]
            if any(part.strip() for part in content[1:]):
                authored.append(SourceUnit(index=len(authored)+1, label=node["title"], text="\n\n".join(p for p in content if p)))
    result, origins = [], {}
    for ident, indices in sorted(pages.items()):
        job = documents.status(ident)
        units = []
        for index in sorted(indices):
            data = documents.page(ident, index)
            text = data.get("text", "")
            if not text.strip():
                raise CourseGraphError(f"《{job['title']}》第 {index} 个资料单元尚无可读文本，请先完成识读。", 409)
            label = ("第 " + str(index) + " 页") if job.get("page_kind") == "pdf" else ("原文段 " + str(index))
            units.append(SourceUnit(index=index, label=label, text=text))
            if not job.get("archived_text"):
                origins[f"{ident}:{index}"] = {"url": f"/api/documents/{ident}/source" + (f"#page={index}" if job.get("page_kind") == "pdf" else ""), "kind": "uploaded_document"}
        if units:
            result.append(Document(id=ident, name=job["title"], kind="course_material", unit_label="资料单元", units=units))
    if authored:
        ident = hashlib.sha256((graph["id"]+":authored").encode()).hexdigest()[:32]
        result.append(Document(id=ident, name=graph["title"]+" · 课程教学资料", kind="course_material", unit_label="知识单元", units=authored))
    if not result:
        raise CourseGraphError("课程还没有可用于讲义的资料，请先在课程中添加资料。", 409)
    return result, origins


def configured_api():
    path = ROOT / "config/models.json"
    try:
        if path.exists():
            from learning_agent.llm import load_model_config
            values = load_model_config(path)
            # Only forward API fields; shared config may contain other module settings.
            config = resolve_api(APIConfig(**{key: values[key] for key in APIConfig.model_fields if key in values}))
        else:
            config = resolve_api(default_api())
    except ValidationError:
        # Pydantic errors include input values: never expose credentials or raw config.
        raise CourseGraphError("课程模型配置无效。请检查协议、思考档位和请求超时（10～600 秒）等设置。", 503) from None
    except ValueError as exc:
        raise CourseGraphError(str(exc), 503) from None
    if not config.api_key.get_secret_value():
        raise CourseGraphError("课程模型尚未配置。", 503)
    return config


def read_job(store, job_id):
    try:
        return store.job(job_id)
    except (ValueError, FileNotFoundError) as exc:
        raise CourseGraphError("这份讲义不存在或不属于当前课程。", 404) from exc


def student_job(store, job_id, student_id=""):
    job = read_job(store, job_id)
    if job.get("student_id") and job["student_id"] != student_id:
        raise CourseGraphError("这份学习片段属于另一份学习记录。", 404)
    return job


def job_path(store, job_id, name):
    path = store.directory("jobs", job_id) / name
    if path.resolve() != path or not path.is_file():
        raise CourseGraphError("讲义文件不存在。", 404)
    return path


def readable_guidance(lesson):
    """Localize schema references only in teaching prompts, preserving source/technical text."""
    names = {"explanation":"正文讲解", "worked_example":"完整例题", "practice":"练习", "source_notes":"来源说明"}
    for section in lesson.sections:
        for prompt in section.study_prompts:
            for key in ("when", "task", "check", "answer"):
                value = getattr(prompt, key)
                if value:
                    for original, label in names.items():
                        value = re.sub(r"(?<![A-Za-z_])"+original+r"(?![A-Za-z_])", label, value)
                    setattr(prompt, key, value)
    return lesson


async def run_job(store, job, request, docs, origins):
    output = store.directory("jobs", job["id"])
    def progress(stage, amount):
        job.update(stage=stage, progress=amount)
        store.save_job(job)
    try:
        job["status"] = "running"
        job.pop("failed_stage", None)
        job["error"] = None
        progress("读取课程资料", 3)
        for doc in docs:
            store.save_document(doc)
        atomic_json(output / "materials.json", {"documents":[doc.model_dump() for doc in docs], "origins":origins})
        async with Provider(request.api) as provider:
            checkpoint = output / "lesson.json"
            lesson = None
            if checkpoint.is_file():
                lesson = Lesson.model_validate_json(checkpoint.read_text(encoding="utf-8"))
                if job.get("scope") and not any(section.practice for section in lesson.sections):
                    lesson = None
            if lesson is None:
                lesson = await generate_lesson(request, docs, store, output, provider, progress)
            lesson = readable_guidance(lesson)
            if job.get("scope") and not any(section.practice for section in lesson.sections):
                raise ValueError("这次讲义没有生成范围内练习，请重新生成完整学习单元。")
            atomic_json(checkpoint, lesson.model_dump())
            progress("生成知识概念及关系", 83)
            concept_map = await generate_map(lesson, provider)
            usage = provider.usage
        atomic_json(output / "knowledge-map.json", concept_map)
        progress("排版详细讲义", 88)
        rendered = await render_lesson(lesson, output, layout="a4")
        atomic_json(output / "generation.json", {"engine":ENGINE, "course_id":job["course_id"], "course_version":job["course_version"], "scope":job.get("scope"), "api_usage":usage})
        job.update(status="completed", stage="图谱、讲义与习题已生成", progress=100, title=lesson.title, page_count=rendered["page_count"])
    except asyncio.CancelledError:
        job.update(status="cancelled", stage="已取消")
        raise
    except Exception as exc:
        error = exc
        while isinstance(error, BaseExceptionGroup):
            error = error.exceptions[0]
        detail = str(error)[:700] if isinstance(error, (ValueError, RuntimeError)) else "讲义生成未完成，请重试。"
        failed_stage = job.get("stage", "生成讲义")
        job.update(status="failed", stage="生成失败", failed_stage=failed_stage, error=f"{failed_stage}：{detail}")
    finally:
        store.save_job(job)


async def close_jobs():
    tasks = list(TASKS.values())
    for task in tasks:
        task.cancel()
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)


@router.get("")
def listing(course_store=Depends(resolve_course_store), chapter_id: str = "", node_id: str = "",
            source_job_id: str = "", concept_id: str = "", section_id: str = "", student_id: str = "", job_id: str = "", mode: str = ""):
    graph, view = graph_for(course_store)
    store = storage(course_store)
    if student_id:
        safe_id(student_id, "学习编号")
    if source_job_id:
        student_job(store, source_job_id, student_id)
    selection = dict(chapter_id=chapter_id, node_id=node_id, source_job_id=source_job_id, concept_id=concept_id, section_id=section_id)
    chosen = student_job(store, job_id, student_id) if job_id else None
    if chosen and not any(selection.values()):
        selection = learning_scope.job_scope(chosen)
    scope = learning_scope.resolve(graph, selection, store)
    section_nodes = learning_scope.resolve(graph, dict(chapter_id=scope["chapter_id"], section_id=section_id), store)["node_ids"] if section_id else None
    owner_filter = "" if mode == "author" else student_id
    jobs = [job for job in store.jobs() if job.get("student_id", "") == owner_filter]
    if chosen and not chosen.get("student_id") and student_id:
        jobs = sorted([chosen, *jobs], key=lambda item: item.get("created_at", ""), reverse=True)
    for job in jobs:
        if job["status"] in {"running", "queued"} and job["id"] not in TASKS:
            job.update(status="failed", stage="任务已中断", error="服务已重启，请重新生成。")
            store.save_job(job)
    return {"course_id":graph["id"], "title":graph["title"], "version":graph["version"], "source_view":view,
            "chapters":graph["chapters"], "jobs":jobs, "scope":scope,
            "scope_jobs":[j for j in jobs if learning_scope.key(learning_scope.job_scope(j)) == scope["key"]],
            "nodes":[{"id":n["id"], "title":n["title"], "chapter_id":n["chapter_id"]} for n in graph["nodes"]
                     if (not scope["chapter_id"] or n["chapter_id"] == scope["chapter_id"])
                     and (section_nodes is None or n["id"] in section_nodes)],
            "activities":graph.get("activities", []),
            "source_content":[{"id":n["id"], "title":n["title"], "description":n.get("description", ""),
                               "lesson_content":n.get("lesson_content", [])}
                              for n in graph["nodes"] if n["id"] in scope["node_ids"]][:12],
            "capabilities":{"generate_handouts":True},
            "snapshot_summary":course_store.source_summary() if hasattr(course_store,"source_summary") else None}


@router.post("")
async def generate(request: Request, course_store=Depends(resolve_course_store)):
    body = await _body(request)
    return start_generation(course_store, body)


def compact_profile_notes(context, budget):
    """Keep complete structured data inside the existing learner-notes contract."""
    ordered = {key: context[key] for key in
               ("current_step", "current_calibration", "conversation_preferences", "goals", "background", "interests", "route")
               if key in context}
    def trim(value, limit):
        if isinstance(value, str):
            return value[:limit]
        if isinstance(value, dict):
            return {key: trim(item, limit) for key, item in list(value.items())[:6]}
        if isinstance(value, list):
            return [trim(item, limit) for item in value[:3]]
        return value
    for limit in (160, 100, 60, 30):
        reduced = trim(ordered, limit)
        serialized = json.dumps(reduced, ensure_ascii=False, separators=(",", ":"))
        if len(serialized) <= budget:
            return serialized
    while len(serialized) > budget and reduced:
        reduced.pop(next(reversed(reduced)))
        serialized = json.dumps(reduced, ensure_ascii=False, separators=(",", ":"))
    return serialized


def start_generation(course_store, body, personalization=None):
    """Synchronous admission makes simultaneous prepare requests idempotent."""
    graph, view = graph_for(course_store)
    store = storage(course_store)
    selection = body.get("scope", body)
    if not isinstance(selection, dict):
        raise CourseGraphError("学习范围无效。")
    scope = learning_scope.resolve(graph, selection, store)
    chapter = scope["chapter_id"]
    for job in store.jobs():
        same_owner = job.get("student_id", "") == (personalization or {}).get("student_id", "")
        same_profile = job.get("profile_fingerprint") == (personalization or {}).get("profile_fingerprint")
        if same_owner and same_profile and job["id"] in TASKS and learning_scope.key(learning_scope.job_scope(job)) == scope["key"] and job["course_version"] == graph["version"]:
            receipt = (personalization or {}).get("prepare_request_id")
            if receipt:
                job["prepare_request_ids"] = list(dict.fromkeys([*job.get("prepare_request_ids", []), receipt]))[-20:]
                store.save_job(job)
            return job
    if len(TASKS) >= 2:
        raise CourseGraphError("已有讲义正在生成，请完成后重试。", 429)
    docs, origins = (learning_scope.concept_materials(scope, store) if scope["kind"] == "concept" else
                     materials(graph, chapter, course_store.material_documents(document_api.document_store), scope))
    api = configured_api()
    try:
        validate_material(make_units(docs), store, api.vision)
    except ValueError as exc:
        raise CourseGraphError(str(exc) + " 请在课程范围中选择具体章节。", 400) from exc
    if len(docs) > 8:
        raise CourseGraphError("当前范围关联的资料超过 8 份，请选择具体课程章节。", 400)
    notes = (f"本次独立学习单元：{scope['title']}。只讲本范围内的内容，必要前置知识单列说明，不扩展为整门课程。"
            "以课程已有资料为依据，包含学习目标、前置说明、详细讲解、完整例题、范围内习题、提示、参考答案和复习建议。"
            "知识点虽小也要形成完整学习单元，至少提供一道可作答习题。休息由内容负荷决定，用户自主选择，不使用计时限制。"
            + ("当前知识点的原图谱定义：" + scope["focus"][:300] if scope["focus"] else ""))
    if personalization:
        mode = "期末复习：凝练核心概念、易混点和迁移题，保留必要推理。" if personalization["learning_mode"] == "exam_review" else "初次学习：解释必要基础，以完整例题连接概念和独立尝试。"
        notes += "\n学习场景：" + mode
        notes += "\n学习者本次需要：" + personalization["feedback"][:400]
        notes += "\n服务器学习画像与路线策略（作为教学依据，推断和偏好不等同于已掌握）："
        notes += compact_profile_notes(personalization["profile_context"], max(2, 2000-len(notes)))
    request_data = GenerateRequest(document_ids=[d.id for d in docs], api=api,
        scope=Scope(mode="topics", topics=scope["title"]) if scope["kind"] in {"node", "concept"} else Scope(),
        learner_notes=notes[:2000], language="简体中文")
    previous = next((j for j in store.jobs() if learning_scope.key(learning_scope.job_scope(j)) == scope["key"]
                     and j["course_version"] == graph["version"] and j["status"] == "failed"
                     and not j.get("student_id")), None) if not personalization else None
    if previous:
        output = store.directory("jobs", previous["id"])
        snapshot = output / "materials.json"
        if snapshot.is_file():
            saved = json.loads(snapshot.read_text(encoding="utf-8"))
            if saved["documents"] == [d.model_dump() for d in docs]:
                checkpoint = output / "lesson.json"
                # Recover completed upstream section checkpoints from an interrupted graph stage.
                if not checkpoint.exists() and (output / "plan.json").exists():
                    plan = LessonPlan.model_validate_json((output / "plan.json").read_text(encoding="utf-8"))
                    paths = [output / f"section-{i+1}.json" for i in range(len(plan.sections))]
                    if all(p.is_file() for p in paths):
                        selection = json.loads((output / "selection.json").read_text(encoding="utf-8"))
                        lesson = Lesson(title=plan.title, subtitle=plan.subtitle, text=plan.text, overview=plan.overview,
                            sections=[LessonSection.model_validate_json(p.read_text(encoding="utf-8")) for p in paths],
                            review_plan=plan.review_plan, method_chapters=plan.method_chapters,
                            sources=selection["sources"], scope_note=selection["scope_note"])
                        atomic_json(checkpoint, lesson.model_dump())
                if checkpoint.exists():
                    previous.update(status="queued", stage="继续生成知识图谱", progress=82, error=None, scope=scope)
                    store.save_job(previous)
                    task = asyncio.create_task(run_job(store, previous, request_data, docs, origins))
                    TASKS[previous["id"]] = task
                    task.add_done_callback(lambda _: TASKS.pop(previous["id"], None))
                    return previous
    job = dict(id=new_id(), status="queued", stage="等待生成", progress=0, created_at=now(), course_id=graph["id"],
               course_version=graph["version"], source_view=view, chapter_id=chapter, scope=scope, title=scope["title"], error=None)
    if personalization:
        job.update(personalization)
    store.save_job(job)
    task = asyncio.create_task(run_job(store, job, request_data, docs, origins))
    TASKS[job["id"]] = task
    task.add_done_callback(lambda _: TASKS.pop(job["id"], None))
    return job


def personalization_context(course, scope, owner=""):
    learner = course._read_learner(scope["student_id"])
    profile = learner.get("profile", {})
    context = {"background": str(profile.get("background", ""))[:500],
               "goals": str(profile.get("goals", ""))[:500],
               "interests": [str(value)[:80] for value in profile.get("interests", [])[:8]]}
    journey = learner.get("workspace", {}).get("journey", {})
    active = journey.get("active") or {}
    route = active.get("route") or journey.get("route", {})
    if isinstance(route, dict):
        context["route"] = {key: route[key] for key in ("summary", "goal", "strategy", "learning_mode", "teaching_approach") if key in route}
        calibration = (active.get("initial_profile") or {}).get("calibration", route.get("calibration", []))
        if isinstance(calibration, list):
            current = next((entry for entry in calibration if isinstance(entry, dict) and entry.get("node_id") in scope["node_ids"]), None)
            if current:
                context["current_calibration"] = {key: current[key] for key in
                    ("node_id", "self_assessment", "signal", "label", "reason", "quote", "evidence_id") if key in current}
        for key in ("steps", "nodes"):
            if isinstance(route.get(key), list):
                current = next((entry for entry in route[key] if isinstance(entry, dict) and
                                entry.get("node_id", entry.get("id")) in scope["node_ids"]), None)
                if current:
                    context["current_step"] = {key: current[key] for key in
                        ("node_id", "title", "strategy", "reason", "mode", "support", "focus", "pace") if key in current}
                    break
    if owner:
        from .assistant import root as assistant_root
        from . import assistant_profile
        current = assistant_profile.load(assistant_root(owner))
        if current.get("enabled"):
            context["conversation_preferences"] = [
                {key: item.get(key, "") for key in ("category", "slot", "value", "basis")}
                for item in current.get("items", []) if item.get("active")][:6]
    return context


@router.post("/prepare")
async def prepare(request: Request, course_store=Depends(resolve_course_store)):
    body = await _body(request)
    student = safe_id(body.get("student_id"), "学习编号")
    graph, _ = graph_for(course_store)
    store = storage(course_store)
    selection = body.get("scope", body)
    if not isinstance(selection, dict):
        raise CourseGraphError("学习范围无效。")
    if body.get("job_id") and not any(selection.get(key) for key in learning_scope.FIELDS):
        selection = learning_scope.job_scope(student_job(store, body["job_id"], student))
    if selection.get("source_job_id"):
        student_job(store, selection["source_job_id"], student)
    scope = learning_scope.resolve(graph, selection, store)
    if scope["kind"] == "course":
        raise CourseGraphError("请从个性化路线中进入一个学习片段。", 400)
    jobs = [j for j in store.jobs() if j.get("student_id") == student and
            j.get("course_version") == graph["version"] and learning_scope.key(learning_scope.job_scope(j)) == scope["key"]]
    latest = jobs[0] if jobs else {}
    mode = body.get("learning_mode", latest.get("learning_mode", "initial"))
    if not isinstance(mode, str) or mode not in {"initial", "exam_review"}:
        raise CourseGraphError("请选择初次学习或期末复习。")
    feedback = _text(body.get("feedback", latest.get("feedback", "")), "学习需要", 600, False)
    owner = body.get("assistant_owner", "")
    if owner:
        safe_id(owner, "对话画像编号")
    regenerate = body.get("regenerate", False)
    if type(regenerate) is not bool:
        raise CourseGraphError("重新生成选项无效。")
    receipt = safe_id(body.get("request_id"), "请求编号") if regenerate else ""
    context = personalization_context(course_store, {**scope, "student_id": student}, owner)
    signature = hashlib.sha256(json.dumps({"context": context, "learning_mode": mode, "feedback": feedback},
                                          sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()
    # A failed task stays visible until the student requests regeneration or the
    # profile changes; returning to a page never creates a failure/retry loop.
    for job in jobs:
        if receipt and (job.get("prepare_request_id") == receipt or receipt in job.get("prepare_request_ids", [])):
            if job.get("learning_mode") != mode or job.get("feedback") != feedback:
                raise CourseGraphError("同一请求编号对应的学习需要已变化，请重新提交。", 409)
            return job
        if not regenerate and job.get("profile_fingerprint") == signature:
            if job["status"] in {"running", "queued"} and job["id"] not in TASKS:
                job.update(status="failed", stage="任务已中断", error="服务已重启，可以重新生成学习片段。")
                store.save_job(job)
            return job
    return start_generation(course_store, {"scope": scope}, {
        "student_id": student, "profile_fingerprint": signature, "profile_context": context,
        "learning_mode": mode, "feedback": feedback, "prepare_request_id": receipt})


@router.get("/{job_id}/artifacts/{name}")
def artifact(job_id: str, name: str, course_store=Depends(resolve_course_store), student_id: str = ""):
    store = storage(course_store)
    if name not in ARTIFACTS or student_job(store, job_id, student_id)["status"] != "completed":
        raise CourseGraphError("讲义尚未生成完成。", 404)
    path = job_path(store, job_id, name)
    return FileResponse(path, media_type=ARTIFACTS[name], headers={"X-Content-Type-Options":"nosniff"})


@router.get("/{job_id}/practice")
def practice_view(job_id: str, student_id: str, course_store=Depends(resolve_course_store)):
    student_job(storage(course_store), job_id, student_id)
    return handout_practice.view(course_store, storage(course_store), job_id, student_id)


@router.post("/{job_id}/practice")
async def practice_write(job_id: str, request: Request, course_store=Depends(resolve_course_store)):
    from starlette.concurrency import run_in_threadpool
    payload = await _body(request)
    student_job(storage(course_store), job_id, payload.get("student_id", ""))
    return await run_in_threadpool(handout_practice.mutate, course_store, storage(course_store), job_id, payload)


@router.get("/{job_id}/sources/{document_id}/{index}")
def source(job_id: str, document_id: str, index: int, course_store=Depends(resolve_course_store), student_id: str = ""):
    store = storage(course_store)
    student_job(store, job_id, student_id)
    data = json.loads(job_path(store, job_id, "materials.json").read_text(encoding="utf-8"))
    for doc in data["documents"]:
        if doc["id"] == document_id:
            unit = next((u for u in doc["units"] if u["index"] == index), None)
            if unit:
                return {"document":doc["name"], **unit, "original":data["origins"].get(f"{document_id}:{index}")}
    raise CourseGraphError("该资料不属于这份讲义。", 404)


@router.post("/{job_id}/cancel")
async def cancel(job_id: str, course_store=Depends(resolve_course_store), student_id: str = ""):
    store = storage(course_store)
    job = student_job(store, job_id, student_id)
    task = TASKS.get(job_id)
    if task:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        job = read_job(store, job_id)
        if job["status"] in {"queued", "running"}:
            job.update(status="cancelled", stage="已取消")
            store.save_job(job)
    return job
