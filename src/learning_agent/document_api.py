"""Upload and page-grounded candidate graph endpoints."""
from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from starlette.concurrency import run_in_threadpool

from . import api
from .api import ChineseRoute, _body
from .course_graph import CourseGraphError
from .documents import MAX_UPLOAD, document_store

router = APIRouter(prefix="/api/documents", tags=["资料图谱"], route_class=ChineseRoute)


@router.get("")
def listing():
    return {"documents": document_store.listing()}


@router.post("/upload")
async def upload(file: UploadFile = File(...), engine: str = Form("local"), start_page: int = Form(1), end_page: str = Form("")):
    try:
        end = int(end_page) if end_page.strip() else None
    except ValueError as exc:
        raise CourseGraphError("结束页码须为整数。") from exc
    job = document_store.create(file.filename or "", engine, start_page, end)
    path = document_store.source(job["id"])
    size = 0
    try:
        with path.open("wb") as target:
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                if size > MAX_UPLOAD:
                    raise CourseGraphError("文件超过 512 MB，请分章节上传。", 413)
                target.write(chunk)
        if not size:
            raise CourseGraphError("上传文件为空。")
        document_store.update(job["id"], size=size)
        return document_store.submit(job["id"])
    except Exception as exc:
        path.unlink(missing_ok=True)
        document_store.update(job["id"], status="failed", error=str(exc))
        raise
    finally:
        await file.close()


@router.get("/{ident}")
def status(ident: str):
    return document_store.status(ident)


@router.get("/{ident}/graph")
@router.get("/{ident}/export")
def graph(ident: str):
    return document_store.graph(ident)


@router.get("/{ident}/source")
def source(ident: str):
    job = document_store.status(ident)
    path = document_store.source(ident)
    if not path.is_file():
        raise CourseGraphError("原文件不存在，请重新上传。", 404)
    return FileResponse(path, filename=job["filename"], content_disposition_type="inline", headers={"X-Content-Type-Options": "nosniff"})


@router.get("/{ident}/pages/{page}")
def page(ident: str, page: int):
    return document_store.page(ident, page)


@router.post("/{ident}/cancel")
def cancel(ident: str):
    return document_store.cancel(ident)


@router.post("/{ident}/retry")
def retry(ident: str):
    return document_store.submit(ident)


@router.post("/{ident}/import")
async def import_draft(ident: str, request: Request):
    body = await _body(request)
    course_store = api.resolve_course_store(body.get("course_id", ""))
    return await run_in_threadpool(document_store.import_draft, ident, course_store, body.get("expected_version"), body.get("node_ids"))
