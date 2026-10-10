"""Synthetic fixed-rubric assessments; no real learners or claimed model validity."""
import json
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, patch

from test_learning_workspace import platform_fixture, publish_synthetic
from learning_agent.course_graph import CourseGraphStore, CourseGraphError
from pliac.assessment import AssessmentService
from pliac.tutor import AssessmentProposal
from pliac.main import app
from fastapi.testclient import TestClient


class AssessmentTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        seed = root / "seed.json"
        seed.write_text(json.dumps(platform_fixture()), encoding="utf-8")
        self.store = CourseGraphStore(seed, root / "records")
        publish_synthetic(self.store)
        self.service = AssessmentService(self.store)
        self.proposal = AssessmentProposal(criteria=[{"criterion_id": "0", "outcome": "met",
            "quote": "synthetic answer", "reason": "Synthetic criterion met"}],
            feedback="Synthetic assessment only", follow_up_question="")

    def payload(self, **fields):
        return {"student_id": "synthetic", "course_version": self.store.load_graph()["version"],
            "expected_version": self.store.load_learner("synthetic")["version"],
            "request_id": uuid.uuid4().hex, **fields}

    def start(self):
        state = self.service.start(self.payload(node_id="a"))
        self.assertNotIn("TEACHER_ONLY", json.dumps(state))
        record = state["workspace"]["assessments"][-1]
        self.assertNotIn("answer_key", record)
        self.assertNotIn("TEACHER_ONLY", json.dumps(self.store.view("synthetic")))
        return record["id"]

    def submit(self, ident):
        payload = self.payload(assessment_id=ident, answer="synthetic answer")
        self.service.submit(payload)
        self.service.submit(payload)
        self.assertEqual(len(self.store.load_learner("synthetic")["evidence"]), 1)

    def test_independent_evidence_persists_without_human_review(self):
        ident = self.start()
        self.submit(ident)
        state = self.service.save_result(self.payload(assessment_id=ident), self.proposal, {"model": "synthetic"})
        self.assertEqual(state["learner"]["states"]["a"]["status"], "mastered")
        diagnosis = state["learner"]["diagnoses"][-1]
        self.assertNotIn("reviewer", diagnosis)
        self.assertEqual(diagnosis["review_status"], "model_verified")

    def test_repeated_question_is_not_independent(self):
        self.start()
        ident = self.start()
        self.submit(ident)
        state = self.service.save_result(self.payload(assessment_id=ident), self.proposal, {})
        self.assertEqual(state["workspace"]["assessments"][-1]["result"]["status"], "assisted_success")
        self.assertNotEqual(state["learner"]["states"]["a"]["status"], "mastered")

    def add_synthetic_turn(self, ident, stamp):
        def apply(graph, learner, workspace):
            workspace.setdefault("tutor_turns", []).append({"request_id": ident, "created_at": stamp,
                "node_id": "a", "message": "synthetic help", "course_version": graph["version"],
                "proposal": {"target_node_id": "a", "blocks": [], "response": "synthetic explanation"}})
        self.service._mutate(self.payload(), "synthetic_test_turn", apply)

    def test_prior_help_same_timestamp_does_not_taint_new_task(self):
        stamp = "2026-10-10T00:00:00Z"
        self.add_synthetic_turn("before-task", stamp)
        with patch.object(self.store, "_stamp", return_value=stamp):
            ident = self.start()
            self.submit(ident)
        record = self.service.assessment_snapshot("synthetic", ident)[0]
        self.assertEqual(record["prompt_level"], 0)
        self.assertEqual(record["assistance_turn_ids"], [])
        self.assertEqual(record["assistance_policy"], "saved-order-v1")

    def test_help_after_task_with_backwards_clock_is_recorded(self):
        ident = self.start()
        self.add_synthetic_turn("after-task", "2000-01-01T00:00:00Z")
        self.submit(ident)
        state = self.service.save_result(self.payload(assessment_id=ident), self.proposal, {})
        record = state["workspace"]["assessments"][-1]
        self.assertEqual(record["assistance_turn_ids"], ["after-task"])
        self.assertEqual(record["result"]["status"], "assisted_success")
        self.assertEqual(self.store.load_learner("synthetic")["evidence"][-1]["context"]["assistance_turn_ids"], ["after-task"])

    def test_legacy_task_keeps_timestamp_policy(self):
        ident = self.start()
        def remove_snapshot(graph, learner, workspace):
            workspace["assessments"][-1].pop("prior_tutor_turn_ids")
        self.service._mutate(self.payload(), "synthetic_legacy_task", remove_snapshot)
        self.add_synthetic_turn("legacy-help", "2099-01-01T00:00:00Z")
        self.submit(ident)
        record = self.service.assessment_snapshot("synthetic", ident)[0]
        self.assertEqual(record["assistance_policy"], "legacy-time-v1")
        self.assertEqual(record["assistance_turn_ids"], ["legacy-help"])

    def test_false_quote_does_not_commit_diagnosis(self):
        ident = self.start()
        self.submit(ident)
        self.proposal.criteria[0].quote = "invented student text"
        with self.assertRaises(CourseGraphError):
            self.service.save_result(self.payload(assessment_id=ident), self.proposal, {})
        learner = self.store.load_learner("synthetic")
        self.assertEqual(len(learner["evidence"]), 1)
        self.assertEqual(learner["diagnoses"], [])

    def test_api_failure_preserves_submission_and_retry_finishes(self):
        with patch("learning_agent.api.store", self.store), TestClient(app) as client:
            first = client.post("/api/tutor/assessment/start", json=self.payload(node_id="a"))
            self.assertEqual(first.status_code, 200, first.text)
            ident = first.json()["workspace"]["assessments"][-1]["id"]
            saved = client.post("/api/tutor/assessment/submit", json=self.payload(assessment_id=ident, answer="synthetic answer"))
            self.assertEqual(saved.status_code, 200, saved.text)
            payload = self.payload(assessment_id=ident)
            with patch("pliac.tutor_api.configured_api", return_value=None), patch("pliac.tutor_api.evaluate_answer", AsyncMock(side_effect=CourseGraphError("synthetic failure", 502))):
                self.assertEqual(client.post("/api/tutor/assessment/evaluate", json=payload).status_code, 502)
            self.assertEqual(self.service.assessment_snapshot("synthetic", ident)[0]["answer"], "synthetic answer")
            model = AsyncMock(return_value=(self.proposal, {"model": "synthetic"}))
            with patch("pliac.tutor_api.configured_api", return_value=None), patch("pliac.tutor_api.evaluate_answer", model):
                result = client.post("/api/tutor/assessment/evaluate", json=payload)
                self.assertEqual(result.status_code, 200, result.text)
                self.assertEqual(client.post("/api/tutor/assessment/evaluate", json=payload).status_code, 200)
                self.assertEqual(model.await_count, 1)


if __name__ == "__main__":
    unittest.main()
