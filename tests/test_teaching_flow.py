"""Event-driven teaching with isolated synthetic evidence and mocked generation."""
import json
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient
from learning_agent.course_graph import CourseGraphStore
from pliac.main import app
from pliac.workspace import LearningWorkspace
from pliac.assessment import AssessmentService
from pliac.teaching_flow import TeachingFlow
from pliac.tutor import TeachingProposal, AssessmentProposal
from test_learning_workspace import platform_fixture, publish_synthetic


class TeachingFlowTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        seed = root / "seed.json"
        seed.write_text(json.dumps(platform_fixture()), encoding="utf-8")
        self.store = CourseGraphStore(seed, root / "records")
        publish_synthetic(self.store)
        scope = patch("learning_agent.api.store", self.store)
        scope.start(); self.addCleanup(scope.stop)
        self.client = TestClient(app)
        self.addCleanup(self.client.close)
        self.workspace = LearningWorkspace(self.store)
        self.flow = TeachingFlow(self.store)
        self.assessment = AssessmentService(self.store)
        self.probe = TeachingProposal(response="合成初诊", target_node_id="a", action="probe", rationale="依据目标确认起点", blocks=[], question="请解释", uncertainty="尚无证据")

    def payload(self, **fields):
        return {"student_id": "synthetic", "request_id": uuid.uuid4().hex, "course_version": self.store.load_graph()["version"],
                "expected_version": self.store.load_learner("synthetic")["version"]} | fields

    def begin(self):
        return self.workspace.onboard(self.payload(goals="理解概念", self_assessments={"a": "confident"}, agent_guided=True, start_node_id="a"))

    def pending_request(self):
        trigger = self.workspace.view("synthetic")["workspace"]["teaching_flow"]["pending"]
        return self.payload(trigger_id=trigger["id"], node_id=trigger["node_id"])

    def advance(self, body=None, proposal=None):
        with patch("pliac.tutor_api.configured_api", return_value=None), patch("pliac.tutor_api.generate_teaching", AsyncMock(return_value=(proposal or self.probe, {"model": "synthetic"}))) as model:
            response = self.client.post("/api/tutor/advance", json=body or self.pending_request())
            self.assertEqual(response.status_code, 200, response.text)
            return response.json(), model

    def fail_assessment(self, record):
        self.assessment.submit(self.payload(assessment_id=record["id"], answer="合成错误表达"))
        proposal = AssessmentProposal(criteria=[{"criterion_id": "0", "outcome": "not_met", "quote": "合成错误表达", "reason": "未满足本题标准"}], feedback="需补学", follow_up_question="")
        return self.assessment.save_result(self.payload(assessment_id=record["id"]), proposal, {"model": "synthetic"})

    def test_start_is_not_mastery_and_duplicate_tabs_share_one_trigger(self):
        self.begin()
        request = self.pending_request()
        with patch("pliac.tutor_api.configured_api", return_value=None), patch("pliac.tutor_api.generate_teaching", AsyncMock(return_value=(self.probe, {"model": "synthetic"}))) as model:
            first = self.client.post("/api/tutor/advance", json=request)
            second = self.client.post("/api/tutor/advance", json=request | {"request_id": uuid.uuid4().hex})
        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual(second.status_code, 200, second.text)
        self.assertEqual(model.await_count, 1)
        self.assertEqual(model.call_args.args[0]["trigger"]["reason"], "initial_diagnosis")
        state = second.json()["state"]
        self.assertEqual(len(state["workspace"]["assessments"]), 1)
        self.assertIsNone(state["workspace"]["teaching_flow"]["pending"])
        self.assertEqual(state["learner"]["diagnoses"], [])
        self.assertNotEqual(state["learner"]["states"]["a"]["status"], "mastered")
        self.assertEqual(state["workspace"]["teaching_flow"]["current_turn_id"], first.json()["turn"]["request_id"])

    def test_evaluation_queues_remediation_and_reading_never_supplies_mastery(self):
        self.begin()
        result, _ = self.advance()
        record = result["state"]["workspace"]["assessments"][0]
        state = self.fail_assessment(record)
        self.assertEqual(state["workspace"]["teaching_flow"]["pending"]["reason"], "assessment_evaluated")
        remediation = self.probe.model_copy(update={"action": "remediate", "response": "重新说明"})
        next_step, model = self.advance(proposal=remediation)
        self.assertEqual(model.call_args.args[0]["diagnoses"][-1]["status"], "needs_review")
        before = len(next_step["state"]["learner"]["evidence"])
        knowledge_before = next_step["state"]["learner"]["states"]["a"]["status"]
        state = self.flow.command(self.payload(operation="continue", turn_id=next_step["turn"]["request_id"]))
        self.assertEqual(state["workspace"]["teaching_flow"]["pending"]["reason"], "reading_finished")
        self.assertEqual(len(state["learner"]["evidence"]), before)
        self.assertEqual(state["learner"]["states"]["a"]["status"], knowledge_before)
        self.assertNotEqual(knowledge_before, "mastered")

    def test_pause_during_generation_prevents_late_activity_commit(self):
        self.begin()
        request = self.pending_request()
        async def model(*args):
            self.flow.command(self.payload(operation="pause"))
            return self.probe, {"model": "synthetic"}
        with patch("pliac.tutor_api.configured_api", return_value=None), patch("pliac.tutor_api.generate_teaching", model):
            response = self.client.post("/api/tutor/advance", json=request)
        self.assertEqual(response.status_code, 409)
        state = self.workspace.view("synthetic")
        self.assertEqual(state["workspace"].get("tutor_turns", []), [])
        self.assertFalse(state["workspace"]["teaching_flow"]["enabled"])
        self.flow.command(self.payload(operation="resume", node_id="a"))
        resumed, _ = self.advance()
        self.assertEqual(resumed["turn"]["trigger"]["reason"], "initial_diagnosis")

    def test_old_goal_task_cannot_override_new_goal_and_forged_trigger_fails(self):
        self.begin()
        result, _ = self.advance()
        record = result["state"]["workspace"]["assessments"][0]
        self.workspace.onboard(self.payload(goals="另一个目标", agent_guided=True, start_node_id="b"))
        pending = self.pending_request()
        self.fail_assessment(record)
        self.assertEqual(self.pending_request()["trigger_id"], pending["trigger_id"])
        with patch("pliac.tutor_api.generate_teaching", AsyncMock()) as model:
            response = self.client.post("/api/tutor/advance", json=self.pending_request() | {"trigger_id": "forged"})
            self.assertEqual(response.status_code, 409)
            model.assert_not_called()

    def test_paused_completed_task_is_queued_for_resume_and_cannot_be_skipped(self):
        self.begin()
        result, _ = self.advance()
        response = self.client.post("/api/tutor/flow", json=self.payload(operation="continue", turn_id=result["turn"]["request_id"]))
        self.assertEqual(response.status_code, 409)
        self.flow.command(self.payload(operation="pause"))
        state = self.fail_assessment(result["state"]["workspace"]["assessments"][0])
        self.assertFalse(state["workspace"]["teaching_flow"]["enabled"])
        self.assertEqual(state["workspace"]["teaching_flow"]["pending"]["reason"], "assessment_evaluated")
        state = self.flow.command(self.payload(operation="resume", node_id="a"))
        self.assertTrue(state["workspace"]["teaching_flow"]["enabled"])
        self.assertEqual(state["workspace"]["teaching_flow"]["pending"]["reason"], "assessment_evaluated")

    def test_course_update_cannot_resume_an_old_activity_as_current(self):
        self.begin()
        result, _ = self.advance()
        old_version = result["turn"]["course_version"]
        publish_synthetic(self.store)
        state = self.flow.command(self.payload(operation="resume", node_id="a"))
        pending = state["workspace"]["teaching_flow"]["pending"]
        self.assertGreater(pending["course_version"], old_version)
        self.assertIsNone(state["workspace"]["teaching_flow"]["current_turn_id"])
        self.assertEqual(state["workspace"]["tutor_turns"][0]["course_version"], old_version)


if __name__ == "__main__":
    unittest.main()
