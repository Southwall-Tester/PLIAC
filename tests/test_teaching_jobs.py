"""Durable generation failure/recovery tests, without live model charges."""
import asyncio
import os
import tempfile
import unittest
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from learning_agent.course_graph import CourseGraphError
from pliac.teaching_jobs import TeachingJobs, durable_generation, close_teaching_jobs
from pliac.tutor import TeachingProposal


class TeachingJobTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = SimpleNamespace(output_dir=Path(self.temp.name))
        self.body = {"student_id": "synthetic", "request_id": "job-one", "expected_version": 0}
        self.context = {"intent": "reply", "message": "synthetic question"}
        self.proposal = TeachingProposal(response="synthetic explanation", target_node_id="a", action="explain",
                                        rationale="synthetic", blocks=[], question="", uncertainty="test only")

    async def asyncTearDown(self):
        await close_teaching_jobs()

    async def test_disconnect_keeps_call_and_retry_reads_durable_result(self):
        started, finish = asyncio.Event(), asyncio.Event()
        calls = 0

        async def model():
            nonlocal calls
            calls += 1
            started.set()
            await finish.wait()
            return self.proposal, {"model": "synthetic"}

        request = asyncio.create_task(durable_generation(self.store, self.body, self.context, model))
        await started.wait()
        with self.assertRaises(CourseGraphError) as running:
            await durable_generation(self.store, self.body, self.context, model)
        self.assertEqual(running.exception.status_code, 409)
        request.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await request
        finish.set()
        jobs = TeachingJobs(self.store)
        for _ in range(100):
            if jobs.status("synthetic", "job-one")["status"] == "generated":
                break
            await asyncio.sleep(.01)
        self.assertEqual(jobs.status("synthetic", "job-one")["status"], "generated")
        result = await durable_generation(self.store, self.body, self.context, model)
        self.assertEqual(result[0], self.proposal)
        self.assertEqual(calls, 1)
        self.assertNotIn("proposal", jobs.status("synthetic", "job-one"))
        with self.assertRaises(CourseGraphError):
            jobs.status("other-student", "job-one")

    async def test_failure_has_bounded_explicit_retries(self):
        model = AsyncMock(side_effect=CourseGraphError("synthetic failure", 502))
        for _ in range(4):
            with self.assertRaises(CourseGraphError):
                await durable_generation(self.store, self.body, self.context, model)
        self.assertEqual(model.await_count, 3)
        self.assertEqual(TeachingJobs(self.store).status("synthetic", "job-one")["status"], "failed")

    async def test_process_capacity_spans_courses_preserves_cache_and_disconnect_slot(self):
        other = SimpleNamespace(output_dir=Path(self.temp.name) / 'other-course')
        cached_body = {**self.body, 'request_id': 'cached'}
        quick = AsyncMock(return_value=(self.proposal, {}))
        await durable_generation(other, cached_body, self.context, quick)
        started, finish = asyncio.Event(), asyncio.Event()
        async def slow():
            started.set()
            await finish.wait()
            return self.proposal, {}
        with patch.dict(os.environ, {'PLIAC_TEACHING_MAX_ACTIVE_PER_PROCESS': '1'}):
            task = asyncio.create_task(durable_generation(self.store, self.body, self.context, slow))
            await started.wait()
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
            for _ in range(2):
                with self.assertRaises(CourseGraphError) as error:
                    await durable_generation(other, self.body, self.context, quick)
                self.assertEqual(error.exception.status_code, 429)
            with TeachingJobs(other).connection() as db:
                self.assertEqual(db.execute('SELECT COUNT(*) FROM jobs WHERE request=?', ('job-one',)).fetchone()[0], 0)
            value = await durable_generation(other, cached_body, self.context, quick)
            self.assertEqual(value[0], self.proposal)
            self.assertEqual(quick.await_count, 1)
            finish.set()
            from pliac import teaching_jobs
            for _ in range(100):
                if teaching_jobs._active_generations == 0:
                    break
                await asyncio.sleep(.01)
            self.assertEqual(teaching_jobs._active_generations, 0)
            await durable_generation(other, self.body, self.context, quick)
            self.assertEqual(quick.await_count, 2)

    async def test_process_capacity_releases_on_error_and_shutdown(self):
        from pliac import teaching_jobs
        with patch.dict(os.environ, {'PLIAC_TEACHING_MAX_ACTIVE_PER_PROCESS': '1'}):
            with self.assertRaises(RuntimeError):
                await durable_generation(self.store, self.body, self.context, AsyncMock(side_effect=RuntimeError('synthetic')))
            self.assertEqual(teaching_jobs._active_generations, 0)
            started = asyncio.Event()
            async def slow():
                started.set()
                await asyncio.Event().wait()
            task = asyncio.create_task(durable_generation(self.store, self.body, self.context, slow))
            await started.wait()
            await close_teaching_jobs()
            with self.assertRaises(asyncio.CancelledError):
                await task
            self.assertEqual(teaching_jobs._active_generations, 0)

    async def test_invalid_process_capacity_does_not_claim_attempt(self):
        model = AsyncMock(return_value=(self.proposal, {}))
        for value in ('0', '65', 'invalid'):
            with patch.dict(os.environ, {'PLIAC_TEACHING_MAX_ACTIVE_PER_PROCESS': value}):
                with self.assertRaises(CourseGraphError) as error:
                    await durable_generation(self.store, self.body, self.context, model)
                self.assertEqual(error.exception.status_code, 503)
        model.assert_not_awaited()
        with TeachingJobs(self.store).connection() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM jobs').fetchone()[0], 0)

    async def test_changed_context_cannot_reuse_result(self):
        model = AsyncMock(return_value=(self.proposal, {}))
        await durable_generation(self.store, self.body, self.context, model)
        with self.assertRaises(CourseGraphError):
            await durable_generation(self.store, self.body, {"message": "changed"}, model)
        self.assertEqual(model.await_count, 1)

    async def test_shutdown_marks_running_call_interrupted(self):
        started = asyncio.Event()

        async def model():
            started.set()
            await asyncio.Event().wait()

        request = asyncio.create_task(durable_generation(self.store, self.body, self.context, model))
        await started.wait()
        await close_teaching_jobs()
        with self.assertRaises(asyncio.CancelledError):
            await request
        self.assertEqual(TeachingJobs(self.store).status("synthetic", "job-one")["status"], "interrupted")

    async def test_lost_lease_stops_old_generator_without_overwriting_new_owner(self):
        started, cancelled = asyncio.Event(), asyncio.Event()
        async def model():
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()
        with patch('pliac.teaching_jobs.HEARTBEAT_SECONDS', .01):
            task = asyncio.create_task(durable_generation(self.store, self.body, self.context, model))
            await started.wait()
            jobs = TeachingJobs(self.store)
            with jobs.connection() as db:
                db.execute("UPDATE jobs SET owner='new-owner', result=NULL")
            await asyncio.wait_for(cancelled.wait(), 1)
            with self.assertRaises(CourseGraphError) as error:
                await task
            self.assertEqual(error.exception.status_code, 409)
            with jobs.connection() as db:
                row = db.execute('SELECT owner,status,result FROM jobs').fetchone()
                self.assertEqual(tuple(row), ('new-owner', 'running', None))

    async def test_timeout_cancels_generator_marks_failure_and_releases_capacity(self):
        cancelled = asyncio.Event()
        async def model():
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()
        with patch('pliac.teaching_jobs.GENERATION_SECONDS', .02):
            with self.assertRaises(CourseGraphError) as error:
                await durable_generation(self.store, self.body, self.context, model)
        self.assertEqual(error.exception.status_code, 504)
        self.assertTrue(cancelled.is_set())
        self.assertEqual(TeachingJobs(self.store).status('synthetic', 'job-one')['status'], 'failed')
        from pliac import teaching_jobs
        self.assertEqual(teaching_jobs._active_generations, 0)

    async def test_expired_worker_is_fenced_and_recoverable(self):
        jobs = TeachingJobs(self.store)
        owner, _ = jobs.claim("synthetic", "job-one", "fingerprint")
        with jobs.connection() as db:
            db.execute("UPDATE jobs SET updated=0")
        self.assertEqual(jobs.status("synthetic", "job-one")["status"], "interrupted")
        new_owner, _ = jobs.claim("synthetic", "job-one", "fingerprint")
        with self.assertRaises(CourseGraphError):
            jobs.update("synthetic", "job-one", owner, "generated", {"stale": True})
        jobs.update("synthetic", "job-one", new_owner, "generated", {"new": True})
        self.assertEqual(jobs.claim("synthetic", "job-one", "fingerprint")[1], {"new": True})

    async def test_two_store_instances_cannot_claim_same_live_request(self):
        jobs_a, jobs_b = TeachingJobs(self.store), TeachingJobs(self.store)
        results = await asyncio.gather(
            asyncio.to_thread(jobs_a.claim, "synthetic", "job-one", "same"),
            asyncio.to_thread(jobs_b.claim, "synthetic", "job-one", "same"), return_exceptions=True)
        self.assertEqual(sum(isinstance(result, tuple) for result in results), 1)
        self.assertEqual(sum(isinstance(result, CourseGraphError) for result in results), 1)

    async def test_course_capacity_is_atomic_and_does_not_spend_retries(self):
        jobs = TeachingJobs(self.store)
        with patch.dict(os.environ, {"PLIAC_TEACHING_MAX_ACTIVE_PER_COURSE": "1"}):
            results = await asyncio.gather(*[
                asyncio.to_thread(TeachingJobs(self.store).claim, "synthetic", f"capacity-{i}", "same")
                for i in range(5)], return_exceptions=True)
            successes = [i for i, result in enumerate(results) if isinstance(result, tuple)]
            self.assertEqual(len(successes), 1)
            self.assertEqual(sum(isinstance(result, CourseGraphError) and result.status_code == 429 for result in results), 4)
            with jobs.connection() as db:
                self.assertEqual(db.execute("SELECT COUNT(*),SUM(attempts) FROM jobs").fetchone()[:], (1, 1))
            winner = successes[0]
            jobs.update("synthetic", f"capacity-{winner}", results[winner][0], "generated", {"cached": True})
            owner, _ = jobs.claim("synthetic", "next", "same")
            self.assertEqual(jobs.claim("synthetic", f"capacity-{winner}", "same")[1], {"cached": True})
            jobs.update("synthetic", "next", owner, "failed")
            blocker, _ = jobs.claim("synthetic", "blocker", "same")
            with self.assertRaises(CourseGraphError) as error:
                jobs.claim("synthetic", "next", "same")
            self.assertEqual(error.exception.status_code, 429)
            self.assertEqual(jobs.status("synthetic", "next")["attempts"], 1)
            jobs.update("synthetic", "blocker", blocker, "interrupted")
            jobs.claim("synthetic", "next", "same")
            self.assertEqual(jobs.status("synthetic", "next")["attempts"], 2)

    async def test_invalid_capacity_rejects_before_model_and_expired_lease_frees_slot(self):
        model = AsyncMock(return_value=(self.proposal, {}))
        with patch.dict(os.environ, {"PLIAC_TEACHING_MAX_ACTIVE_PER_COURSE": "0"}):
            with self.assertRaises(CourseGraphError):
                await durable_generation(self.store, self.body, self.context, model)
        model.assert_not_awaited()
        jobs = TeachingJobs(self.store)
        with patch.dict(os.environ, {"PLIAC_TEACHING_MAX_ACTIVE_PER_COURSE": "1"}):
            jobs.claim("synthetic", "expired", "same")
            with jobs.connection() as db:
                db.execute("UPDATE jobs SET updated=0")
            await durable_generation(self.store, self.body, self.context, model)
        self.assertEqual(model.await_count, 1)
