"""Concurrent explanation assessment and recovery with synthetic model replies."""
import asyncio
import unittest
import uuid
from unittest.mock import AsyncMock, patch

import httpx
import test_assessment
from learning_agent.course_graph import CourseGraphError
from pliac.main import app
from pliac.assessment import AssessmentService


class AssessmentJobTests(unittest.IsolatedAsyncioTestCase):
    setUp = test_assessment.AssessmentTests.setUp
    payload = test_assessment.AssessmentTests.payload

    def saved_answer(self):
        state = self.service.start(self.payload(node_id="a"))
        ident = state["workspace"]["assessments"][-1]["id"]
        self.service.submit(self.payload(assessment_id=ident, answer="synthetic answer"))
        return ident, self.payload(assessment_id=ident)

    async def test_two_tabs_share_model_call_and_only_one_diagnosis(self):
        ident, body = self.saved_answer()
        started, finish = asyncio.Event(), asyncio.Event()
        calls = 0

        async def model(*_):
            nonlocal calls
            calls += 1
            started.set()
            await finish.wait()
            return self.proposal, {"model": "synthetic"}

        with patch("learning_agent.api.store", self.store), patch("pliac.tutor_api.configured_api", return_value=object()), patch("pliac.tutor_api.evaluate_answer", model):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
                first = asyncio.create_task(client.post("/api/tutor/assessment/evaluate", json=body))
                await asyncio.wait_for(started.wait(), 5)
                second_body = body | {"request_id": uuid.uuid4().hex}
                second = await client.post("/api/tutor/assessment/evaluate", json=second_body)
                self.assertEqual(second.status_code, 409, second.text)
                finish.set()
                self.assertEqual((await first).status_code, 200)
                retry = await client.post("/api/tutor/assessment/evaluate", json=second_body)
                self.assertEqual(retry.status_code, 200, retry.text)
                self.assertEqual(len(retry.json()["learner"]["diagnoses"]), 1)
        self.assertEqual(calls, 1)

    async def test_commit_failure_reuses_evaluation_without_model_call(self):
        _, body = self.saved_answer()
        model = AsyncMock(return_value=(self.proposal, {"model": "synthetic"}))
        with patch("learning_agent.api.store", self.store), patch("pliac.tutor_api.configured_api", return_value=object()), patch("pliac.tutor_api.evaluate_answer", model):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
                with patch.object(AssessmentService, "save_result", side_effect=CourseGraphError("synthetic commit unavailable", 503)):
                    failed = await client.post("/api/tutor/assessment/evaluate", json=body)
                self.assertEqual(failed.status_code, 503)
                retry = await client.post("/api/tutor/assessment/evaluate", json=body)
                self.assertEqual(retry.status_code, 200, retry.text)
                self.assertEqual(model.await_count, 1)
                self.assertEqual(len(retry.json()["learner"]["diagnoses"]), 1)

    async def test_false_evidence_is_not_cached_as_success(self):
        _, body = self.saved_answer()
        invalid = self.proposal.model_copy(deep=True)
        invalid.criteria[0].quote = "invented words"
        model = AsyncMock(side_effect=[(invalid, {}), (self.proposal, {})])
        with patch("learning_agent.api.store", self.store), patch("pliac.tutor_api.configured_api", return_value=object()), patch("pliac.tutor_api.evaluate_answer", model):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
                failed = await client.post("/api/tutor/assessment/evaluate", json=body)
                self.assertEqual(failed.status_code, 502)
                self.assertEqual(self.store.load_learner("synthetic")["diagnoses"], [])
                retry = await client.post("/api/tutor/assessment/evaluate", json=body)
                self.assertEqual(retry.status_code, 200, retry.text)
                self.assertEqual(model.await_count, 2)
