"""Student-scoped automatic lesson preparation; isolated stores and no model calls."""
import asyncio
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from test_learning_workspace import platform_fixture, publish_synthetic
from learning_agent.course_graph import CourseGraphStore, CourseGraphError
from learnmargin.models import APIConfig
from learnmargin.storage import atomic_json
from pliac import margin


class AutomaticHandoutTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        seed = root / "course.json"
        seed.write_text(json.dumps(platform_fixture()), encoding="utf-8")
        self.course = CourseGraphStore(seed, root / "course")
        self.graph = publish_synthetic(self.course)
        self.node = self.graph["nodes"][0]["id"]
        self.store = margin.storage(self.course)
        self.calls = []
        async def waiting_job(store, job, request, docs, origins):
            self.calls.append((job, request))
            await asyncio.Event().wait()
        self.enterContext(patch.object(margin, "run_job", side_effect=waiting_job))
        self.enterContext(patch.object(margin, "configured_api", return_value=APIConfig(model="synthetic")))
        self.addAsyncCleanup(margin.close_jobs)

    async def prepare(self, student="student-a", **changes):
        payload = {"student_id": student, "scope": {"node_id": self.node}, **changes}
        with patch.object(margin, "_body", new=AsyncMock(return_value=payload)):
            result = await margin.prepare(None, self.course)
        await asyncio.sleep(0)
        return result

    async def finish(self, job, status="completed"):
        task = margin.TASKS.get(job["id"])
        if task:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        job = self.store.job(job["id"])
        job.update(status=status, stage=status, progress=100 if status == "completed" else 24, page_count=1)
        self.store.save_job(job)
        return job

    async def test_entering_twice_reuses_one_active_and_completed_job(self):
        first, duplicate = await asyncio.gather(self.prepare(), self.prepare())
        self.assertEqual(first["id"], duplicate["id"])
        self.assertEqual(1, len(self.calls))
        await self.finish(first)
        again = await self.prepare()
        self.assertEqual(first["id"], again["id"])
        self.assertEqual("completed", again["status"])
        self.assertEqual(1, len(self.store.jobs()))

    async def test_latest_server_profile_and_route_change_create_new_version(self):
        learner = self.course._read_learner("student-a")
        learner["profile"].update(background="刚开始学习", goals="学会解释命令")
        learner["workspace"] = {"journey": {"active": {"route": {"summary": "循序理解",
            "steps": [{"node_id": self.node, "reason": "补充必要基础", "focus": "先例子后概念", "pace": "慢"}]},
            "initial_profile": {"calibration": [{"node_id": self.node, "signal": "needs_support",
                "self_assessment": "confident", "label": "本次核验发现需要补充的理解"}]}}}}
        self.course._commit(learner)
        first = await self.prepare(profile={"background": "客户端伪造"}, profile_context={"goal": "伪造"})
        self.assertEqual("刚开始学习", first["profile_context"]["background"])
        self.assertEqual("慢", first["profile_context"]["current_step"]["pace"])
        self.assertIn("先例子后概念", self.calls[-1][1].learner_notes)
        self.assertIn("本次核验发现需要补充的理解", self.calls[-1][1].learner_notes)
        self.assertNotIn("伪造", self.calls[-1][1].learner_notes)
        await self.finish(first)
        learner = self.course._read_learner("student-a")
        learner["profile"]["background"] = "已经练习过基本概念"
        self.course._commit(learner)
        updated = await self.prepare()
        self.assertNotEqual(first["id"], updated["id"])
        self.assertNotEqual(first["profile_fingerprint"], updated["profile_fingerprint"])
        self.assertEqual("completed", self.store.job(first["id"])["status"])

    async def test_personal_versions_and_artifacts_are_student_scoped(self):
        first, other = await self.prepare(), await self.prepare("student-b")
        self.assertNotEqual(first["id"], other["id"])
        listing = margin.listing(self.course, node_id=self.node, student_id="student-a")
        self.assertEqual([first["id"]], [j["id"] for j in listing["scope_jobs"]])
        self.assertEqual([], margin.listing(self.course, node_id=self.node)["scope_jobs"])
        await self.finish(first)
        path = self.store.directory("jobs", first["id"]) / "lesson.json"
        atomic_json(path, {"title": "private lesson"})
        self.assertEqual(path, Path(margin.artifact(first["id"], "lesson.json", self.course, "student-a").path))
        for student in ("", "student-b"):
            with self.assertRaises(CourseGraphError):
                margin.artifact(first["id"], "lesson.json", self.course, student)
            with self.assertRaises(CourseGraphError):
                margin.listing(self.course, student_id=student, job_id=first["id"])
            with self.assertRaises(CourseGraphError):
                await margin.cancel(first["id"], self.course, student)

    async def test_regenerate_has_mode_feedback_and_request_idempotency(self):
        original = await self.prepare()
        await self.finish(original)
        request = dict(regenerate=True, request_id="request-review", learning_mode="exam_review", feedback="集中比较易混点")
        newer = await self.prepare(**request)
        duplicate = await self.prepare(**request)
        self.assertEqual(newer["id"], duplicate["id"])
        self.assertNotEqual(original["id"], newer["id"])
        self.assertIn("期末复习", self.calls[-1][1].learner_notes)
        self.assertIn("集中比较易混点", self.calls[-1][1].learner_notes)
        self.assertEqual("completed", self.store.job(original["id"])["status"])
        await self.finish(newer)
        self.assertEqual(newer["id"], (await self.prepare())["id"])
        with self.assertRaises(CourseGraphError):
            await self.prepare(**{**request, "feedback": "请求编号已用于不同需要"})

    async def test_failed_preparation_does_not_repeat_until_explicit_regeneration(self):
        first = await self.prepare()
        await self.finish(first, "failed")
        for _ in range(3):
            current = await self.prepare()
            self.assertEqual(first["id"], current["id"])
            self.assertEqual("failed", current["status"])
        self.assertEqual(1, len(self.calls))
        retried = await self.prepare(regenerate=True, request_id="retry-failed")
        self.assertNotEqual(first["id"], retried["id"])
        self.assertEqual("failed", self.store.job(first["id"])["status"])

    async def test_whole_course_and_unconfigured_model_do_not_create_placeholder_jobs(self):
        with self.assertRaises(CourseGraphError):
            await self.prepare(scope={})
        with patch.object(margin, "configured_api", side_effect=CourseGraphError("课程模型尚未配置。", 503)):
            with self.assertRaises(CourseGraphError) as error:
                await self.prepare()
        self.assertEqual(503, error.exception.status_code)
        self.assertEqual([], self.store.jobs())

    async def test_active_assistant_preferences_are_read_from_server(self):
        folder = Path(self.tmp.name) / "assistant"
        atomic_json(folder / "profile" / "current.json", {"enabled": True, "items": [
            {"active": True, "category": "preference", "slot": "format", "value": "先给例子", "basis": "edited"},
            {"active": False, "category": "preference", "slot": "format", "value": "旧偏好", "basis": "explicit"}]})
        with patch("pliac.assistant.root", return_value=folder):
            job = await self.prepare(assistant_owner="a" * 32)
        self.assertEqual("先给例子", job["profile_context"]["conversation_preferences"][0]["value"])
        self.assertNotIn("旧偏好", self.calls[-1][1].learner_notes)
        self.assertIn("先给例子", self.calls[-1][1].learner_notes)


if __name__ == "__main__":
    unittest.main()
