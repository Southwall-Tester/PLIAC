"""Memory is a source index, not a second source of mastery truth."""
import unittest
import test_assessment
from test_learning_workspace import publish_synthetic
from pliac.assessment import AssessmentService
from pliac.memory import recall_memory


class MemoryTests(unittest.TestCase):
    setUp = test_assessment.AssessmentTests.setUp
    payload = test_assessment.AssessmentTests.payload

    def test_persisted_summary_has_real_source_ids_and_respects_course_change(self):
        service = AssessmentService(self.store)
        state = service.start(self.payload(node_id="a"))
        ident = state["workspace"]["assessments"][-1]["id"]
        service.submit(self.payload(assessment_id=ident, answer="synthetic answer"))
        state = service.save_result(self.payload(assessment_id=ident), self.proposal, {"model": "synthetic"})
        memory = state["workspace"]["memory"]
        node = memory["nodes"]["a"]
        self.assertEqual(node["status"], "mastered")
        self.assertEqual(node["recent_evidence_ids"], [state["learner"]["evidence"][0]["id"]])
        self.assertEqual(node["recent_diagnosis_ids"], [state["learner"]["diagnoses"][0]["id"]])
        self.assertEqual(self.store._read_learner("synthetic")["workspace"]["memory"], memory)
        self.assertEqual(recall_memory(self.store.load_graph(), self.store.load_learner("synthetic"), {"b"})["nodes"], {})
        graph = self.store.load_graph("draft")
        graph["nodes"][0]["description"] += " synthetic changed definition"
        publish_synthetic(self.store, graph)
        current = service.view("synthetic")
        self.assertEqual(current["workspace"]["memory"]["nodes"]["a"]["status"], "uncertain")
        self.assertTrue(current["workspace"]["memory"]["nodes"]["a"]["version_changed"])
        self.assertEqual(len(current["learner"]["diagnoses"]), 1)

    def test_open_task_memory_does_not_create_mastery(self):
        state = AssessmentService(self.store).start(self.payload(node_id="a"))
        memory = state["workspace"]["memory"]["nodes"]["a"]
        self.assertEqual(memory["evidence_count"], 0)
        self.assertEqual(memory["diagnosis_count"], 0)
        self.assertEqual(memory["pending_assessments"][0]["status"], "open")
        self.assertNotEqual(memory["status"], "mastered")
