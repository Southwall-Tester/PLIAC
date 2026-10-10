"""Delete expired camera bytes even when no media endpoint is visited."""
import asyncio
import logging
import sqlite3
import time
from contextlib import closing

from starlette.concurrency import run_in_threadpool
from learning_agent.course_catalog import COURSE_ID

logger = logging.getLogger(__name__)


def cleanup_expired(root, now=None):
    """Only known camera database locations; never recursively scan user files."""
    root = root.absolute()
    if root.resolve() != root:
        raise ValueError("Media cleanup root must not be redirected")
    candidates = [root / "camera.sqlite3", root / "acceptance_demo" / "v1" / "camera.sqlite3"]
    courses = root / "courses"
    if courses.resolve() == courses and courses.is_dir():
        candidates.extend(directory / "camera.sqlite3" for directory in courses.iterdir()
                          if COURSE_ID.fullmatch(directory.name))
    deleted = checked = failed = 0
    for path in candidates:
        if path.resolve() != path or not path.is_file():
            continue
        try:
            # mode=rw cannot create a missing database during a filesystem race.
            with closing(sqlite3.connect(path.as_uri() + "?mode=rw", uri=True, timeout=2)) as db:
                db.execute("PRAGMA secure_delete=ON")
                stamp = time.time() if now is None else now
                count = db.execute("DELETE FROM clips WHERE session_id IN (SELECT id FROM sessions WHERE expires<=?)", (stamp,)).rowcount
                db.execute("UPDATE sessions SET status='expired' WHERE expires<=? AND status!='revoked'", (stamp,))
                db.commit()
                deleted += count
                checked += 1
        except sqlite3.Error:
            failed += 1
            logger.warning("Camera expiry cleanup failed for one database; next cycle will retry")
    return {"checked": checked, "deleted_clips": deleted, "failed": failed}


class MediaCleanup:
    def __init__(self, root_provider, interval=60):
        self.root_provider = root_provider
        self.interval = interval
        self.stop_event = asyncio.Event()
        self.task = None
        self.status = {"last_success": None, "failed": 0}

    async def sweep(self):
        try:
            result = await run_in_threadpool(cleanup_expired, self.root_provider())
            self.status = result | {"last_success": time.time() if not result["failed"] else self.status.get("last_success")}
        except Exception:
            self.status = self.status | {"failed": self.status.get("failed", 0) + 1}
            logger.warning("Camera expiry scan failed; next cycle will retry")

    async def start(self):
        await self.sweep()
        self.task = asyncio.create_task(self.run())

    async def run(self):
        while not self.stop_event.is_set():
            try:
                await asyncio.wait_for(self.stop_event.wait(), timeout=self.interval)
            except asyncio.TimeoutError:
                await self.sweep()

    async def close(self):
        self.stop_event.set()
        if self.task:
            await self.task
