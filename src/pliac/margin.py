"""Course-owned LearnMargin handouts. Reuse existing material; no second upload system."""
import asyncio
import hashlib
import json
import re
from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.responses import FileResponse
from learning_agent.api import ChineseRoute, _body, resolve_course_store
from learning_agent.course_graph import CourseGraphError, ROOT
from learning_agent import document_api
from learnmargin.config import default_api, resolve_api
from learnmargin.models import APIConfig, Document, SourceUnit, GenerateRequest, Lesson, LessonPlan, LessonSection
from learnmargin.pipeline import generate_lesson, validate_material, make_units
from learnmargin.provider import Provider
from learnmargin.rendering import render_lesson
from learnmargin.storage import Store, atomic_json, new_id, now
from .margin_graph import generate_map

router = APIRouter(prefix="/api/handouts", route_class=ChineseRoute)
TASKS = {}
ARTIFACTS = {"lesson.json":"application/json", "knowledge-map.json":"application/json",
             "lesson.html":"text/html", "lesson.pdf":"application/pdf", "validation.json":"application/json"}


def storage(course):
    return Store(course.ensure_handouts())


def graph_for(course):
    graph = course.load_graph()
    return (graph, graph.get("delivery_mode", "published")) if graph else (course.load_graph("draft"), "draft")


def materials(graph, chapter_id="", documents=None):
    """Snapshot complete cached source units explicitly linked to this course scope."""
    documents = documents or document_api.document_store
    if chapter_id and chapter_id not in {c["id"] for c in graph["chapters"]}:
        raise CourseGraphError("课程章节不存在。", 404)
    nodes = [n for n in graph["nodes"] if not chapter_id or n["chapter_id"] == chapter_id]
    pages, authored = {}, []
    for node in nodes:
        ident = node.get("document_id")
        evidence = node.get("document_evidence", [])
        if ident and evidence:
            selected = pages.setdefault(ident, set())
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
    if path.exists():
        from learning_agent.llm import load_model_config
        config = load_model_config(path)
        return resolve_api(APIConfig(base_url=config["base_url"], model=config["model"], api_key=config["api_key"],
                                     protocol=config.get("protocol", "chat_completions")))
    config = resolve_api(default_api())
    if not config.api_key.get_secret_value():
        raise CourseGraphError("课程模型尚未配置。", 503)
    return config


def read_job(store, job_id):
    try:
        return store.job(job_id)
    except (ValueError, FileNotFoundError) as exc:
        raise CourseGraphError("这份讲义不存在或不属于当前课程。", 404) from exc


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
        progress("读取课程资料", 3)
        for doc in docs:
            store.save_document(doc)
        atomic_json(output / "materials.json", {"documents":[doc.model_dump() for doc in docs], "origins":origins})
        async with Provider(request.api) as provider:
            checkpoint = output / "lesson.json"
            if checkpoint.is_file():
                lesson = Lesson.model_validate_json(checkpoint.read_text(encoding="utf-8"))
            else:
                lesson = await generate_lesson(request, docs, store, output, provider, progress)
                atomic_json(checkpoint, lesson.model_dump())
            lesson = readable_guidance(lesson)
            atomic_json(checkpoint, lesson.model_dump())
            progress("生成知识概念及关系", 83)
            concept_map = await generate_map(lesson, provider)
            usage = provider.usage
        atomic_json(output / "knowledge-map.json", concept_map)
        progress("排版详细讲义", 88)
        rendered = await render_lesson(lesson, output, layout="a4")
        atomic_json(output / "generation.json", {"engine":"LearnMargin 63dba8f", "course_id":job["course_id"], "course_version":job["course_version"], "api_usage":usage})
        job.update(status="completed", stage="讲义与知识图谱已生成", progress=100, title=lesson.title, page_count=rendered["page_count"])
    except asyncio.CancelledError:
        job.update(status="cancelled", stage="已取消")
        raise
    except Exception as exc:
        error = exc
        while isinstance(error, BaseExceptionGroup):
            error = error.exceptions[0]
        detail = str(error)[:700] if isinstance(error, (ValueError, RuntimeError)) else "讲义生成未完成，请重试。"
        job.update(status="failed", stage="生成失败", error=detail)
    finally:
        store.save_job(job)


async def close_jobs():
    tasks = list(TASKS.values())
    for task in tasks:
        task.cancel()
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)


@router.get("")
def listing(course_store=Depends(resolve_course_store)):
    graph, view = graph_for(course_store)
    store = storage(course_store)
    jobs = store.jobs()
    for job in jobs:
        if job["status"] in {"running", "queued"} and job["id"] not in TASKS:
            job.update(status="failed", stage="任务已中断", error="服务已重启，请重新生成。")
            store.save_job(job)
    return {"course_id":graph["id"], "title":graph["title"], "version":graph["version"], "source_view":view,
            "chapters":graph["chapters"], "jobs":jobs,
            "capabilities":{"generate_handouts":True},
            "snapshot_summary":course_store.source_summary() if hasattr(course_store,"source_summary") else None}


@router.post("")
async def generate(request: Request, course_store=Depends(resolve_course_store)):
    body = await _body(request)
    graph, view = graph_for(course_store)
    chapter = body.get("chapter_id", "")
    if not isinstance(chapter, str):
        raise CourseGraphError("章节编号无效。")
    store = storage(course_store)
    for job in store.jobs():
        if job["id"] in TASKS and job.get("chapter_id") == chapter:
            return job
    if len(TASKS) >= 2:
        raise CourseGraphError("已有讲义正在生成，请完成后重试。", 429)
    docs, origins = materials(graph, chapter, course_store.material_documents(document_api.document_store))
    api = configured_api()
    try:
        validate_material(make_units(docs), store, api.vision)
    except ValueError as exc:
        raise CourseGraphError(str(exc) + " 请在课程范围中选择具体章节。", 400) from exc
    if len(docs) > 8:
        raise CourseGraphError("当前范围关联的资料超过 8 份，请选择具体课程章节。", 400)
    request_data = GenerateRequest(document_ids=[d.id for d in docs], api=api,
        learner_notes="以课程现有资料为依据，讲清概念含义、条件与推理，提供完整例题。休息由内容负荷决定，用户自主选择，不使用计时限制。", language="简体中文")
    previous = next((j for j in store.jobs() if j.get("chapter_id") == chapter and j["status"] == "failed"), None)
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
                    previous.update(status="queued", stage="继续生成知识图谱", progress=82, error=None)
                    store.save_job(previous)
                    task = asyncio.create_task(run_job(store, previous, request_data, docs, origins))
                    TASKS[previous["id"]] = task
                    task.add_done_callback(lambda _: TASKS.pop(previous["id"], None))
                    return previous
    job = dict(id=new_id(), status="queued", stage="等待生成", progress=0, created_at=now(), course_id=graph["id"],
               course_version=graph["version"], source_view=view, chapter_id=chapter, title=graph["title"], error=None)
    store.save_job(job)
    task = asyncio.create_task(run_job(store, job, request_data, docs, origins))
    TASKS[job["id"]] = task
    task.add_done_callback(lambda _: TASKS.pop(job["id"], None))
    return job


@router.get("/{job_id}/artifacts/{name}")
def artifact(job_id: str, name: str, course_store=Depends(resolve_course_store)):
    store = storage(course_store)
    if name not in ARTIFACTS or read_job(store, job_id)["status"] != "completed":
        raise CourseGraphError("讲义尚未生成完成。", 404)
    path = job_path(store, job_id, name)
    return FileResponse(path, media_type=ARTIFACTS[name], headers={"X-Content-Type-Options":"nosniff"})


@router.get("/{job_id}/sources/{document_id}/{index}")
def source(job_id: str, document_id: str, index: int, course_store=Depends(resolve_course_store)):
    store = storage(course_store)
    data = json.loads(job_path(store, job_id, "materials.json").read_text(encoding="utf-8"))
    for doc in data["documents"]:
        if doc["id"] == document_id:
            unit = next((u for u in doc["units"] if u["index"] == index), None)
            if unit:
                return {"document":doc["name"], **unit, "original":data["origins"].get(f"{document_id}:{index}")}
    raise CourseGraphError("该资料不属于这份讲义。", 404)


@router.post("/{job_id}/cancel")
async def cancel(job_id: str, course_store=Depends(resolve_course_store)):
    store = storage(course_store)
    job = read_job(store, job_id)
    task = TASKS.get(job_id)
    if task:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        job = read_job(store, job_id)
        if job["status"] in {"queued", "running"}:
            job.update(status="cancelled", stage="已取消")
            store.save_job(job)
    return job
