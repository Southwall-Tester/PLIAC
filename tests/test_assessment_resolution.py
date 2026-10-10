"""Independent retests resolve only covered prior automatic diagnoses."""
import copy
import unittest

import test_assessment
from test_learning_workspace import publish_synthetic
from pliac.tutor import AssessmentProposal, teaching_context
from pliac.reports import StageReports
from pliac.personal_export import export_body


class AssessmentResolutionTests(unittest.TestCase):
    setUp = test_assessment.AssessmentTests.setUp
    payload = test_assessment.AssessmentTests.payload

    def prepare_retest(self, rubric=None):
        graph = self.store.load_graph("draft")
        node = next(item for item in graph["nodes"] if item["id"] == "a")
        node["retest_tasks"] = [{"id": "retest-a", "version": 1, "question": "New independent synthetic question",
                                 "rubric": rubric or node["check_task"]["rubric"], "hint_levels": ["a", "b", "c", "d"]}]
        publish_synthetic(self.store, graph)

    def start(self):
        return self.service.start(self.payload(node_id="a"))["workspace"]["assessments"][-1]["id"]

    def finish(self, ident, passed):
        self.service.submit(self.payload(assessment_id=ident, answer="synthetic answer"))
        record, _, _ = self.service.assessment_snapshot("synthetic", ident)
        proposal = AssessmentProposal(criteria=[{"criterion_id": item["id"], "outcome": "met" if passed else "not_met",
            "quote": "synthetic answer", "reason": "Synthetic criterion check"} for item in record["rubric"]],
            feedback="Synthetic success" if passed else "Synthetic problem", follow_up_question="")
        return self.service.save_result(self.payload(assessment_id=ident), proposal, {"model": "synthetic"})

    def test_new_independent_full_coverage_resolves_without_deleting_history(self):
        self.prepare_retest()
        first = self.finish(self.start(), False)
        old = copy.deepcopy(first["learner"]["diagnoses"][0])
        state = self.finish(self.start(), True)
        self.assertEqual(state["learner"]["states"]["a"]["status"], "mastered")
        self.assertEqual(state["learner"]["diagnoses"][0], old)
        self.assertEqual(state["learner"]["diagnoses"][-1]["resolves_diagnosis_ids"], [old["id"]])
        self.assertEqual(len(state["learner"]["evidence"]), 2)
        self.assertTrue(state["workspace"]["memory"]["nodes"]["a"]["recent_feedback"][0]["resolved"])
        report = StageReports(self.store).save(self.payload())["workspace"]["stage_reports"][-1]
        self.assertIn("已由后续独立核验覆盖", export_body("report", report))

    def test_different_criterion_does_not_resolve_old_problem(self):
        self.prepare_retest(["A different synthetic criterion"])
        self.finish(self.start(), False)
        state = self.finish(self.start(), True)
        self.assertEqual(state["learner"]["diagnoses"][-1]["resolves_diagnosis_ids"], [])
        self.assertEqual(state["learner"]["states"]["a"]["status"], "uncertain")

    def test_changed_node_uses_new_evidence_without_rewriting_old_diagnosis(self):
        first = self.finish(self.start(), False)
        old = copy.deepcopy(first["learner"]["diagnoses"][0])
        graph = self.store.load_graph("draft")
        node = next(item for item in graph["nodes"] if item["id"] == "a")
        node["description"] += " Revised synthetic teaching scope."
        node["check_task"]["question"] = "New version independent synthetic question"
        publish_synthetic(self.store, graph)
        before = self.service.view("synthetic")
        self.assertTrue(before["learner"]["states"]["a"]["version_changed"])
        state = self.finish(self.start(), True)
        self.assertEqual(state["learner"]["states"]["a"]["status"], "mastered")
        self.assertEqual(state["learner"]["diagnoses"][0], old)
        self.assertEqual(state["learner"]["diagnoses"][-1]["resolves_diagnosis_ids"], [])
        feedback = state["workspace"]["memory"]["nodes"]["a"]["recent_feedback"]
        self.assertFalse(feedback[0]["applicable"])
        self.assertFalse(feedback[0]["resolved"])
        self.assertTrue(feedback[-1]["applicable"])
        report = StageReports(self.store).save(self.payload())["workspace"]["stage_reports"][-1]
        self.assertFalse(report["diagnoses"][0]["applicable"])
        self.assertTrue(report["diagnoses"][-1]["applicable"])
        self.assertIn("不参与当时的掌握或冲突判断", export_body("report", report))
        context = teaching_context(self.store.load_graph(), self.store.load_learner("synthetic"), "a", "下一步")
        self.assertFalse(context["diagnoses"][0]["applicable"])
        self.assertTrue(context["diagnoses"][-1]["applicable"])
        self.assertEqual(context["diagnoses"][0]["course_version"], old["course_version"])

    def test_unrelated_course_update_keeps_same_node_conflict(self):
        self.prepare_retest(["Different existing criterion"])
        self.finish(self.start(), False)
        graph = self.store.load_graph("draft")
        next(item for item in graph["nodes"] if item["id"] == "b")["description"] += " Unrelated update."
        publish_synthetic(self.store, graph)
        state = self.finish(self.start(), True)
        self.assertEqual(state["learner"]["states"]["a"]["status"], "uncertain")

    def test_exposed_question_does_not_resolve_old_problem(self):
        self.finish(self.start(), False)
        state = self.finish(self.start(), True)
        self.assertEqual(state["workspace"]["assessments"][-1]["result"]["status"], "assisted_success")
        self.assertEqual(state["learner"]["diagnoses"][-1]["resolves_diagnosis_ids"], [])

    def test_assisted_new_question_does_not_resolve_old_problem(self):
        self.prepare_retest()
        self.finish(self.start(), False)
        ident = self.start()
        def expose(graph, learner, workspace):
            record = next(item for item in workspace["assessments"] if item["id"] == ident)
            workspace.setdefault("exposures", {})[record["task_key"]] = 1
        self.service._mutate(self.payload(), "synthetic_help", expose)
        state = self.finish(ident, True)
        self.assertEqual(state["learner"]["diagnoses"][-1]["resolves_diagnosis_ids"], [])

    def test_task_opened_before_old_diagnosis_is_not_a_followup(self):
        self.prepare_retest()
        first, second = self.start(), self.start()
        self.finish(first, False)
        state = self.finish(second, True)
        self.assertEqual(state["learner"]["diagnoses"][-1]["resolves_diagnosis_ids"], [])
        self.assertEqual(state["learner"]["states"]["a"]["status"], "uncertain")
