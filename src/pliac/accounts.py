"""Local accounts and session-bound learner identities.

Account data is separate from course/learner stores. Existing anonymous records
are retained and are never adopted automatically by a newly registered account.
"""
from contextlib import contextmanager
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import secrets
import threading
import time
import unicodedata
from urllib.parse import parse_qsl, quote, unquote, urlencode, urlsplit

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool
from starlette.requests import Request as StarletteRequest

from learning_agent.api import ChineseRoute, _body
from learning_agent.course_graph import CourseGraphError, _atomic_json

ROOT = Path(__file__).resolve().parents[2]
COOKIE = "pliac_session"
SESSION_SECONDS = 30 * 86400
ITERATIONS = 600_000
MAX_BODY = 2_101_248
_LOCK = threading.RLock()
router = APIRouter(prefix="/api/account", route_class=ChineseRoute)


def required(app):
    """Only an explicit test override disables production authentication."""
    return getattr(app.state, "auth_required", True) is not False


def directory(app):
    return Path(getattr(app.state, "account_directory", ROOT / "outputs" / "account"))


def _read(folder):
    path = folder / "current.json"
    with _LOCK:
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else dict(schema=1, users={}, sessions={})


@contextmanager
def _writer(folder):
    with _LOCK:
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / ".write.lock"
        deadline = time.monotonic() + 5
        while True:
            try:
                descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
                os.close(descriptor)
                break
            except FileExistsError:
                if time.monotonic() >= deadline:
                    raise CourseGraphError("账号保存正在进行，请稍后重试。", 409)
                time.sleep(.02)
        try:
            yield
        finally:
            path.unlink(missing_ok=True)


def _name(value):
    if not isinstance(value, str):
        raise CourseGraphError("请输入 3～40 位账号，可使用中英文、数字、点、下划线和短横线。")
    value = unicodedata.normalize("NFKC", value).strip()
    if not re.fullmatch(r"[\w.-]{3,40}", value) or ".." in value:
        raise CourseGraphError("请输入 3～40 位账号，可使用中英文、数字、点、下划线和短横线。")
    return value


def _name_key(value):
    return hashlib.sha256(value.casefold().encode("utf-8")).hexdigest()


def _password(value):
    if not isinstance(value, str) or not 8 <= len(value) <= 128:
        raise CourseGraphError("密码需要 8～128 个字符。")
    return value


def _hash(password, salt=None):
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt), ITERATIONS).hex()
    return dict(algorithm="pbkdf2_sha256", iterations=ITERATIONS, salt=salt, digest=digest)


def _matches(password, record):
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(record["salt"]),
                               record["iterations"]).hex()
    return hmac.compare_digest(digest, record["digest"])


def _token_key(token):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _public(user):
    return {key: user[key] for key in ("id", "display_name", "student_id", "assistant_owner")}


def current_user(app, token):
    if not token or not re.fullmatch(r"[A-Za-z0-9_-]{40,100}", token):
        return None
    state = _read(directory(app))
    session = state["sessions"].get(_token_key(token))
    if not session or session["expires_at"] <= time.time():
        return None
    return state["users"].get(session["user_id"])


def safe_return_to(value):
    """Accept only ordinary same-site paths, including after percent decoding."""
    if not isinstance(value, str) or len(value) > 2000:
        return "/courses"
    decoded = value
    for _ in range(3):
        decoded = unquote(decoded)
    if (not value.startswith("/") or decoded.startswith("//") or "\\" in decoded
            or any(ord(char) < 32 for char in decoded)):
        return "/courses"
    parts = urlsplit(decoded)
    if parts.scheme or parts.netloc or parts.path in {"/login", "/api/account/login", "/api/account/register"}:
        return "/courses"
    return value


def _same_origin(request):
    origin = request.headers.get("origin")
    if origin and (urlsplit(origin).scheme != request.url.scheme
                   or urlsplit(origin).netloc != request.headers.get("host")):
        raise CourseGraphError("请从当前网站提交请求。", 403)
    if request.headers.get("sec-fetch-site") == "cross-site":
        raise CourseGraphError("请从当前网站提交请求。", 403)


def _issue(state, user, old_token=""):
    now = time.time()
    state["sessions"] = {key: item for key, item in state["sessions"].items() if item["expires_at"] > now}
    if old_token:
        state["sessions"].pop(_token_key(old_token), None)
    token = secrets.token_urlsafe(32)
    state["sessions"][_token_key(token)] = dict(user_id=user["id"], created_at=now, expires_at=now + SESSION_SECONDS)
    return token


def _register(folder, body, old_token):
    username = _name(body.get("username"))
    password_hash = _hash(_password(body.get("password")))
    display = body.get("display_name", username)
    if not isinstance(display, str) or not 1 <= len(display.strip()) <= 80 or any(ord(char) < 32 for char in display):
        raise CourseGraphError("显示名称需要 1～80 个可见字符。")
    key = _name_key(username)
    with _writer(folder):
        state = _read(folder)
        if any(user["username_key"] == key for user in state["users"].values()):
            raise CourseGraphError("这个账号暂不可用，请更换名称或使用已有账号登录。", 409)
        user = dict(id=secrets.token_hex(16), username_key=key, display_name=display.strip(),
                    password_hash=password_hash, student_id="u_" + secrets.token_hex(12),
                    assistant_owner=secrets.token_hex(16), created_at=time.time())
        state["users"][user["id"]] = user
        token = _issue(state, user, old_token)
        _atomic_json(folder / "current.json", state)
    return user, token


def _login(folder, body, old_token):
    try:
        username = _name(body.get("username"))
        password = _password(body.get("password"))
    except CourseGraphError:
        raise CourseGraphError("账号或密码不正确。", 401) from None
    state = _read(folder)
    user = next((value for value in state["users"].values() if value["username_key"] == _name_key(username)), None)
    # Unknown names incur the same password derivation work as existing names.
    record = user["password_hash"] if user else dict(iterations=ITERATIONS, salt="00" * 16, digest="00" * 32)
    matches = _matches(password, record)
    if not user or not matches:
        raise CourseGraphError("账号或密码不正确。", 401)
    with _writer(folder):
        state = _read(folder)
        token = _issue(state, user, old_token)
        _atomic_json(folder / "current.json", state)
    return user, token


def _response(request, user, token, body):
    response = JSONResponse(dict(authenticated=True, user=_public(user), next=safe_return_to(body.get("next", "/courses"))))
    response.set_cookie(COOKIE, token, max_age=SESSION_SECONDS, httponly=True, samesite="lax",
                        secure=request.url.scheme == "https", path="/")
    response.headers["Cache-Control"] = "no-store"
    return response


@router.get("/me")
def me(request: Request):
    if not required(request.app):
        return dict(authenticated=False, testing=True)
    user = current_user(request.app, request.cookies.get(COOKIE, ""))
    if not user:
        raise CourseGraphError("请先登录。", 401)
    return JSONResponse(dict(authenticated=True, user=_public(user)), headers={"Cache-Control": "no-store"})


@router.post("/register")
async def register(request: Request):
    _same_origin(request)
    body = await _body(request)
    user, token = await run_in_threadpool(_register, directory(request.app), body, request.cookies.get(COOKIE, ""))
    return _response(request, user, token, body)


@router.post("/login")
async def login(request: Request):
    _same_origin(request)
    body = await _body(request)
    user, token = await run_in_threadpool(_login, directory(request.app), body, request.cookies.get(COOKIE, ""))
    return _response(request, user, token, body)


@router.post("/logout")
async def logout(request: Request):
    _same_origin(request)
    token = request.cookies.get(COOKIE, "")
    if token:
        def revoke():
            folder = directory(request.app)
            with _writer(folder):
                state = _read(folder)
                state["sessions"].pop(_token_key(token), None)
                _atomic_json(folder / "current.json", state)
        await run_in_threadpool(revoke)
    response = JSONResponse({"ok": True})
    response.delete_cookie(COOKIE, path="/", httponly=True, samesite="lax")
    response.headers["Cache-Control"] = "no-store"
    return response


def _check_ids(value, user):
    expected = dict(student_id=user["student_id"], owner=user["assistant_owner"], assistant_owner=user["assistant_owner"])
    if isinstance(value, dict):
        for key, child in value.items():
            if key in expected and child not in ("", None, expected[key]):
                raise CourseGraphError("当前账号只能访问自己的学习记录和对话画像。", 403)
            _check_ids(child, user)
    elif isinstance(value, list):
        for child in value:
            _check_ids(child, user)


class AccountMiddleware:
    """Bind request identity server-side before any course/assistant handler."""
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or not required(scope["app"]):
            return await self.app(scope, receive, send)
        path = scope.get("path", "")
        public = path.startswith("/static/") or path in {
            "/health", "/login", "/favicon.ico", "/api/account/me", "/api/account/login",
            "/api/account/register", "/api/account/logout",
        }
        if public:
            return await self.app(scope, receive, send)
        request = StarletteRequest(scope, receive=receive)
        user = await run_in_threadpool(current_user, scope["app"], request.cookies.get(COOKIE, ""))
        if not user:
            if path.startswith("/api/"):
                response = JSONResponse({"detail": "请先登录。"}, status_code=401)
            else:
                target = path + ("?" + scope["query_string"].decode("utf-8", errors="replace") if scope["query_string"] else "")
                from starlette.responses import RedirectResponse
                response = RedirectResponse("/login?next=" + quote(safe_return_to(target), safe=""), status_code=303)
            return await response(scope, receive, send)
        scope.setdefault("state", {})["account"] = _public(user)
        try:
            if scope["method"] not in {"GET", "HEAD", "OPTIONS"}:
                _same_origin(request)
            pairs = parse_qsl(scope.get("query_string", b"").decode("utf-8"), keep_blank_values=True)
            _check_ids(dict(pairs), user)
            # Validate duplicates as well: frameworks may choose the last value.
            for key, value in pairs:
                _check_ids({key: value}, user)
            identities = dict(student_id=user["student_id"], owner=user["assistant_owner"], assistant_owner=user["assistant_owner"])
            pairs = [(key, identities[key] if key in identities else value) for key, value in pairs]
            if path.startswith("/api/"):
                present = {key for key, _ in pairs}
                if "student_id" not in present:
                    pairs.append(("student_id", user["student_id"]))
                if path.startswith("/api/assistant") and "owner" not in present:
                    pairs.append(("owner", user["assistant_owner"]))
            scope["query_string"] = urlencode(pairs).encode("utf-8")
            upload = path == "/api/documents/upload" and request.headers.get("content-type", "").startswith("multipart/form-data")
            if path.startswith("/api/") and not upload and scope["method"] not in {"GET", "HEAD", "OPTIONS"}:
                chunks, length = [], 0
                async for chunk in request.stream():
                    length += len(chunk)
                    if length > MAX_BODY:
                        raise CourseGraphError("请求内容过大，请缩小后重试。", 413)
                    chunks.append(chunk)
                try:
                    body = json.loads(b"".join(chunks) or b"{}")
                except (ValueError, UnicodeError, RecursionError):
                    raise CourseGraphError("提交内容不是有效 JSON。", 400) from None
                _check_ids(body, user)
                if isinstance(body, dict):
                    for key in identities:
                        if key in body:
                            body[key] = identities[key]
                    if path.startswith(("/api/learning", "/api/linux-lab", "/api/ml-lab", "/api/course-graph", "/api/handouts")):
                        body["student_id"] = user["student_id"]
                    if path.startswith("/api/assistant"):
                        body["owner"] = user["assistant_owner"]
                    if path.startswith("/api/handouts"):
                        body["assistant_owner"] = user["assistant_owner"]
                encoded = json.dumps(body, ensure_ascii=False).encode("utf-8")
                scope["headers"] = [(key, value) for key, value in scope["headers"] if key != b"content-length"] + [
                    (b"content-length", str(len(encoded)).encode("ascii"))]
                delivered = False
                async def replay():
                    nonlocal delivered
                    if not delivered:
                        delivered = True
                        return {"type": "http.request", "body": encoded, "more_body": False}
                    return await receive()
                return await self.app(scope, replay, send)
        except CourseGraphError as exc:
            return await JSONResponse({"detail": str(exc)}, status_code=exc.status_code)(scope, receive, send)
        return await self.app(scope, receive, send)
