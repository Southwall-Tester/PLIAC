"""Expiry without visiting media APIs, only isolated synthetic database bytes."""
import asyncio
import sqlite3
import tempfile
import time
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace

from pliac.media_cleanup import cleanup_expired, MediaCleanup


def database(path, expires):
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(path)) as db:
        db.executescript("CREATE TABLE sessions(id TEXT,expires REAL,status TEXT); CREATE TABLE clips(session_id TEXT,content BLOB);")
        db.execute("INSERT INTO sessions VALUES ('test',?,'closed')", (expires,))
        db.execute("INSERT INTO clips VALUES ('test',?)", (b'synthetic',))
        db.commit()


def count(path):
    with closing(sqlite3.connect(path)) as db:
        return db.execute("SELECT COUNT(*) FROM clips").fetchone()[0]


class CleanupTests(unittest.TestCase):
    def test_known_locations_only_and_expiry_boundary(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            expired = root / 'camera.sqlite3'
            future = root / 'courses' / ('a' * 32) / 'camera.sqlite3'
            demo = root / 'acceptance_demo/v1/camera.sqlite3'
            unrelated = root / 'unrelated/camera.sqlite3'
            for path, expiry in [(expired, 100), (future, 101), (demo, 99), (unrelated, 0)]:
                database(path, expiry)
            result = cleanup_expired(root, now=100)
            self.assertEqual(result, {'checked': 3, 'deleted_clips': 2, 'failed': 0})
            self.assertEqual([count(p) for p in (expired, future, demo, unrelated)], [0, 1, 0, 1])
            self.assertEqual(cleanup_expired(root, now=100)['deleted_clips'], 0)

    def test_one_broken_database_does_not_block_others(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            with closing(sqlite3.connect(root / 'camera.sqlite3')) as db:
                db.execute('CREATE TABLE unrelated(value TEXT)')
            path = root / 'courses' / ('b' * 32) / 'camera.sqlite3'
            database(path, 0)
            result = cleanup_expired(root, now=100)
            self.assertEqual(result['failed'], 1)
            self.assertEqual(count(path), 0)


class PeriodicTests(unittest.IsolatedAsyncioTestCase):
    async def test_application_lifespan_runs_cleanup_even_when_capture_disabled(self):
        from pliac.main import lifespan
        import os
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            path = root / 'camera.sqlite3'
            database(path, time.time() - 1)
            application = SimpleNamespace(state=SimpleNamespace())
            with patch('learning_agent.api.store', SimpleNamespace(output_dir=root)), patch.dict(os.environ, {'PLIAC_MEDIA_ENABLED': '0'}):
                async with lifespan(application):
                    self.assertEqual(count(path), 0)
                    self.assertFalse(application.state.media_cleanup.task.done())
                self.assertTrue(application.state.media_cleanup.task.done())

    async def test_background_cycle_cleans_without_request_and_stops(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            worker = MediaCleanup(lambda: root, interval=0.02)
            await worker.start()
            try:
                path = root / 'camera.sqlite3'
                database(path, time.time() - 1)
                for _ in range(100):
                    if count(path) == 0:
                        break
                    await asyncio.sleep(0.02)
                self.assertEqual(count(path), 0)
                self.assertIsNotNone(worker.status['last_success'])
            finally:
                await worker.close()
            self.assertTrue(worker.task.done())

    async def test_scan_failure_retries_next_cycle(self):
        worker = MediaCleanup(lambda: Path('unused'))
        with patch('pliac.media_cleanup.cleanup_expired', side_effect=[OSError('synthetic failure'), {'checked': 0, 'deleted_clips': 0, 'failed': 0}]):
            await worker.sweep()
            self.assertEqual(worker.status['failed'], 1)
            await worker.sweep()
            self.assertEqual(worker.status['failed'], 0)
            self.assertIsNotNone(worker.status['last_success'])
