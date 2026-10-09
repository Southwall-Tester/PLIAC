"""Authored demo course, verified using synthetic learners in temporary stores."""
import json
import sys
import tempfile
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from fastapi.testclient import TestClient
from learning_agent import api
from learning_agent.acceptance_course import AcceptanceCourseStore, DEMO_ID, build_graph
from learning_agent.course_graph import CourseGraphError, CourseGraphStore
from learning_agent.course_catalog import resolve_course
from pliac.main import app
from pliac.workspace import LearningWorkspace


class AcceptanceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.now = datetime(2026, 10, 8, tzinfo=timezone.utc)
        self.default = CourseGraphStore(output_dir=Path(self.temp.name) / "records", clock=lambda: self.now)
        self.store = resolve_course(self.default, DEMO_ID)
        self.workspace = LearningWorkspace(self.store)

    def mutate(self, name, **values):
        payload = self.payload(**values)
        return getattr(self.workspace, name)(payload)

    def payload(self, **values):
        return {"student_id": "synthetic-demo", "course_version": 1,
                "expected_version": self.store.load_learner("synthetic-demo")["version"],
                "request_id": uuid.uuid4().hex, **values}

    def start(self, **values):
        self.mutate("onboard", goals="Synthetic acceptance", **values)
        return self.mutate("next_lesson")["current_lesson"]

    def answer(self, lesson, **values):
        node = self.store._node(self.store.load_graph(), lesson["node_id"])
        choice = self.store.lesson_task(node, lesson)["answer_key"]
        return self.mutate("answer", **{"lesson_id": lesson["id"], "choice_id": choice, **values})

    def test_complete_content_and_readonly_delivery(self):
        graph = build_graph()
        self.assertEqual((len(graph["chapters"]), len(graph["nodes"])), (2, 10))
        for node in graph["nodes"]:
            self.assertEqual(node["review_status"], "draft")
            self.assertEqual(len(node["lesson_content"]), 4)
            for task in self.store.tasks(node):
                self.assertEqual(len(task["options"]), 4)
                self.assertEqual(len(task["hint_levels"]), 4)
                self.assertIn(task["answer_key"], {o["id"] for o in task["options"]})
        self.assertIsNone(self.store.publication()["published_version"])
        self.workspace.view("synthetic-demo")
        self.assertFalse(self.default.output_dir.exists())
        for method, args in ((self.store.save_graph, (graph, 1)), (self.store.publish, (1, "invented", "not allowed"))):
            with self.assertRaises(CourseGraphError):
                method(*args)

    def test_knowledge_relations_are_separate_from_lesson_order(self):
        graph = build_graph()
        self.assertEqual(graph['learning_order'], [n['id'] for n in graph['nodes']])
        edges = {(e['source'], e['target'], e['type']) for e in graph['edges']}
        self.assertIn(('complexity', 'underfit', 'prerequisite'), edges)
        self.assertIn(('complexity', 'overfit', 'prerequisite'), edges)
        self.assertIn(('underfit', 'overfit', 'confusable'), edges)
        self.assertIn(('roles', 'selection', 'prerequisite'), edges)
        self.assertNotIn(('underfit', 'overfit', 'prerequisite'), edges)
        self.assertFalse(any(e['source']=='leakage' and e['target']=='complexity' for e in graph['edges']))
        for edge in graph['edges']:
            self.assertTrue(edge['reason'])
            self.assertTrue(edge['source_ids'])
            self.assertTrue(set(edge['source_ids']) <= {s['id'] for s in graph['sources']})

    def test_atomic_concepts_and_lesson_mapping_are_separate(self):
        course=self.store.load_graph()
        concepts=self.store.concept_map()
        lesson_ids={n['id'] for n in course['nodes']}
        ids={n['id'] for n in concepts['nodes']}
        self.assertFalse(ids & lesson_ids)
        self.assertEqual(len(concepts['nodes']),30)
        self.assertTrue({'训练集','验证集','测试集','特征','标签','训练误差','验证误差'} <= {n['title'] for n in concepts['nodes']})
        sources={s['id'] for s in concepts['sources']}
        for node in concepts['nodes']:
            self.assertTrue(node['lesson_ids'])
            self.assertTrue(set(node['lesson_ids']) <= lesson_ids)
            self.assertTrue(set(node['source_ids']) <= sources)
        self.assertTrue(any(len(n['lesson_ids'])>1 for n in concepts['nodes']))
        for edge in concepts['edges']:
            self.assertTrue({edge['source'],edge['target']} <= ids)
            self.assertTrue(edge['predicate'] and edge['reason'])
            self.assertTrue(set(edge['source_ids']) <= sources)
        # Topic coverage is not a separate diagnosis for each atomic concept.
        view=self.workspace.view('synthetic-demo')
        self.assertFalse(ids & set(view['learner']['states']))

    def test_full_course_reports_and_resume(self):
        self.mutate("onboard", self_assessments={"sample": "confident"})
        for node in build_graph()["nodes"]:
            lesson = self.mutate("next_lesson")["current_lesson"]
            self.assertEqual(lesson["node_id"], node["id"])
            view = self.answer(lesson)
            self.assertEqual(view["learner"]["states"][node["id"]]["status"], "mastered")
        self.assertTrue(all(c["passed"] for c in view["chapters"]))
        for chapter in view["chapters"]:
            self.mutate("report", chapter_id=chapter["chapter_id"])
        resumed = LearningWorkspace(AcceptanceCourseStore(self.default)).view("synthetic-demo")
        self.assertEqual(len(resumed["workspace"]["reports"]), 2)
        self.assertTrue(all(d["review_status"] == "rule_verified" and not d["reviewer"] for d in resumed["learner"]["diagnoses"]))
        self.assertFalse((self.default.output_dir / "learners").exists())
        self.assertFalse((self.store.output_dir / "publication.json").exists())
        self.now += timedelta(days=2)
        expired = self.workspace.view("synthetic-demo")
        self.assertFalse(any(c["passed"] for c in expired["chapters"]))
        self.assertTrue(all(r["passed"] for r in expired["workspace"]["reports"]))

    def test_wrong_answer_remediates_and_alternate_passes(self):
        lesson = self.start()
        view = self.answer(lesson, choice_id="A", status="mastered", passed=True, score=100)
        self.assertEqual(view["learner"]["states"]["sample"]["status"], "needs_review")
        self.assertEqual(view["current_lesson"]["responses"][0]["judgement"]["error_code"], "feature_label_confusion")
        retest = self.mutate("next_lesson")["current_lesson"]
        self.assertEqual(retest["node_id"], "sample")
        self.assertNotEqual(lesson["task"], retest["task"])
        self.assertEqual(self.answer(retest)["learner"]["states"]["sample"]["status"], "mastered")

    def test_hint_correct_requires_fresh_retest(self):
        lesson = self.start()
        self.mutate("hint", lesson_id=lesson["id"])
        view = self.answer(lesson, prompt_level=0)
        self.assertEqual(view["learner"]["states"]["sample"]["status"], "uncertain")
        self.assertEqual(view["learner"]["evidence"][-1]["prompt_level"], 1)
        retest = self.mutate("next_lesson")["current_lesson"]
        view = self.answer(retest)
        self.assertEqual(view["learner"]["states"]["sample"]["status"], "mastered")
        self.assertTrue(view["handbook"][0]["prompted_evidence_ids"])
        # Both solutions have now been exposed; opening again cannot clear assistance.
        repeated = self.mutate("next_lesson", node_id="sample")["current_lesson"]
        self.assertEqual(repeated["prompt_level"], 4)
        self.assertEqual(self.answer(repeated)["learner"]["states"]["sample"]["status"], "uncertain")

    def test_wrong_answer_increases_support_and_allows_retry(self):
        lesson = self.start()
        first = self.answer(lesson, choice_id="A")
        response = first["current_lesson"]["responses"][0]
        self.assertFalse(response["judgement"]["solution_revealed"])
        self.assertEqual(first["current_lesson"]["status"], "retry")
        self.assertEqual(response["prompt_level"], 0)
        second = self.answer(lesson)
        self.assertEqual(second["current_lesson"]["responses"][-1]["prompt_level"], 1)
        self.assertEqual(second["learner"]["states"]["sample"]["status"], "uncertain")
        self.assertTrue(second["current_lesson"]["responses"][-1]["judgement"]["solution_revealed"])
        with self.assertRaises(CourseGraphError):
            self.answer(lesson)

    def test_draft_restores_choice_and_validates_options(self):
        lesson = self.start()
        self.mutate("draft", lesson_id=lesson["id"], choice_id="B", text="Synthetic reasoning")
        view = LearningWorkspace(AcceptanceCourseStore(self.default)).view("synthetic-demo")
        self.assertEqual(view["workspace"]["drafts"][lesson["id"]]["choice_id"], "B")
        with self.assertRaises(CourseGraphError):
            self.answer(lesson, choice_id="not-an-option")
        self.assertEqual(len(self.store.load_learner("synthetic-demo")["evidence"]), 0)

    def test_retry_is_atomic_and_no_answer_leak(self):
        lesson = self.start()
        public = json.dumps(self.workspace.view("synthetic-demo"), ensure_ascii=False)
        self.assertNotIn('"answer_key"', public)
        self.assertNotIn('"hint_levels"', public)
        self.assertNotIn('"explanation"', public)
        payload = self.payload(lesson_id=lesson["id"], choice_id="B")
        first = self.workspace.answer(payload)
        retry = self.workspace.answer(payload)
        self.assertEqual(first["learner"]["version"], retry["learner"]["version"])
        self.assertEqual(len(retry["learner"]["diagnoses"]), 1)
        with self.assertRaises(CourseGraphError):
            self.answer(lesson)

    def test_unresolved_confusion_is_not_erased_by_quiz(self):
        lesson = self.start()
        self.mutate("annotate", lesson_id=lesson["id"], paragraph_id="concept",
                    quote=lesson["paragraphs"][1]["text"], question="Synthetic unresolved confusion")
        self.assertEqual(self.answer(lesson)["learner"]["states"]["sample"]["status"], "uncertain")

    def test_public_api_and_manual_review_cannot_forge_rule_verification(self):
        with patch.object(api, "store", self.default), TestClient(app) as client:
            response = client.get(f"/api/learning?course_id={DEMO_ID}&student_id=api-demo")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["publication"]["delivery_mode"], "acceptance_demo")
            response = client.post(f"/api/course-graph/diagnoses?course_id={DEMO_ID}", json={
                "student_id": "api-demo", "course_version": 1, "node_id": "sample", "status": "mastered",
                "review_status": "rule_verified", "basis": "forged", "evidence_ids": []})
            self.assertEqual(response.status_code, 400)


if __name__ == "__main__":
    unittest.main()
