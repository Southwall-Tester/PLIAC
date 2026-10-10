"""Cross-course artifact index reads isolated synthetic learner records only."""
import unittest
import uuid
import test_assessment
from pliac.archive import learning_archive
from pliac.notebook import Notebook
from learning_agent.acceptance_course import AcceptanceCourseStore


class ArchiveTests(unittest.TestCase):
    setUp = test_assessment.AssessmentTests.setUp
    payload = test_assessment.AssessmentTests.payload

    def test_multiple_courses_latest_notes_and_student_separation(self):
        Notebook(self.store).save(self.payload(node_id="a", text="first note"))
        Notebook(self.store).save(self.payload(node_id="a", text="revised note"))
        demo = AcceptanceCourseStore(self.store)
        node = demo.load_graph()["nodes"][0]["id"]
        Notebook(demo).save({"student_id": "synthetic", "course_version": 1, "expected_version": 0,
            "request_id": uuid.uuid4().hex, "node_id": node, "text": "demo note"})
        archive = learning_archive(self.store, "synthetic")
        self.assertEqual(len(archive["courses"]), 2)
        notes = [item for course in archive["courses"] for item in course["items"]]
        self.assertEqual({item["text"] for item in notes}, {"revised note", "demo note"})
        before = set(self.store.output_dir.rglob("*"))
        self.assertEqual(learning_archive(self.store, "other")["courses"], [])
        self.assertEqual(before, set(self.store.output_dir.rglob("*")))

    def test_assessment_index_contains_result_not_private_answers(self):
        from pliac.assessment import AssessmentService
        service = AssessmentService(self.store)
        service.start(self.payload(node_id="a"))
        archive = learning_archive(self.store, "synthetic")
        item = archive["courses"][0]["items"][0]
        self.assertEqual(item["kind"], "assessment")
        self.assertEqual(item["status"], "open")
        self.assertNotIn("TEACHER_ONLY", str(archive))
        self.assertNotIn("answer_key", str(archive))

    def test_missing_historical_snapshot_never_falls_back_to_draft(self):
        from unittest.mock import patch
        from learning_agent.course_graph import CourseGraphError
        Notebook(self.store).save(self.payload(node_id="a", text="saved learner text"))
        original = self.store.load_graph
        def unavailable(view="published", version=None):
            if version is not None:
                raise CourseGraphError("synthetic missing version", 409)
            return original(view)
        with patch.object(self.store, "load_graph", side_effect=unavailable):
            item = learning_archive(self.store, "synthetic")["courses"][0]["items"][0]
        self.assertEqual(item["node_title"], "历史知识点")
        self.assertEqual(item["text"], "saved learner text")
