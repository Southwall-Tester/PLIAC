"""Study conditions and evidence provenance, with isolated synthetic learners."""
import tempfile
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from learning_agent.acceptance_course import AcceptanceCourseStore
from learning_agent.course_graph import CourseGraphStore, CourseGraphError
from pliac.workspace import LearningWorkspace


class StudyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.now = datetime(2026, 10, 9, tzinfo=timezone.utc)
        self.store = AcceptanceCourseStore(CourseGraphStore(output_dir=Path(self.temp.name), clock=lambda: self.now))
        self.service = LearningWorkspace(self.store)
        self.call("onboard")

    def call(self, operation, **fields):
        return getattr(self.service, operation)({"student_id": "study-test", "course_version": 1,
            "expected_version": self.store.load_learner("study-test")["version"], "request_id": uuid.uuid4().hex, **fields})

    def lesson(self, node="roles"):
        return self.call("next_lesson", node_id=node, study_protocol=1)["current_lesson"]

    def answer(self, lesson):
        node = self.store._node(self.store.load_graph(), lesson["node_id"])
        key = self.store.lesson_task(node, lesson)["answer_key"]
        return self.call("answer", lesson_id=lesson["id"], choice_id=key, confidence="sure")

    def test_reading_correct_is_not_independent_and_recall_new_task_is(self):
        lesson = self.lesson()
        result = self.answer(lesson)
        self.assertEqual(result["learner"]["states"]["roles"]["status"], "uncertain")
        lesson = self.lesson()
        self.call("study", lesson_id=lesson["id"], action="recall")
        result = self.answer(lesson)
        self.assertEqual(result["learner"]["states"]["roles"]["status"], "mastered")
        record = result["learner"]["evidence"][-1]
        self.assertEqual(record["context"]["confidence"], "sure")
        self.assertTrue(CourseGraphStore._independent(record))

    def test_reopening_and_reclosing_cannot_erase_material_exposure(self):
        lesson = self.lesson()
        for action in ["recall", "read", "recall", "break", "continue"]:
            self.call("study", lesson_id=lesson["id"], action=action, note="回到数据职责")
        result = self.answer(lesson)
        self.assertTrue(result["current_lesson"]["study"]["material_reopened"])
        self.assertEqual(result["learner"]["states"]["roles"]["status"], "uncertain")
        self.assertEqual(result["current_lesson"]["study"]["resume_note"], "回到数据职责")
        self.assertEqual(LearningWorkspace(self.store).view("study-test")["current_lesson"], result["current_lesson"])

    def test_discussion_after_recall_is_assistance(self):
        lesson = self.lesson()
        self.call("study", lesson_id=lesson["id"], action="recall")
        self.call("ask", lesson_id=lesson["id"], text="验证集的作用是什么？")
        result = self.answer(lesson)
        self.assertTrue(result["current_lesson"]["study"]["support_viewed"])
        self.assertEqual(result["learner"]["states"]["roles"]["status"], "uncertain")

    def test_due_retest_advances_interval_and_starts_with_materials_closed(self):
        lesson = self.lesson()
        self.call("study", lesson_id=lesson["id"], action="recall")
        self.answer(lesson)
        self.now += timedelta(days=2)
        lesson = self.lesson()
        self.assertEqual(lesson["study"]["mode"], "recall")
        result = self.answer(lesson)
        state = result["learner"]["states"]["roles"]
        self.assertEqual(state["review_stage"], 1)
        self.assertEqual(state["due_at"], (self.now + timedelta(days=7)).isoformat().replace("+00:00", "Z"))

    def test_cards_preserve_prior_evidence_and_do_not_grant_mastery(self):
        first = self.call("card", node_id="leakage", fields={"trigger": "出现事后字段", "reason": "预测时拿不到"})
        first_id = first["study_activities"]["cards"]["leakage"]["evidence_id"]
        second = self.call("card", node_id="leakage", fields={"trigger": "先确定预测发生时刻"})
        self.assertIn(first_id, {e["id"] for e in second["learner"]["evidence"]})
        self.assertFalse(second["learner"]["diagnoses"])
        self.assertNotEqual(second["learner"]["states"]["leakage"]["status"], "mastered")

    def test_mixed_feedback_is_after_submission_and_separate_from_diagnosis(self):
        self.assertIsNone(self.service.view("study-test")["study_activities"]["mixed_task"])
        for node in ["roles", "partition"]:
            self.answer(self.lesson(node))
        view = self.service.view("study-test")
        task = view["study_activities"]["mixed_task"]
        self.assertNotIn("key", task)
        self.assertNotIn("explanation", task)
        before = view["learner"]["diagnoses"]
        view = self.call("mixed", task_id=task["id"], choice=1, confidence="unsure", reason="验证集用于选择模型")
        self.assertEqual(view["learner"]["diagnoses"], before)
        self.assertTrue(view["study_activities"]["mixed_history"][-1]["correct"])
        with self.assertRaises(CourseGraphError):
            self.call("mixed", task_id=task["id"], choice=1, confidence="sure", reason="重复提交")

    def test_invalid_confidence_does_not_commit_and_old_records_still_read(self):
        lesson = self.lesson()
        revision = self.store.load_learner("study-test")["version"]
        with self.assertRaises(CourseGraphError):
            self.call("answer", lesson_id=lesson["id"], choice_id="A", confidence="made-up")
        self.assertEqual(self.store.load_learner("study-test")["version"], revision)
        old = self.call("next_lesson", node_id="sample")["current_lesson"]
        self.assertNotIn("study", old)
        self.assertEqual(self.answer(old)["learner"]["states"]["sample"]["status"], "mastered")


if __name__ == "__main__":
    unittest.main()
