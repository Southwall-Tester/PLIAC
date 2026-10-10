"""Opt-in, activity-bound camera storage. Media never changes learning diagnoses."""
import base64
import hashlib
import json
import math
import os
import shutil
import sqlite3
import subprocess
import time
import uuid
from contextlib import contextmanager

from learning_agent.course_graph import CourseGraphError, safe_id


def capture_policy():
    contact = os.environ.get("PLIAC_MEDIA_CONTACT", "").strip()
    try:
        days = int(os.environ.get("PLIAC_MEDIA_RETENTION_DAYS", "0"))
    except ValueError:
        days = 0
    enabled = os.environ.get("PLIAC_MEDIA_ENABLED") == "1" and os.environ.get("PLIAC_REQUIRE_AUTH") == "1" and 1 <= days <= 30 and 0 < len(contact) <= 200
    if not enabled:
        return {"enabled": False, "notice": "摄像头留存尚未启用；正常学习不受影响。"}
    policy = {"enabled": True, "retention_days": days, "contact": contact,
        "purpose": "将可选授权的摄像头片段关联到学习活动，供本人及授权后台回看。",
        "limits": "不录屏、不录音，不用于比赛展示，不上传到模型，不自动推断心理状态或掌握程度。",
        "withdrawal": "可暂停或撤回；撤回删除当前服务中的该次片段。独立备份须按部署删除方案处理。",
        "max_clip_bytes": 1_000_000, "max_session_bytes": 50_000_000}
    policy["version"] = hashlib.sha256(json.dumps(policy, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    return policy


def number(value, label, minimum, maximum):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not minimum <= value <= maximum:
        raise CourseGraphError(f"{label}超出允许范围。", 400)
    return value


def validate_clip(content):
    """Fail closed before persistence; never trust browser MIME or consent alone."""
    probe, decoder = shutil.which("ffprobe"), shutil.which("ffmpeg")
    if not probe or not decoder:
        raise CourseGraphError("服务端视频验证工具未就绪，片段未保存。", 503)
    try:
        result = subprocess.run([probe, "-v", "error", "-protocol_whitelist", "pipe",
            "-f", "matroska", "-i", "pipe:0", "-show_streams", "-of", "json"],
            input=content, capture_output=True, timeout=10, check=True)
        streams = json.loads(result.stdout).get("streams", [])
        if len(streams) != 1:
            raise ValueError("exactly one video stream required")
        video = streams[0]
        if (video.get("codec_type") != "video" or video.get("codec_name") not in {"vp8", "vp9"}
                or not 1 <= int(video.get("width", 0)) <= 1280
                or not 1 <= int(video.get("height", 0)) <= 720):
            raise ValueError("unsupported camera stream")
        # Decode the entire bounded upload, not just its first frame. No audio or
        # external protocols are allowed. A timeout fails instead of saving bytes.
        decoded = subprocess.run([decoder, "-v", "error", "-xerror", "-threads", "1",
            "-protocol_whitelist", "pipe", "-f", "matroska", "-i", "pipe:0",
            "-map", "0:v:0", "-an", "-progress", "pipe:1", "-f", "null", "-"],
            input=content, capture_output=True, timeout=15, check=True)
        progress = {}
        for line in decoded.stdout.decode("utf-8", errors="replace").splitlines():
            key, sep, value = line.partition("=")
            if sep:
                progress[key] = value.strip()
        if (progress.get("progress") != "end" or not 1 <= int(progress.get("frame", 0)) <= 600
                or not 0 < int(progress.get("out_time_us", 0)) <= 20_500_000):
            raise ValueError("invalid decoded duration or frame count")
    except (subprocess.SubprocessError, OSError, ValueError, TypeError, KeyError) as exc:
        raise CourseGraphError("视频无效或不符合限制：须为可解码、无音轨的 VP8/VP9 WebM，最长 20 秒、最高 1280×720。", 400) from exc


class MediaStore:
    def __init__(self, course_store, clock=time.time):
        self.course = course_store
        self.path = course_store.output_dir / "camera.sqlite3"
        self.clock = clock

    @contextmanager
    def connection(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            db.execute("PRAGMA foreign_keys=ON")
            db.execute("PRAGMA secure_delete=ON")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS sessions (
                    id TEXT PRIMARY KEY, student TEXT NOT NULL, request_id TEXT NOT NULL,
                    activity_kind TEXT NOT NULL, activity_id TEXT NOT NULL, course_version INTEGER NOT NULL,
                    policy TEXT NOT NULL, status TEXT NOT NULL, started REAL NOT NULL, expires REAL NOT NULL,
                    UNIQUE(student, request_id));
                CREATE TABLE IF NOT EXISTS clips (
                    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                    sequence INTEGER NOT NULL, start_ms REAL NOT NULL, duration_ms REAL NOT NULL,
                    received REAL NOT NULL, digest TEXT NOT NULL, content BLOB NOT NULL,
                    PRIMARY KEY(session_id, sequence));
                CREATE TABLE IF NOT EXISTS review_access (
                    actor TEXT NOT NULL, student TEXT NOT NULL, session_id TEXT NOT NULL,
                    operation TEXT NOT NULL, requested REAL NOT NULL);
            """)
            # Expired content cannot be read even if scheduled cleanup was delayed.
            db.execute("DELETE FROM clips WHERE session_id IN (SELECT id FROM sessions WHERE expires<=?)", (self.clock(),))
            db.execute("UPDATE sessions SET status='expired' WHERE expires<=? AND status!='revoked'", (self.clock(),))
            db.commit()
            db.execute("BEGIN IMMEDIATE")
            yield db
            db.commit()
        finally:
            db.close()

    @staticmethod
    def public(row):
        return {key: row[key] for key in ("id", "activity_kind", "activity_id", "course_version", "status", "started", "expires")}

    def owned(self, db, student, ident):
        safe_id(student, "学习编号"); safe_id(ident, "摄像头会话")
        row = db.execute("SELECT * FROM sessions WHERE id=? AND student=?", (ident, student)).fetchone()
        if not row:
            raise CourseGraphError("未找到本人的摄像头会话。", 404)
        return row

    def start(self, body):
        policy = capture_policy()
        if not policy["enabled"]:
            raise CourseGraphError(policy["notice"], 503)
        if body.get("accepted") is not True or body.get("policy_version") != policy["version"]:
            raise CourseGraphError("请阅读并同意当前摄像头用途与保存说明。", 409)
        student = safe_id(body.get("student_id"), "学习编号")
        request_id = safe_id(body.get("request_id"), "请求编号")
        ident = safe_id(body.get("activity_id"), "学习活动")
        kind = body.get("activity_kind")
        graph = self.course._require_graph()
        workspace = self.course.load_learner(student, graph).get("workspace", {})
        objects = {"material": (workspace.get("tutor_turns", []), "request_id"),
                   "assessment": (workspace.get("assessments", []), "id"),
                   "lab": (workspace.get("ml_lab", {}).get("sessions", []), "id")}
        items, field = objects.get(kind, ([], "id"))
        record = next((item for item in items if item.get(field) == ident), None)
        if not record or record.get("course_version") != graph["version"]:
            raise CourseGraphError("只能关联本人当前课程版本中的已保存学习活动。", 409)
        with self.connection() as db:
            previous = db.execute("SELECT * FROM sessions WHERE student=? AND request_id=?", (student, request_id)).fetchone()
            if previous:
                if previous["activity_kind"] != kind or previous["activity_id"] != ident or json.loads(previous["policy"])["version"] != policy["version"]:
                    raise CourseGraphError("同一请求不能改变摄像头授权用途。", 409)
                return self.public(previous)
            if db.execute("SELECT COUNT(*) FROM sessions WHERE student=?", (student,)).fetchone()[0] >= 100:
                raise CourseGraphError("摄像头会话数量已达到上限。", 409)
            if db.execute("SELECT 1 FROM sessions WHERE student=? AND status IN ('active','paused')", (student,)).fetchone():
                raise CourseGraphError("请先停止已有摄像头会话，不能多标签同时采集。", 409)
            session_id, now = uuid.uuid4().hex, self.clock()
            db.execute("INSERT INTO sessions VALUES (?,?,?,?,?,?,?,?,?,?)", (session_id, student, request_id, kind, ident,
                graph["version"], json.dumps(policy, ensure_ascii=False), "active", now, now + policy["retention_days"] * 86400))
            return self.public(self.owned(db, student, session_id))

    def control(self, body):
        actions = {"pause": ("active", "paused"), "resume": ("paused", "active"), "stop": (None, "closed"), "revoke": (None, "revoked")}
        operation = body.get("operation")
        if operation not in actions:
            raise CourseGraphError("不支持的摄像头操作。", 400)
        with self.connection() as db:
            row = self.owned(db, body.get("student_id"), body.get("session_id"))
            source, target = actions[operation]
            if operation == "revoke":
                db.execute("DELETE FROM clips WHERE session_id=?", (row["id"],))
            elif row["status"] == target:
                return self.public(row)
            elif row["status"] in {"closed", "expired", "revoked"} or source and row["status"] != source:
                raise CourseGraphError("会话状态已变化，不能恢复已关闭或撤回的采集。", 409)
            if operation == "resume":
                self.check_policy(row)
            db.execute("UPDATE sessions SET status=? WHERE id=?", (target, row["id"]))
            return self.public(self.owned(db, row["student"], row["id"]))

    @staticmethod
    def check_policy(row):
        policy = capture_policy()
        if not policy["enabled"] or json.loads(row["policy"])["version"] != policy["version"]:
            raise CourseGraphError("摄像头授权配置已变化，请停止旧会话并重新授权。", 409)

    def upload(self, body):
        sequence = number(body.get("sequence"), "片段序号", 0, 1000)
        if type(sequence) is not int:
            raise CourseGraphError("片段序号须为整数。", 400)
        start = number(body.get("start_ms"), "相对开始时间", 0, 3_600_000)
        duration = number(body.get("duration_ms"), "片段时长", 1, 20_000)
        encoded = body.get("content_base64")
        if not isinstance(encoded, str) or len(encoded) > 1_333_336:
            raise CourseGraphError("片段超过上传大小限制。", 413)
        try:
            content = base64.b64decode(encoded, validate=True)
        except ValueError as exc:
            raise CourseGraphError("片段编码无效。", 400) from exc
        if len(content) > 1_000_000 or not content.startswith(b"\x1a\x45\xdf\xa3"):
            raise CourseGraphError("仅支持独立 WebM 片段，且每片段不超过 1 MB。", 400)
        digest = hashlib.sha256(content).hexdigest()
        # Check ownership and current consent before spending decoder resources.
        # Release the database lock during decoding, then recheck below because
        # the user may revoke consent while validation is running.
        with self.connection() as db:
            row = self.owned(db, body.get("student_id"), body.get("session_id"))
            self.check_policy(row)
            if row["status"] != "active":
                raise CourseGraphError("会话当前不接受上传。", 409)
        validate_clip(content)
        with self.connection() as db:
            row = self.owned(db, body.get("student_id"), body.get("session_id"))
            self.check_policy(row)
            if row["course_version"] != self.course._require_graph()["version"]:
                raise CourseGraphError("课程版本已更新，请结束旧摄像头会话。", 409)
            if row["status"] != "active":
                raise CourseGraphError("会话已暂停、结束、撤回或到期，拒绝写入。", 409)
            previous = db.execute("SELECT * FROM clips WHERE session_id=? AND sequence=?", (row["id"], sequence)).fetchone()
            if previous:
                if previous["digest"] != digest or previous["start_ms"] != start or previous["duration_ms"] != duration:
                    raise CourseGraphError("相同片段序号不能覆盖不同内容。", 409)
                return {"sequence": sequence, "received": previous["received"]}
            last = db.execute("SELECT sequence,start_ms,duration_ms FROM clips WHERE session_id=? ORDER BY sequence DESC LIMIT 1", (row["id"],)).fetchone()
            if sequence != (last["sequence"] + 1 if last else 0) or last and start < last["start_ms"] + last["duration_ms"]:
                raise CourseGraphError("片段须按顺序上传，时间范围不得重叠。", 409)
            total = db.execute("SELECT COALESCE(SUM(length(content)),0) FROM clips WHERE session_id=?", (row["id"],)).fetchone()[0]
            if total + len(content) > 50_000_000:
                raise CourseGraphError("本次摄像头会话已达到 50 MB 上限，请停止采集。", 413)
            now = self.clock()
            db.execute("INSERT INTO clips VALUES (?,?,?,?,?,?,?)", (row["id"], sequence, start, duration, now, digest, content))
            return {"sequence": sequence, "received": now}

    def list_sessions(self, student):
        safe_id(student, "学习编号")
        with self.connection() as db:
            return [self.public(row) for row in db.execute(
                "SELECT * FROM sessions WHERE student=? ORDER BY started DESC,id DESC LIMIT 100", (student,))]

    def audit_review(self, actor, student, ident, operation):
        safe_id(actor, "管理身份"); safe_id(student, "学习编号")
        if ident:
            safe_id(ident, "摄像头会话")
        with self.connection() as db:
            db.execute("INSERT INTO review_access VALUES (?,?,?,?,?)", (actor, student, ident, operation, self.clock()))

    def view(self, student, ident):
        with self.connection() as db:
            row = self.owned(db, student, ident)
            result = self.public(row)
            result["policy"] = json.loads(row["policy"])
            result["clips"] = [dict(item) for item in db.execute("SELECT sequence,start_ms,duration_ms,received FROM clips WHERE session_id=? ORDER BY sequence", (ident,))]
            return result

    def read(self, student, ident, sequence):
        with self.connection() as db:
            row = self.owned(db, student, ident)
            if row["status"] in {"expired", "revoked"}:
                raise CourseGraphError("片段已到期或撤回。", 404)
            clip = db.execute("SELECT content FROM clips WHERE session_id=? AND sequence=?", (ident, sequence)).fetchone()
            if not clip:
                raise CourseGraphError("未找到片段。", 404)
            return clip["content"]
