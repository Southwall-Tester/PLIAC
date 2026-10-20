"""Real persisted progress without fabricated elapsed completion or model text."""
import asyncio
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from learnmargin.models import GenerateRequest
from learnmargin.storage import Store, now
from pliac.handout_progress import ProgressReporter, finish_progress
from pliac import margin
from learning_agent.acceptance_course import build_graph


class ProgressTests(unittest.TestCase):
    def setUp(self):
        temporary = self.enterContext(tempfile.TemporaryDirectory())
        self.store = Store(Path(temporary))
        self.job = dict(id="f" * 32, status="running", created_at=now())
        self.progress = ProgressReporter(self.store, self.job)

    def event(self, ident="one", phase="receiving", **values):
        return dict(request_id=ident, phase=phase, attempt=1, response_chars=40,
                    reasoning_chars=0, transport="sse", **values)

    def test_received_characters_and_elapsed_activity_do_not_inflate_percentage(self):
        self.progress("整理内容总览", 24)
        self.progress.model_event(self.event(phase="request_started"))
        for count in range(100):
            event = self.event()
            event["response_chars"] = count
            self.progress.model_event(event)
        self.assertEqual(self.job["progress"], 24)
        self.assertEqual(self.job["progress_detail"]["request"]["received_chars"], 99)
        self.progress.model_event(self.event(phase="completed"))
        saved = self.store.job(self.job["id"])
        self.assertEqual(saved["progress"], 24)
        self.assertEqual(saved["progress_detail"]["request"]["completed_count"], 1)

    def test_two_sections_retain_independent_work_and_completed_counts(self):
        self.progress("开始编写", 35)
        for index in (1, 2):
            self.progress.detail(dict(task_id=f"section:{index}:draft", label=f"第{index}节初稿",
                                      phase="writing", status="running", section_index=index, section_total=3))
        self.progress.detail(dict(task_id="section:1:draft", label="第1节初稿", phase="writing", status="completed"))
        self.progress.detail(dict(task_id="section:1:validate", label="第1节检查", phase="writing",
                                  status="completed", section_index=1, section_total=3))
        self.assertEqual(self.job["progress_detail"]["current_task"], "第2节初稿")
        self.assertEqual(self.job["progress_detail"]["sections"], {"completed": 1, "total": 3})
        self.progress("完成一个检查", 40)
        self.progress("旧并发步骤回调", 36)
        self.assertEqual(self.job["progress"], 40)
        self.progress("构建图谱", 82)
        self.progress.detail(dict(task_id="late", label="延迟的写作通知", phase="writing", status="completed"))
        self.assertEqual(self.job["progress_detail"]["phase"], "graph")

    def test_requests_aggregate_concurrently_without_storing_payloads(self):
        self.progress("开始编写", 35)
        for ident in ("one", "two"):
            self.progress.model_event(self.event(ident=ident, phase="request_started"))
            self.progress.model_event(self.event(ident=ident, text="SECRET TEXT", reasoning="PRIVATE REASONING",
                                                api_key="SECRET KEY", prompt="PRIVATE PROMPT"))
        current = self.job["progress_detail"]["request"]
        self.assertEqual((current["active_count"], current["received_chars"]), (2, 80))
        self.progress.model_event(self.event(ident="one", phase="completed"))
        current = self.job["progress_detail"]["request"]
        self.assertEqual((current["active_count"], current["received_chars"], current["completed_count"]), (1, 40, 1))
        self.progress.model_event(self.event(ident="two", phase="completed"))
        record = json.dumps(self.store.job(self.job["id"]))
        for secret in ("SECRET TEXT", "PRIVATE REASONING", "SECRET KEY", "PRIVATE PROMPT"):
            self.assertNotIn(secret, record)

    def test_retry_resets_only_its_current_response_and_records_real_attempt(self):
        self.progress("整理内容总览", 24)
        self.progress.model_event(self.event())
        retry = self.event(phase="retry")
        retry.update(attempt=2, response_chars=0)
        self.progress.model_event(retry)
        self.assertEqual(self.job["progress_detail"]["request"]["status"], "retrying")
        self.assertEqual(self.job["progress_detail"]["request"]["attempt"], 2)
        self.assertEqual(self.job["progress_detail"]["request"]["received_chars"], 0)
        self.assertEqual(self.job["progress"], 24)

    def test_nonstreaming_wait_has_no_fabricated_response_and_render_failure_is_separate(self):
        self.progress("整理内容总览", 24)
        event = self.event(phase="receiving", waiting=True)
        event.update(response_chars=0, transport="json")
        self.progress.model_event(event)
        self.assertEqual(self.job["progress_detail"]["request"]["status"], "waiting")
        self.assertIsNone(self.job["progress_detail"]["request"]["last_received_at"])
        self.progress.model_event(self.event(phase="completed"))
        self.progress("排版详细讲义", 88)
        self.job["status"] = "failed"
        self.progress.finish("failed")
        self.assertEqual(self.job["progress_detail"]["steps"][-1]["status"], "failed")
        self.assertEqual(self.job["progress_detail"]["request"]["status"], "completed")

    def test_model_activity_is_bound_to_its_task_without_completing_validation(self):
        self.progress("开始编写", 35)
        for index in (1, 2):
            self.progress.detail(dict(task_id=f"section:{index}:review", label=f"第{index}节审校",
                                      phase="writing", status="running"))
        self.progress.model_event(self.event(phase="retry", task_id="section:2:review"))
        first, second = self.job["progress_detail"]["tasks"]
        self.assertNotIn("model_status", first)
        self.assertEqual(second["model_status"], "retrying")
        self.progress.model_event(self.event(phase="completed", task_id="section:2:review"))
        self.assertEqual(second["model_status"], "completed")
        self.assertEqual(second["status"], "running")
        self.assertEqual(self.job["progress"], 35)

    def test_terminal_state_freezes_clocks_and_never_reports_failed_work_complete(self):
        for status in ("failed", "cancelled", "completed"):
            with self.subTest(status=status):
                job = copy.deepcopy(self.job)
                job.update(stage="排版讲义", status="running")
                reporter = ProgressReporter(self.store, job)
                reporter("正在编写", 35)
                reporter.detail(dict(task_id="s1", label="编写第一节", phase="writing", status="running"))
                reporter.model_event(self.event(phase="request_started"))
                job["status"] = status
                reporter.finish(status)
                frozen = copy.deepcopy(job)
                reporter("迟到的回调", 99)
                reporter.model_event(self.event())
                reporter.finish(status)
                self.assertEqual(job, frozen)
                self.assertEqual(job["progress"], 100 if status == "completed" else 35)
                detail = job["progress_detail"]
                self.assertTrue(detail["finished_at"])
                self.assertEqual(detail["request"]["active_count"], 0)
                self.assertFalse(any(step["status"] == "running" for step in detail["steps"]))

    def test_recovery_stops_saved_progress_and_legacy_jobs_remain_compatible(self):
        self.progress("整理内容总览", 24)
        saved = self.store.job(self.job["id"])
        saved.update(status="failed", stage="任务已中断")
        finish_progress(saved, "failed", "2026-10-20T12:00:00+00:00")
        self.assertEqual(saved["progress_detail"]["finished_at"], "2026-10-20T12:00:00+00:00")
        legacy = dict(status="failed", progress=24)
        finish_progress(legacy, "failed")
        self.assertEqual(legacy, dict(status="failed", progress=24))


class JobProgressTests(unittest.IsolatedAsyncioTestCase):
    async def test_running_job_persists_model_updates_and_cancellation(self):
        class ProviderStub:
            usage = []
            async def __aenter__(self): return self
            async def __aexit__(self, *args): pass
        provider = ProviderStub()
        started = asyncio.Event()
        async def writer(request, docs, store, output, supplied_provider, progress):
            progress("生成总览初稿", 24)
            progress.detail(dict(task_id="plan:draft", label="生成总览初稿", status="running", phase="planning"))
            supplied_provider.observer(dict(request_id="synthetic", phase="receiving", attempt=1,
                                             response_chars=240, reasoning_chars=0, transport="sse"))
            started.set()
            await asyncio.Event().wait()
        docs, origins = margin.materials(build_graph())
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(Path(tmp))
            job = dict(id="e" * 32, status="queued", course_id="synthetic", course_version=1, created_at=now())
            request = GenerateRequest(document_ids=[d.id for d in docs])
            with patch.object(margin, "Provider", return_value=provider), \
                    patch.object(margin, "generate_lesson", side_effect=writer):
                task = asyncio.create_task(margin.run_job(store, job, request, docs, origins))
                await asyncio.wait_for(started.wait(), 5)
                self.assertEqual(job["progress_detail"]["request"]["received_chars"], 240)
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
            saved = store.job(job["id"])
            self.assertEqual(saved["status"], "cancelled")
            self.assertEqual(saved["progress"], 24)
            self.assertTrue(saved["progress_detail"]["finished_at"])
            self.assertEqual(saved["progress_detail"]["steps"][1]["status"], "cancelled")


if __name__ == "__main__":
    unittest.main()
