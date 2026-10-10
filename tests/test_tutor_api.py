"""Isolated teaching persistence tests; model output is explicitly simulated."""
import json
import os
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, patch

from test_learning_workspace import platform_fixture, publish_synthetic
from fastapi.testclient import TestClient
from learning_agent.course_graph import CourseGraphStore, CourseGraphError
from pliac.main import app
from pliac.tutor import TeachingProposal, ResourceRecommendation
from pliac.workspace import LearningWorkspace


class TutorAPITests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        path = Path(self.temp.name)
        seed = path / "seed.json"
        seed.write_text(json.dumps(platform_fixture()), encoding="utf-8")
        self.store = CourseGraphStore(seed, path / "records")
        publish_synthetic(self.store)
        self.patch_store = patch("learning_agent.api.store", self.store)
        self.patch_store.start()
        self.addCleanup(self.patch_store.stop)
        self.client = TestClient(app)
        self.addCleanup(self.client.close)
        self.payload = {"student_id": "synthetic", "course_version": self.store.load_graph()["version"],
                        "expected_version": 0, "request_id": uuid.uuid4().hex, "node_id": "a", "message": "请换个例子"}
        self.output = TeachingProposal(response="先确认你对这个概念的理解。", target_node_id="a", action="probe",
                                       rationale="先核验起点", blocks=[], question="请解释这个概念。", uncertainty="尚无独立证据")

    def test_reply_saved_once_without_fabricated_mastery(self):
        model = AsyncMock(return_value=(self.output, {"model": "synthetic-test", "usage": []}))
        with patch("pliac.tutor_api.configured_api", return_value=object()), patch("pliac.tutor_api.generate_teaching", model):
            first = self.client.post("/api/tutor/reply", json=self.payload)
            self.assertEqual(first.status_code, 200, first.text)
            second = self.client.post("/api/tutor/reply", json=self.payload)
            self.assertEqual(second.status_code, 200, second.text)
            self.assertEqual(model.await_count, 1)
            state = second.json()["state"]
            self.assertEqual(len(state["workspace"]["tutor_turns"]), 1)
            self.assertEqual(state["learner"]["diagnoses"], [])
            self.assertNotEqual(state["learner"]["states"]["a"]["status"], "mastered")
            self.assertNotIn("TEACHER_ONLY", json.dumps(model.call_args.args[0]))
            changed = self.client.post("/api/tutor/reply", json=self.payload | {"message": "另一个问题"})
            self.assertEqual(changed.status_code, 409)

    def test_failure_does_not_write_learning_state(self):
        model = AsyncMock(side_effect=CourseGraphError("simulated model unavailable", 502))
        with patch("pliac.tutor_api.configured_api", return_value=object()), patch("pliac.tutor_api.generate_teaching", model):
            response = self.client.post("/api/tutor/reply", json=self.payload)
        self.assertEqual(response.status_code, 502)
        self.assertEqual(self.store.load_learner("synthetic")["version"], 0)

    def test_resource_recommendation_uses_catalog_and_is_saved_once(self):
        graph = self.store.load_graph('draft')
        graph['resources'][0].update(format='video', video_segment={'start_seconds': 12, 'end_seconds': 50})
        publish_synthetic(self.store, graph)
        self.payload['course_version'] = self.store.load_graph()['version']
        self.output.recommended_resources = [ResourceRecommendation(resource_id='r_a', reason='合成建议：先查看相关材料，再用自己的话解释。')]
        model = AsyncMock(return_value=(self.output, {'model': 'synthetic'}))
        with patch('pliac.tutor_api.configured_api', return_value=None), patch('pliac.tutor_api.generate_teaching', model):
            response = self.client.post('/api/tutor/reply', json=self.payload)
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(self.client.post('/api/tutor/reply', json=self.payload).status_code, 200)
        self.assertEqual(model.await_count, 1)
        context = model.call_args.args[0]
        self.assertEqual(context['resources'][0]['id'], 'r_a')
        record = response.json()['turn']
        self.assertEqual(record['resource_catalog'][0]['url'], context['resources'][0]['url'])
        self.assertEqual(len(record['resource_catalog']), 1)
        self.assertEqual(response.json()['state']['learner']['diagnoses'], [])
        from pliac.personal_export import export_body
        html = export_body('material', record)
        self.assertIn('建议的学习材料', html)
        self.assertIn('合成建议', html)
        self.assertIn('12—50 秒', html)
        graph = self.store.load_graph('draft')
        graph['resources'][0]['video_segment'] = {'start_seconds': 70, 'end_seconds': 90}
        publish_synthetic(self.store, graph)
        from pliac.personal_export import saved_snapshot
        historic = saved_snapshot(self.store, 'synthetic', 'material', self.payload['request_id'])
        self.assertIn('12—50 秒', export_body('material', historic))
        self.assertNotIn('70—90 秒', export_body('material', historic))

    def test_invalid_resource_recommendation_is_not_cached_as_success(self):
        from pliac.teaching_jobs import TeachingJobs
        model = AsyncMock(return_value=(self.output, {'model': 'synthetic'}))
        with patch('pliac.tutor_api.configured_api', return_value=None), patch('pliac.tutor_api.generate_teaching', model):
            self.output.recommended_resources = [ResourceRecommendation(resource_id='invented', reason='不存在的推荐')]
            failed = self.client.post('/api/tutor/reply', json=self.payload)
            self.assertEqual(failed.status_code, 502, failed.text)
            self.assertEqual(self.store.load_learner('synthetic')['version'], 0)
            self.assertEqual(TeachingJobs(self.store).status('synthetic', self.payload['request_id'])['status'], 'failed')
            self.output.recommended_resources = [ResourceRecommendation(resource_id='r_a', reason='合成有效材料')]
            self.assertEqual(self.client.post('/api/tutor/reply', json=self.payload).status_code, 200)
            self.assertEqual(model.await_count, 2)

    def test_busy_course_preserves_request_and_retry_after_capacity_returns(self):
        from pliac.teaching_jobs import TeachingJobs
        jobs = TeachingJobs(self.store)
        model = AsyncMock(return_value=(self.output, {"model": "synthetic"}))
        with patch.dict(os.environ, {"PLIAC_TEACHING_MAX_ACTIVE_PER_COURSE": "1"}), patch("pliac.tutor_api.configured_api", return_value=object()), patch("pliac.tutor_api.generate_teaching", model):
            owner, _ = jobs.claim("another-student", "synthetic-blocker", "same")
            response = self.client.post("/api/tutor/reply", json=self.payload)
            self.assertEqual(response.status_code, 429, response.text)
            model.assert_not_awaited()
            self.assertEqual(self.store.load_learner("synthetic")["version"], 0)
            jobs.update("another-student", "synthetic-blocker", owner, "generated", {})
            response = self.client.post("/api/tutor/reply", json=self.payload)
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(model.await_count, 1)
            self.assertEqual(jobs.status("synthetic", self.payload["request_id"])["attempts"], 1)

    def test_concurrent_update_rejects_stale_generation(self):
        async def generate(*args):
            LearningWorkspace(self.store).onboard(self.payload | {"request_id": uuid.uuid4().hex, "goals": "新目标", "self_assessments": {}})
            return self.output, {"model": "synthetic-test"}
        with patch("pliac.tutor_api.configured_api", return_value=object()), patch("pliac.tutor_api.generate_teaching", generate):
            response = self.client.post("/api/tutor/reply", json=self.payload)
        self.assertEqual(response.status_code, 409)
        state = LearningWorkspace(self.store).view("synthetic")
        self.assertEqual(state["learner"]["profile"]["goals"], "新目标")
        self.assertEqual(state["workspace"].get("tutor_turns", []), [])

    def test_invalid_request_rejected_before_model(self):
        with patch("pliac.tutor_api.generate_teaching", AsyncMock()) as model:
            response = self.client.post("/api/tutor/reply", json=self.payload | {"request_id": "../invalid"})
            self.assertEqual(response.status_code, 400)
            model.assert_not_called()

    def test_advance_reads_assessment_evidence_and_is_idempotent(self):
        from pliac.assessment import AssessmentService
        from pliac.tutor import AssessmentProposal
        service = AssessmentService(self.store)
        def payload(**fields):
            return self.payload | {"request_id": uuid.uuid4().hex,
                "expected_version": self.store.load_learner("synthetic")["version"]} | fields
        state = service.start(payload())
        ident = state["workspace"]["assessments"][-1]["id"]
        service.submit(payload(assessment_id=ident, answer="不知道为什么"))
        proposal = AssessmentProposal(criteria=[{"criterion_id": "0", "outcome": "insufficient",
            "quote": "不知道为什么", "reason": "尚未解释概念"}], feedback="需要先补充解释", follow_up_question="")
        service.save_result(payload(assessment_id=ident), proposal, {"model": "synthetic"})
        async def model(context, config):
            self.assertEqual(context["intent"], "advance")
            self.assertEqual(context["evidence"][-1]["text"], "不知道为什么")
            self.assertEqual(context["diagnoses"][-1]["status"], "uncertain")
            self.assertEqual(context["assessments"][-1]["status"], "assessed")
            self.assertNotIn("TEACHER_ONLY", json.dumps(context))
            return self.output, {"model": "synthetic"}
        mock = AsyncMock(side_effect=model)
        request = payload()
        with patch("pliac.tutor_api.configured_api", return_value=None), patch("pliac.tutor_api.generate_teaching", mock):
            response = self.client.post("/api/tutor/advance", json=request)
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json()["turn"]["intent"], "advance")
            self.assertEqual(self.client.post("/api/tutor/advance", json=request).status_code, 200)
            self.assertEqual(mock.await_count, 1)
            self.assertEqual(self.client.post("/api/tutor/reply", json=request).status_code, 409)

    def test_advance_opens_and_resumes_task_without_fabricating_assistance(self):
        from pliac.assessment import AssessmentService
        model = AsyncMock(return_value=(self.output, {"model": "synthetic"}))
        with patch("pliac.tutor_api.configured_api", return_value=None), patch("pliac.tutor_api.generate_teaching", model):
            response = self.client.post("/api/tutor/advance", json=self.payload)
            self.assertEqual(response.status_code, 200, response.text)
            result = response.json()
            ident = result["turn"]["activity"]["id"]
            self.assertEqual(result["state"]["workspace"]["assessments"][0]["id"], ident)
            service = AssessmentService(self.store)
            state = service.submit(self.payload | {"request_id": uuid.uuid4().hex,
                "expected_version": result["state"]["learner"]["version"], "assessment_id": ident, "answer": "synthetic"})
            self.assertEqual(state["learner"]["evidence"][-1]["prompt_level"], 0)
            resumed = self.client.post("/api/tutor/advance", json=self.payload | {
                "request_id": uuid.uuid4().hex, "expected_version": state["learner"]["version"]})
            self.assertEqual(resumed.status_code, 200, resumed.text)
            self.assertEqual(resumed.json()["turn"]["activity"]["id"], ident)
            self.assertEqual(len(resumed.json()["state"]["workspace"]["assessments"]), 1)


if __name__ == "__main__":
    unittest.main()
