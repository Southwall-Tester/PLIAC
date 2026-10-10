"""Opt-in protected runtime; legacy local development is explicitly separate."""
import hashlib
import ipaddress
import json
import os
import re
import secrets
import sqlite3
import time
import uuid
from contextlib import contextmanager

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

COOKIE = "pliac_session"
SESSION_SECONDS = 24 * 60 * 60
router = APIRouter(prefix="/api/access")


def enabled():
    return os.environ.get("PLIAC_REQUIRE_AUTH") == "1"


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


class IdentityStore:
    def __init__(self, root):
        self.path = root / "identities.sqlite3"

    @contextmanager
    def connection(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(self.path, timeout=5)
        db.row_factory = sqlite3.Row
        try:
            db.executescript("""CREATE TABLE IF NOT EXISTS identities (
                student TEXT PRIMARY KEY, recovery_hash TEXT UNIQUE NOT NULL);
                CREATE TABLE IF NOT EXISTS sessions (
                token_hash TEXT PRIMARY KEY, student TEXT NOT NULL, role TEXT NOT NULL, expires REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS attempts (
                peer_hash TEXT NOT NULL, operation TEXT NOT NULL, created REAL NOT NULL);""")
            with db:
                yield db
        finally:
            db.close()

    def session(self, token):
        if not token or len(token) > 200:
            return None
        with self.connection() as db:
            row = db.execute("SELECT student, role, expires FROM sessions WHERE token_hash=? AND expires>?",
                             (digest(token), time.time())).fetchone()
        return dict(row) if row else None

    def issue(self, *, recovery=None, admin=False):
        token, recovery_code = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        student = "learner-" + uuid.uuid4().hex
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            if recovery:
                row = db.execute("SELECT student FROM identities WHERE recovery_hash=?", (digest(recovery),)).fetchone()
                if not row:
                    raise ValueError("恢复码无效。")
                student = row["student"]
                db.execute("UPDATE identities SET recovery_hash=? WHERE student=?", (digest(recovery_code), student))
                db.execute("DELETE FROM sessions WHERE student=?", (student,))
            else:
                db.execute("INSERT INTO identities VALUES (?, ?)", (student, digest(recovery_code)))
            db.execute("DELETE FROM sessions WHERE expires<=?", (time.time(),))
            db.execute("INSERT INTO sessions VALUES (?, ?, ?, ?)",
                       (digest(token), student, "admin" if admin else "learner", time.time() + SESSION_SECONDS))
        return token, student, recovery_code

    def revoke(self, token):
        with self.connection() as db:
            db.execute("DELETE FROM sessions WHERE token_hash=?", (digest(token or ""),))

    def allow_attempt(self, peer, operation):
        """Bound identity issuance/credential attempts, including across workers."""
        now = time.time()
        limit = 20 if operation == "anonymous" else 10
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("DELETE FROM attempts WHERE created<?", (now - 600,))
            count = db.execute("SELECT COUNT(*) FROM attempts WHERE peer_hash=? AND operation=?",
                               (digest(peer), operation)).fetchone()[0]
            if count >= limit:
                return False
            db.execute("INSERT INTO attempts VALUES (?, ?, ?)", (digest(peer), operation, now))
        return True


def identities():
    from learning_agent import api
    return IdentityStore(api.store.output_dir)


def loopback(request):
    try:
        return ipaddress.ip_address(request.client.host).is_loopback
    except (ValueError, AttributeError):
        return False


def response(data, status=200):
    return JSONResponse(data, status_code=status, headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"})


async def read_json(request, limit=2 * 1024 * 1024):
    chunks, size = [], 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > limit:
            raise ValueError("请求过大。")
        chunks.append(chunk)
    request._body = b"".join(chunks)
    data = json.loads(request._body)
    if not isinstance(data, dict):
        raise ValueError("请求必须是 JSON 对象。")
    return data


@router.get("/session")
def current_session(request: Request):
    principal = identities().session(request.cookies.get(COOKIE)) if enabled() else None
    return response({"protected": enabled(), "identity": principal})


@router.post("/{operation}")
async def access_operation(operation: str, request: Request):
    if not enabled():
        return response({"detail": "当前是本地开发模式，未启用身份服务。"}, 409)
    if request.url.scheme != "https" and not loopback(request):
        return response({"detail": "共享访问必须使用 HTTPS。"}, 403)
    store = identities()
    if operation == "logout":
        await run_in_threadpool(store.revoke, request.cookies.get(COOKIE))
        result = response({"signed_out": True})
        result.delete_cookie(COOKIE, path="/")
        return result
    if operation not in {"anonymous", "recover", "admin"}:
        return response({"detail": "不支持的身份操作。"}, 404)
    try:
        body = await read_json(request, 4096)
    except (ValueError, UnicodeError, RecursionError):
        return response({"detail": "身份请求格式无效。"}, 400)
    if operation == "anonymous":
        existing = await run_in_threadpool(store.session, request.cookies.get(COOKIE))
        if existing:
            return response({"protected": True, "identity": existing})
        if body:
            return response({"detail": "新建匿名档案不接受自选身份编号。"}, 400)
    peer = request.client.host if request.client else "unknown"
    if not await run_in_threadpool(store.allow_attempt, peer, operation):
        result = response({"detail": "身份操作过于频繁，请在十分钟后重试。"}, 429)
        result.headers["Retry-After"] = "600"
        return result
    if operation == "admin":
        secret = os.environ.get("PLIAC_ADMIN_SECRET", "")
        supplied = body.get("secret")
        if len(secret) < 32 or not isinstance(supplied, str) or not secrets.compare_digest(secret.encode(), supplied.encode()):
            return response({"detail": "管理凭证无效或尚未配置。"}, 403)
    recovery = body.get("recovery_code") if operation == "recover" else None
    if operation == "recover" and (not isinstance(recovery, str) or not 32 <= len(recovery) <= 128):
        return response({"detail": "恢复码无效。"}, 403)
    try:
        token, student, recovery_code = await run_in_threadpool(store.issue, recovery=recovery, admin=operation == "admin")
    except ValueError:
        return response({"detail": "恢复码无效。"}, 403)
    result = response({"protected": True, "identity": {"student": student, "role": "admin" if operation == "admin" else "learner"},
                       "recovery_code": recovery_code if operation != "admin" else None})
    result.set_cookie(COOKIE, token, max_age=SESSION_SECONDS, httponly=True,
                      secure=request.url.scheme == "https", samesite="strict", path="/")
    return result


STUDENT_READS = {"/api/courses", "/api/learning", "/api/ml-lab", "/api/ml-lab/export",
    "/api/course-graph", "/api/course-graph/export", "/api/course-graph/learner/export",
    "/api/course-graph/path", "/api/course-graph/recommendations", "/api/tutor/archive", "/api/tutor/export/pdf", "/api/tutor/export/word"}
STUDENT_WRITES = {"/api/tutor/" + item for item in ("reply", "advance", "notes", "report", "assessment/start", "assessment/submit", "assessment/evaluate")}
STUDENT_WRITES |= {"/api/learning/" + item for item in ("onboard", "next", "draft", "hint", "answer", "ask", "annotate", "resource", "report", "study", "card", "mixed", "rest")}
STUDENT_WRITES |= {"/api/ml-lab/" + item for item in ("start", "rest", "hint", "run", "check", "support")}
STUDENT_WRITES.add("/api/tutor/flow")
STUDENT_WRITES.update({"/api/tutor/plan", "/api/tutor/plan/apply"})
STUDENT_READS.add("/api/learning/reading-position")
STUDENT_READS.add("/api/learning/continue")
STUDENT_READS.add("/api/learning/review-reminders")
STUDENT_READS.add("/api/tutor/source-preview")
STUDENT_READS.add("/api/tutor/textbook")
STUDENT_READS.add("/api/tutor/resources")
STUDENT_READS.add("/api/tutor/resource-position")
STUDENT_READS.update({"/api/tutor/resource-document", "/api/tutor/resource-document-page"})
STUDENT_WRITES.add("/api/tutor/resource-document-position")
STUDENT_WRITES.add("/api/tutor/resource-position")
STUDENT_READS.add("/api/tutor/source-page-image")
STUDENT_READS.add("/api/tutor/source-position")
STUDENT_WRITES.add("/api/tutor/source-position")
STUDENT_WRITES.add("/api/learning/reading-position")
STUDENT_WRITES.add("/api/learning/preferences")
STUDENT_READS.update({"/api/media/policy", "/api/media/session", "/api/media/sessions", "/api/media/clip"})
STUDENT_WRITES.update({"/api/media/start", "/api/media/control", "/api/media/upload"})


def published_document(ident):
    from learning_agent import api
    from learning_agent.course_catalog import list_courses, resolve_course
    for course in list_courses(api.store):
        graph = resolve_course(api.store, course["id"]).load_graph()
        if graph and any(node.get("document_id") == ident and node.get("document_evidence") for node in graph["nodes"]):
            return True
        if graph and any(item.get('review_status') in ('reviewed', 'auto_validated')
                         and item.get('url', '').split('#')[0] == f'/api/documents/{ident}/source'
                         for item in graph.get('resources', [])):
            return True
    return False


def student_courses():
    from learning_agent import api
    from learning_agent.course_catalog import list_courses, resolve_course
    courses = []
    for item in list_courses(api.store):
        graph = resolve_course(api.store, item["id"]).load_graph()
        if graph:
            courses.append({"id": graph["id"], "title": graph["title"], "status": "published",
                            "node_count": len(graph["nodes"]), "chapter_count": len(graph["chapters"])})
    return {"courses": courses}


async def access_gate(request, call_next):
    path = request.url.path.rstrip("/")
    if not enabled() or not path.startswith("/api/"):
        return await call_next(request)
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        origin = request.headers.get("origin")
        if (origin and origin != str(request.base_url).rstrip("/")) or request.headers.get("sec-fetch-site") == "cross-site":
            return response({"detail": "拒绝跨站写入请求。"}, 403)
    if path.startswith("/api/access/"):
        return await call_next(request)
    if request.url.scheme != "https" and not loopback(request):
        return response({"detail": "共享访问必须使用 HTTPS。"}, 403)
    principal = await run_in_threadpool(identities().session, request.cookies.get(COOKIE))
    if not principal:
        return response({"detail": "请先建立或恢复你的学习身份。"}, 401)
    request.state.identity = principal
    if principal["role"] == "admin":
        return await call_next(request)
    reading = request.method == "GET"
    permitted = reading and (path in STUDENT_READS or re.fullmatch(r"/api/tutor/jobs/[A-Za-z0-9_-]+", path))
    source = re.fullmatch(r"/api/documents/([A-Za-z0-9_-]+)/source", path)
    if reading and source:
        permitted = await run_in_threadpool(published_document, source.group(1))
    if request.method == "POST":
        permitted = path in STUDENT_WRITES
    if request.method == "PUT" and path == "/api/course-graph/profile":
        permitted = True
    if not permitted or any(view != "published" for view in request.query_params.getlist("view")):
        return response({"detail": "该操作需要管理权限。"}, 403)
    if any(value != principal["student"] for value in request.query_params.getlist("student_id")):
        return response({"detail": "不能访问其他学习者的档案。"}, 403)
    if reading and path == "/api/courses":
        return response(await run_in_threadpool(student_courses))
    if request.method in {"POST", "PUT"}:
        try:
            body = await read_json(request)
        except (ValueError, UnicodeError, RecursionError):
            return response({"detail": "学习请求格式无效。"}, 400)
        if body.get("student_id") != principal["student"]:
            return response({"detail": "不能修改其他学习者的档案。"}, 403)
    result = await call_next(request)
    result.headers["Cache-Control"] = "no-store"
    return result
