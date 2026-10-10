"""Durable teaching-generation receipts with leases and fenced result writes."""
import asyncio
import os
import hashlib
import json
import sqlite3
import time
import uuid
import threading
from contextlib import contextmanager

from learning_agent.course_graph import CourseGraphError, safe_id, _text
from .tutor import TeachingProposal

LEASE_SECONDS = 45
HEARTBEAT_SECONDS = 10
GENERATION_SECONDS = 180
_tasks = set()
_capacity_lock = threading.Lock()
_active_generations = 0


@contextmanager
def generation_capacity():
    global _active_generations
    try:
        limit = int(os.environ.get('PLIAC_TEACHING_MAX_ACTIVE_PER_PROCESS', '8'))
    except ValueError:
        limit = 0
    if not 1 <= limit <= 64:
        raise CourseGraphError('教学总并发配置无效，请维护者设置每进程 1—64 个活动任务。', 503)
    with _capacity_lock:
        if _active_generations >= limit:
            raise CourseGraphError('教学服务繁忙，已保存内容仍可查看；请稍后重试原请求，本次不消耗模型尝试次数。', 429)
        _active_generations += 1
    try:
        yield
    finally:
        with _capacity_lock:
            _active_generations -= 1


class TeachingJobs:
    def __init__(self, store):
        self.path = store.output_dir / "teaching-jobs.sqlite3"

    @contextmanager
    def connection(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(self.path, timeout=5)
        try:
            db.row_factory = sqlite3.Row
            db.execute('BEGIN IMMEDIATE')
            db.execute("""CREATE TABLE IF NOT EXISTS jobs (
                student TEXT NOT NULL, request TEXT NOT NULL, fingerprint TEXT NOT NULL,
                status TEXT NOT NULL, owner TEXT NOT NULL, updated REAL NOT NULL,
                attempts INTEGER NOT NULL, result TEXT, PRIMARY KEY (student, request))""")
            if 'retry_limit' not in {column[1] for column in db.execute('PRAGMA table_info(jobs)')}:
                db.execute('ALTER TABLE jobs ADD COLUMN retry_limit INTEGER NOT NULL DEFAULT 3')
            db.execute('''CREATE TABLE IF NOT EXISTS recoveries (
                receipt TEXT PRIMARY KEY, actor TEXT NOT NULL, student TEXT NOT NULL,
                request TEXT NOT NULL, reason TEXT NOT NULL, attempts INTEGER NOT NULL,
                previous_limit INTEGER NOT NULL, created REAL NOT NULL)''')
            db.commit()
            with db:
                yield db
        finally:
            db.close()

    def claim(self, student, request, fingerprint):
        owner = uuid.uuid4().hex
        now = time.time()
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM jobs WHERE student=? AND request=?", (student, request)).fetchone()
            if row:
                if row["fingerprint"] != fingerprint:
                    raise CourseGraphError("请求对应的学习上下文已改变，请重新发起教学请求。", 409)
                if row["status"] == "generated":
                    return None, json.loads(row["result"])
                if row["status"] == "running" and now - row["updated"] < LEASE_SECONDS:
                    raise CourseGraphError("这个教学请求仍在生成，请稍后查询或重试，不会重复调用模型。", 409)
                if row["attempts"] >= row['retry_limit']:
                    raise CourseGraphError("这个教学请求已达到重试上限，请让维护者检查模型后恢复；不要反复点击。", 503)
            try:
                limit = int(os.environ.get("PLIAC_TEACHING_MAX_ACTIVE_PER_COURSE", "4"))
            except ValueError:
                limit = 0
            if not 1 <= limit <= 32:
                raise CourseGraphError("教学并发配置无效，请维护者设置每课程 1—32 个活动任务。", 503)
            count = db.execute("SELECT COUNT(*) FROM jobs WHERE status='running' AND updated>?",
                               (now - LEASE_SECONDS,)).fetchone()[0]
            if count >= limit:
                raise CourseGraphError("当前课程的教学服务繁忙，原有内容和草稿仍保留；请稍后重试原请求。本次未调用模型，也不消耗任务重试次数。", 429)
            if row:
                db.execute("UPDATE jobs SET status='running', owner=?, updated=?, attempts=attempts+1 WHERE student=? AND request=?",
                           (owner, now, student, request))
            else:
                db.execute("INSERT INTO jobs (student,request,fingerprint,status,owner,updated,attempts,result) VALUES (?, ?, ?, 'running', ?, ?, 1, NULL)",
                           (student, request, fingerprint, owner, now))
        return owner, None

    def cached(self, student, request, fingerprint):
        with self.connection() as db:
            row = db.execute('SELECT * FROM jobs WHERE student=? AND request=?', (student, request)).fetchone()
        if row:
            if row['fingerprint'] != fingerprint:
                raise CourseGraphError('请求对应的学习上下文已改变，请重新发起教学请求。', 409)
            if row['status'] == 'generated':
                return json.loads(row['result'])
            if row['status'] == 'running' and time.time() - row['updated'] < LEASE_SECONDS:
                raise CourseGraphError('这个教学请求仍在生成，请稍后查询或重试，不会重复调用模型。', 409)
        return None

    def update(self, student, request, owner, status, result=None):
        with self.connection() as db:
            changed = db.execute("UPDATE jobs SET status=?, updated=?, result=? WHERE student=? AND request=? AND owner=? AND status='running'",
                                (status, time.time(), json.dumps(result, ensure_ascii=False) if result is not None else None, student, request, owner)).rowcount
            if changed != 1:
                raise CourseGraphError("教学任务已被恢复或终止，旧结果不会覆盖当前任务。", 409)

    def status(self, student, request):
        student, request = safe_id(student, "学习编号"), safe_id(request, "请求编号")
        with self.connection() as db:
            row = db.execute("SELECT status, updated, attempts, retry_limit FROM jobs WHERE student=? AND request=?", (student, request)).fetchone()
        if not row:
            raise CourseGraphError("未找到当前学习编号的教学任务。", 404)
        state = row["status"]
        if state == "running" and time.time() - row["updated"] >= LEASE_SECONDS:
            state = "interrupted"
        return {"request_id": request, "status": state, "attempts": row["attempts"],
                "retry_limit": row['retry_limit'], "retry_remaining": max(0, row['retry_limit'] - row['attempts']),
                "notice": "生成结果不等于已写入学习档案；重试原请求后仍会核对学习版本。"}

    def recover(self, actor, body):
        actor = safe_id(actor, '管理身份')
        student = safe_id(body.get('student_id'), '学习编号')
        request = safe_id(body.get('job_id'), '任务编号')
        receipt = safe_id(body.get('request_id'), '恢复请求编号')
        reason = _text(body.get('reason'), '恢复原因', 500)
        attempts, limit = body.get('expected_attempts'), body.get('expected_limit')
        if type(attempts) is not int or type(limit) is not int:
            raise CourseGraphError('请先读取任务状态再恢复。', 400)
        with self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            previous = db.execute('SELECT * FROM recoveries WHERE receipt=?', (receipt,)).fetchone()
            if previous:
                if (previous['actor'], previous['student'], previous['request'], previous['reason'], previous['attempts'], previous['previous_limit']) != (actor, student, request, reason, attempts, limit):
                    raise CourseGraphError('恢复请求编号不能复用于其他操作。', 409)
            else:
                row = db.execute('SELECT * FROM jobs WHERE student=? AND request=?', (student, request)).fetchone()
                if not row:
                    raise CourseGraphError('没有该学习者的任务。', 404)
                if row['attempts'] != attempts or row['retry_limit'] != limit:
                    raise CourseGraphError('任务状态已变化，请重新读取。', 409)
                if row['status'] == 'generated' or (row['status'] == 'running' and time.time() - row['updated'] < LEASE_SECONDS):
                    raise CourseGraphError('不能恢复正在执行或已有生成结果的任务。', 409)
                if attempts < limit or limit >= 12:
                    raise CourseGraphError('任务尚有重试次数或已达到累计十二次上限，不能继续扩充。', 409)
                db.execute("UPDATE jobs SET status='interrupted',owner=?,retry_limit=retry_limit+3,updated=? WHERE student=? AND request=?",
                           (uuid.uuid4().hex, time.time(), student, request))
                db.execute('INSERT INTO recoveries VALUES (?,?,?,?,?,?,?,?)', (receipt, actor, student, request, reason, attempts, limit, time.time()))
        return self.status(student, request)


async def _generate(store, body, context, generator, result_type):
    student = safe_id(body.get("student_id"), "学习编号")
    request = safe_id(body.get("request_id"), "请求编号")
    # Include evidence and course context, not the model secret/configuration.
    fingerprint = hashlib.sha256(json.dumps({"context": context, "version": body["expected_version"], "result_type": result_type.__name__},
                                            ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    jobs = TeachingJobs(store)
    cached = await asyncio.to_thread(jobs.cached, student, request, fingerprint)
    if cached is not None:
        return result_type.model_validate(cached["proposal"]), cached["metadata"]

    with generation_capacity():
        return await _claimed_generation(jobs, student, request, fingerprint, generator, result_type)


async def _claimed_generation(jobs, student, request, fingerprint, generator, result_type):
    owner, cached = await asyncio.to_thread(jobs.claim, student, request, fingerprint)
    if cached is not None:
        return result_type.model_validate(cached['proposal']), cached['metadata']

    async def heartbeat():
        while True:
            await asyncio.sleep(HEARTBEAT_SECONDS)
            await asyncio.to_thread(jobs.update, student, request, owner, "running")

    async def execute():
        pulse = asyncio.create_task(heartbeat())
        generation = asyncio.create_task(generator())
        async def mark_failure(status):
            try:
                await asyncio.to_thread(jobs.update, student, request, owner, status)
            except CourseGraphError as error:
                if error.status_code != 409:
                    raise
                # A replacement owner controls this row; retain the original failure.
        try:
            done, _ = await asyncio.wait({pulse, generation}, timeout=GENERATION_SECONDS,
                                         return_when=asyncio.FIRST_COMPLETED)
            if not done:
                raise TimeoutError
            if pulse in done:
                await pulse  # A failed lease renewal invalidates this worker.
            proposal, metadata = await generation
            pulse.cancel()
            await asyncio.gather(pulse, return_exceptions=True)
            await asyncio.to_thread(jobs.update, student, request, owner, "generated",
                                    {"proposal": proposal.model_dump(), "metadata": metadata})
            return proposal, metadata
        except asyncio.CancelledError:
            await mark_failure("interrupted")
            raise
        except Exception as exc:
            await mark_failure("failed")
            if isinstance(exc, TimeoutError):
                raise CourseGraphError("教学生成超时，原有学习记录仍保留，可稍后重试。", 504) from exc
            raise
        finally:
            pulse.cancel()
            generation.cancel()
            await asyncio.gather(pulse, generation, return_exceptions=True)

    return await execute()


async def durable_generation(store, body, context, generator, *, result_type=TeachingProposal):
    task = asyncio.create_task(_generate(store, body, context, generator, result_type))
    _tasks.add(task)

    def finished(done):
        _tasks.discard(done)
        if not done.cancelled():
            done.exception()  # Consume failures even if the browser disconnected.

    task.add_done_callback(finished)
    # A disconnected request must not cancel a paid call; its result is durable.
    return await asyncio.shield(task)


async def close_teaching_jobs():
    tasks = list(_tasks)
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
