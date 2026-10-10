"""Versioned synthetic learner notes remain distinct from assessment evidence."""
import unittest
import test_assessment
from pliac.notebook import Notebook, relevant_notes
from learning_agent.course_graph import CourseGraphError


class NotebookTests(unittest.TestCase):
    setUp = test_assessment.AssessmentTests.setUp
    payload = test_assessment.AssessmentTests.payload
    def test_notes_revise_recall_and_clear_without_mastery(self):
        notebook = Notebook(self.store)
        payload = self.payload(node_id="a", text="synthetic note")
        notebook.save(payload)
        notebook.save(payload)
        state = notebook.save(self.payload(node_id="a", text="corrected synthetic note"))
        self.assertEqual(len(state["workspace"]["notes"]["a"]), 2)
        learner = self.store.load_learner("synthetic")
        self.assertEqual(relevant_notes(learner, {"a"})[0]["text"], "corrected synthetic note")
        self.assertEqual(relevant_notes(learner, {"b"}), [])
        self.assertEqual(learner["evidence"], [])
        self.assertEqual(learner["diagnoses"], [])
        self.assertEqual(relevant_notes(self.store.load_learner("other"), {"a"}), [])
        notebook.save(self.payload(node_id="a", text=""))
        self.assertEqual(relevant_notes(self.store.load_learner("synthetic"), {"a"}), [])

    def test_false_material_and_stale_save_preserve_notes(self):
        notebook = Notebook(self.store)
        with self.assertRaises(CourseGraphError):
            notebook.save(self.payload(node_id="a", text="note", material_id="not-real"))
        stale = self.payload(node_id="a", text="stale")
        notebook.save(self.payload(node_id="a", text="newer"))
        with self.assertRaises(CourseGraphError):
            notebook.save(stale)
        self.assertEqual(relevant_notes(self.store.load_learner("synthetic"), {"a"})[0]["text"], "newer")
