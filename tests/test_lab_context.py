"""Actual experiment results in tutoring; no simulated mastery or hidden tests."""
import copy
import unittest
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient
from learning_agent.course_graph import CourseGraphError
from pliac.main import app
from pliac.lab_context import experiment_context, validate_lab_request
from pliac.ml_lab import MLLab
from pliac.tutor import TeachingProposal
import test_ml_lab


class LabContextTests(unittest.TestCase):
    setUp = test_ml_lab.MLLabTests.setUp
    payload = test_ml_lab.MLLabTests.payload
    act = test_ml_lab.MLLabTests.act
    run_model = test_ml_lab.MLLabTests.run_model

    def context(self):
        graph = self.store.load_graph()
        return experiment_context(graph, self.store._read_learner(self.student)["workspace"], MLLab.binding(graph))

    def test_actual_results_have_no_seed_unseen_hints_or_test_metrics(self):
        self.act("start", scene="space")
        run = self.run_model(4)
        context = self.context()
        self.assertEqual(context["active"]["runs"][0]["result"]["validation_accuracy"], run["result"]["validation_accuracy"])
        self.assertEqual(context["active"]["task"]["id"], "inspect")
        self.assertNotIn("seed", str(context))
        self.assertNotIn("test_accuracy", str(context))
        self.assertEqual(context["active"]["hints"], {})
        self.assertNotIn("hints", context["active"]["task"])
        self.assertIsNone(context["active"]["final"])

    def test_home_continuation_is_read_only_private_and_version_aware(self):
        from pliac.reading_position import recent_reading
        self.act("start", scene="space")
        before = self.store._read_learner(self.student)
        result = recent_reading(self.default, self.student)["items"]
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["kind"], "lab")
        self.assertEqual(result[0]["session_id"], self.lab.view(self.student)["active"]["id"])
        self.assertGreater(result[0]["updated_at"], 0)
        self.assertFalse(result[0]["restart_required"])
        self.assertEqual(recent_reading(self.default, "other-student")["items"], [])
        with patch("pliac.ml_lab.VERSION", "synthetic-new-contract"):
            self.assertTrue(recent_reading(self.default, self.student)["items"][0]["restart_required"])
        self.assertEqual(self.store._read_learner(self.student), before)

    def test_archive_keeps_old_round_observations_without_private_seed(self):
        from pliac.archive import learning_archive
        self.act("start", scene="space")
        run = self.run_model(4)
        self.act("check", answer={"target": "receipt"})
        old = self.lab.view(self.student)["active"]
        with patch("pliac.ml_lab.VERSION", 2):
            self.act("start", scene="space")
        before = self.store._read_learner(self.student)
        archive = learning_archive(self.default, self.student)
        items = archive["courses"][0]["items"]
        self.assertEqual(len(items), 2)
        historic = next(item for item in items if item["id"] == old["id"])["lab"]
        self.assertEqual(historic["runs"][0]["validation_accuracy"], run["result"]["validation_accuracy"])
        self.assertEqual(historic["checks"][0]["feedback"], old["checks"][0]["feedback"])
        self.assertIsNone(historic["test_accuracy"])
        self.assertNotIn("seed", str(archive))
        self.assertNotIn("hint_texts", str(archive))
        self.assertEqual(before, self.store._read_learner(self.student))
        self.assertEqual(learning_archive(self.default, "other-student")["courses"], [])

    def test_home_continuation_excludes_finished_or_unmapped_experiments(self):
        from pliac.ml_lab import recent_lab
        self.act("start", scene="space")
        learner = self.store._read_learner(self.student)
        learner["workspace"]["ml_lab"]["sessions"][0]["final"] = {"synthetic": True}
        with patch.object(self.store, "_read_learner", return_value=learner):
            self.assertEqual(recent_lab(self.store, self.student), [])
        with patch.object(MLLab, "binding", side_effect=CourseGraphError("missing mapping", 409)):
            self.assertEqual(recent_lab(self.store, self.student), [])

    def test_old_version_and_wrong_session_are_not_current_context(self):
        self.act("start", scene="space")
        graph = copy.deepcopy(self.store.load_graph()); graph["version"] += 1
        context = experiment_context(graph, self.store._read_learner(self.student)["workspace"], MLLab.binding(graph))
        self.assertIsNone(context["active"])
        with self.assertRaises(CourseGraphError):
            validate_lab_request({"lab": self.context()}, "foreign-session")

    def test_failed_help_does_not_record_assistance(self):
        self.act("start", scene="space")
        ident = self.lab.view(self.student)["active"]["id"]
        request = self.payload(node_id="sample", message="解释实验", lab_session_id=ident)
        with patch("learning_agent.api.store", self.default), patch("pliac.tutor_api.configured_api", return_value=None), patch("pliac.tutor_api.generate_teaching", AsyncMock(side_effect=CourseGraphError("synthetic failure", 502))), TestClient(app) as client:
            result = client.post("/api/tutor/reply?course_id=ml_acceptance_demo", json=request)
        self.assertEqual(result.status_code, 502)
        self.assertEqual(self.lab.view(self.student)["active"]["hints"], {})

    def test_changed_contract_rejects_context_and_help_before_model_call(self):
        self.act("start", scene="space")
        ident = self.lab.view(self.student)["active"]["id"]
        request = self.payload(node_id="sample", message="解释实验", lab_session_id=ident)
        model = AsyncMock()
        with patch("pliac.lab_context.VERSION", "synthetic-new-contract", create=True):
            self.assertIsNone(self.context()["active"])
            with patch("learning_agent.api.store", self.default), patch("pliac.tutor_api.generate_teaching", model), TestClient(app) as client:
                result = client.post("/api/tutor/reply?course_id=ml_acceptance_demo", json=request)
            self.assertEqual(result.status_code, 409)
        model.assert_not_awaited()
        self.assertEqual(self.lab.view(self.student)["active"]["hints"], {})

    def test_contract_change_during_generation_does_not_record_help(self):
        self.act("start", scene="space")
        from pliac.lab_context import record_lab_help
        workspace = self.store._read_learner(self.student)["workspace"]
        before = copy.deepcopy(workspace)
        with patch("pliac.lab_context.VERSION", "synthetic-new-contract", create=True), self.assertRaises(CourseGraphError):
            record_lab_help(workspace, workspace["ml_lab"]["active_id"], "synthetic-turn")
        self.assertEqual(workspace, before)

    def test_many_runs_are_bounded_and_truncation_is_explicit(self):
        self.act("start", scene="space")
        for depth in range(8):
            self.run_model(depth)
        active = self.context()["active"]
        self.assertEqual(active["run_count"], 8)
        self.assertEqual(len(active["runs"]), 6)
        self.assertTrue(active["runs_truncated"])

    def test_lab_help_is_saved_once_and_not_a_diagnosis(self):
        self.act("start", scene="space")
        self.run_model(1)
        ident = self.lab.view(self.student)["active"]["id"]
        request = self.payload(node_id="sample", message="解释当前实验结果", lab_session_id=ident)
        output = TeachingProposal(response="这是已保存的训练与验证结果。", target_node_id="sample", action="probe",
            rationale="根据当前实验讨论", blocks=[], question="这些数据各自用于什么？", uncertainty="合成模型仅验证工程")
        model = AsyncMock(return_value=(output, {"model": "synthetic"}))
        with patch("learning_agent.api.store", self.default), patch("pliac.tutor_api.configured_api", return_value=None), patch("pliac.tutor_api.generate_teaching", model), TestClient(app) as client:
            first = client.post("/api/tutor/reply?course_id=ml_acceptance_demo", json=request)
            self.assertEqual(first.status_code, 200, first.text)
            self.assertEqual(client.post("/api/tutor/reply?course_id=ml_acceptance_demo", json=request).status_code, 200)
        self.assertTrue(model.call_args.args[0]["lab_help"])
        self.assertEqual(model.await_count, 1)
        learner = self.store._read_learner(self.student)
        session = learner["workspace"]["ml_lab"]["sessions"][-1]
        self.assertEqual(len(session["tutor_help"]), 1)
        self.assertEqual(session["hints"]["inspect"], 1)
        self.assertEqual(learner["diagnoses"], [])


if __name__ == "__main__":
    unittest.main()
