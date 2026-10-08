"""Synthetic platform contracts: persistence, evidence provenance and chapter decisions."""
import copy
import json
import sys
import tempfile
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from learning_agent import api
from learning_agent.course_graph import CourseGraphError, CourseGraphStore, validate_graph
from learning_agent.course_catalog import create_course, resolve_course
from learning_agent.main import app
from pliac.workspace import LearningWorkspace
from test_course_graph import fixture


def platform_fixture():
    graph = fixture()
    for node in graph["nodes"]:
        node.update(check_question=f"合成问题：请解释 {node['id']}。", expected_answer="TEACHER_ONLY_ANSWER")
        node["check_task"] = {"id": "check_" + node["id"], "version": 1,
                              "rubric": ["TEACHER_ONLY_RUBRIC"], "hint_levels": [f"HINT_{i}" for i in range(1, 5)]}
    return graph


def publish_synthetic(store, graph=None):
    graph = copy.deepcopy(graph or store.load_graph("draft"))
    for item in [*graph["nodes"], *graph["edges"], *graph["resources"]]:
        item.update(review_status="reviewed", reviewer="Synthetic reviewer",
                    reviewed_at=store._stamp(), review_note="Synthetic fixture " + uuid.uuid4().hex)
    graph = store.save_graph(graph, graph["version"])["graph"]
    store.publish(graph["version"], "Synthetic publisher", "Synthetic test only")
    return graph


class WorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.seed = self.root / "seed.json"
        self.seed.write_text(json.dumps(platform_fixture(), ensure_ascii=False), encoding="utf-8")
        self.now = datetime(2026, 10, 8, tzinfo=timezone.utc)
        self.store = CourseGraphStore(self.seed, self.root / "records", clock=lambda: self.now)
        self.workspace = LearningWorkspace(self.store)
        publish_synthetic(self.store)

    def payload(self, student="synthetic", **values):
        return {"student_id": student, "course_version": self.store.load_graph()["version"],
                "expected_version": self.store.load_learner(student)["version"], "request_id": uuid.uuid4().hex, **values}

    def start(self, student="synthetic", node="a"):
        self.workspace.onboard(self.payload(student, goals="Synthetic goal", self_assessments={"a": "confident"}))
        return self.workspace.next_lesson(self.payload(student, node_id=node))["current_lesson"]

    def answer(self, lesson, **values):
        return self.workspace.answer(self.payload(**{"lesson_id": lesson["id"], "text": "Synthetic answer", **values}))

    def diagnose(self, evidence, status="mastered", **values):
        return self.store.add_diagnosis({"student_id": evidence["student_id"], "course_version": evidence["course_version"],
                                        "node_id": evidence["node_id"], "evidence_ids": [evidence["id"]],
                                        "status": status, "review_status": "reviewed", "reviewer": "Synthetic reviewer",
                                        "basis": "Synthetic explicit review", **values})

    def test_unpublished_blocks_writes_without_changing_legacy_records(self):
        store = CourseGraphStore(self.seed, self.root / "unpublished")
        workspace = LearningWorkspace(store)
        self.assertIsNone(workspace.view("new")["course"])
        self.assertFalse(store.output_dir.exists())
        with self.assertRaises(CourseGraphError):
            workspace.onboard(self.payload(student_id="new", course_version=1, expected_version=0))
        self.assertEqual(store._read_learner("new")["version"], 0)

    def test_self_assessment_and_interest_cannot_prove_mastery(self):
        self.start()
        view = self.workspace.view("synthetic")
        self.assertEqual(view["learner"]["states"]["a"]["status"], "uncertain")
        raw = view["learner"]["evidence"][0]
        with self.assertRaises(CourseGraphError):
            self.diagnose(raw)
        count = len(view["learner"]["evidence"])
        self.workspace.onboard(self.payload(interests=["科幻"], self_assessments={"a": "confident"}))
        self.assertEqual(len(self.store.load_learner("synthetic")["evidence"]), count)

    def test_student_responses_do_not_expose_teacher_material_or_future_hints(self):
        self.start()
        raw = json.dumps(self.workspace.view("synthetic"))
        for secret in ("TEACHER_ONLY_ANSWER", "TEACHER_ONLY_RUBRIC", "HINT_1", "HINT_4"):
            self.assertNotIn(secret, raw)
        self.assertIn("TEACHER_ONLY_ANSWER", json.dumps(self.workspace.teacher_view("synthetic")))

    def test_hint_is_server_owned_and_persists_across_restart_and_new_lesson(self):
        lesson = self.start()
        view = self.workspace.hint(self.payload(lesson_id=lesson["id"], prompt_level=0))
        self.assertEqual(view["current_lesson"]["prompt_level"], 1)
        self.assertNotIn("HINT_2", json.dumps(view))
        restored = LearningWorkspace(CourseGraphStore(self.seed, self.store.output_dir, clock=lambda: self.now))
        lesson = restored.next_lesson(self.payload(node_id="a"))["current_lesson"]
        self.assertEqual(lesson["hints"][0]["text"], "HINT_1")
        raw = restored.answer(self.payload(lesson_id=lesson["id"], text="Correct with help", prompt_level=0))["learner"]["evidence"][-1]
        self.assertEqual(raw["prompt_level"], 1)
        with self.assertRaises(CourseGraphError):
            self.diagnose(raw)

    def test_reversioning_same_question_does_not_erase_hint_exposure(self):
        lesson = self.start()
        self.workspace.hint(self.payload(lesson_id=lesson["id"]))
        graph = self.store.load_graph("draft")
        graph["nodes"][0]["check_task"]["version"] = 2
        publish_synthetic(self.store, graph)
        new = self.workspace.next_lesson(self.payload(node_id="a"))["current_lesson"]
        self.assertEqual(new["prompt_level"], 1)

    def test_hint_ladder_stops_at_four(self):
        lesson = self.start()
        for level in range(1, 5):
            self.assertEqual(self.workspace.hint(self.payload(lesson_id=lesson["id"]))["current_lesson"]["prompt_level"], level)
        with self.assertRaises(CourseGraphError):
            self.workspace.hint(self.payload(lesson_id=lesson["id"]))

    def test_raw_answer_updates_shared_graph_only_after_real_review(self):
        lesson = self.start()
        view = self.answer(lesson)
        evidence = view["learner"]["evidence"][-1]
        self.assertEqual(view["learner"]["states"]["a"]["status"], "uncertain")
        self.assertEqual(evidence["context"]["task_id"], "check_a")
        self.diagnose(evidence)
        view = self.workspace.view("synthetic")
        self.assertEqual(view["learner"]["states"], self.store.view("synthetic")["learner"]["states"])
        self.assertEqual(view["learner"]["states"]["a"]["status"], "uncertain")  # uncited self-assessment still needs review
        view = self.answer(lesson, text="New independent explanation after review")
        self.store.add_diagnosis({"student_id":"synthetic", "course_version":evidence["course_version"], "node_id":"a",
                                 "evidence_ids":[e["id"] for e in view["learner"]["evidence"]], "status":"mastered",
                                 "review_status":"reviewed", "reviewer":"Synthetic reviewer", "basis":"Review both assessment and answer"})
        self.assertEqual(self.workspace.view("synthetic")["learner"]["states"]["a"]["status"], "mastered")

    def test_retry_is_idempotent_even_after_other_writes(self):
        lesson = self.start()
        request = self.payload(lesson_id=lesson["id"], text="Do not duplicate")
        first = self.workspace.answer(request)
        self.workspace.report(self.payload(chapter_id="ch1"))
        second = self.workspace.answer(request)
        self.assertEqual(len(first["learner"]["evidence"]), len(second["learner"]["evidence"]))
        with self.assertRaises(CourseGraphError):
            self.workspace.answer({**request, "text":"Changed operation"})

    def test_concurrent_tabs_cannot_overwrite(self):
        lesson = self.start()
        one = self.payload(lesson_id=lesson["id"], text="one")
        two = {**one, "text":"two", "request_id":uuid.uuid4().hex}
        def save(payload):
            try:
                self.workspace.draft(payload)
                return "saved"
            except CourseGraphError as exc:
                return exc.status_code
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(save, [one, two]))
        self.assertCountEqual(results, ["saved", 409])

    def test_draft_restore_and_old_core_mutations_preserve_workspace(self):
        lesson = self.start()
        self.workspace.draft(self.payload(lesson_id=lesson["id"], text="Unfinished reasoning"))
        before = self.store._read_learner("synthetic")["workspace"]
        self.store.save_profile({"student_id":"synthetic", "interests":["音乐"]})
        restored = LearningWorkspace(CourseGraphStore(self.seed, self.store.output_dir, clock=lambda: self.now)).view("synthetic")
        self.assertEqual(restored["workspace"]["drafts"][lesson["id"]]["text"], "Unfinished reasoning")
        self.assertEqual(before, self.store._read_learner("synthetic")["workspace"])

    def test_atomic_failure_preserves_both_evidence_and_workspace(self):
        from learning_agent import course_graph
        lesson = self.start()
        before = self.store._read_learner("synthetic")
        original = course_graph._atomic_json
        def fail(path, data):
            if path.name == "workspace.json":
                raise OSError("Synthetic interrupted save")
            return original(path, data)
        with patch.object(course_graph, "_atomic_json", side_effect=fail):
            with self.assertRaises(OSError):
                self.answer(lesson)
        self.assertEqual(before, self.store._read_learner("synthetic"))

    def test_course_update_preserves_old_session_but_blocks_new_evidence(self):
        lesson = self.start()
        self.workspace.draft(self.payload(lesson_id=lesson["id"], text="Old draft"))
        graph = self.store.load_graph("draft")
        graph["nodes"][0]["description"] = "Changed concept"
        publish_synthetic(self.store, graph)
        self.assertTrue(self.workspace.view("synthetic")["course_changed"])
        with self.assertRaises(CourseGraphError):
            self.answer(lesson)
        new = self.workspace.next_lesson(self.payload(node_id="a"))
        self.assertEqual(new["workspace"]["drafts"][lesson["id"]]["text"], "Old draft")

    def test_other_learner_cannot_submit_to_session(self):
        lesson = self.start()
        self.start(student="other")
        with self.assertRaises(CourseGraphError):
            self.workspace.answer(self.payload("other", lesson_id=lesson["id"], text="Cross learner"))

    def test_annotation_requires_exact_current_paragraph_and_is_not_mastery(self):
        lesson = self.start()
        request = self.payload(lesson_id=lesson["id"], paragraph_id="concept", quote="invented", question="Why?")
        with self.assertRaises(CourseGraphError):
            self.workspace.annotate(request)
        view = self.workspace.annotate({**request, "quote":"概念说明"})
        self.assertEqual(view["learner"]["evidence"][-1]["source_type"], "annotation")
        self.assertEqual(len(view["handbook"][0]["annotation_evidence_ids"]), 1)

    def test_chapter_rule_has_no_invented_threshold_and_requires_current_evidence(self):
        lesson = self.start(node="b")
        raw = self.answer(lesson)["learner"]["evidence"][-1]
        self.diagnose(raw)
        report = self.workspace.view("synthetic")["chapters"][0]
        self.assertEqual(report["outcome"], "not_configured")
        graph = self.store.load_graph("draft")
        graph["chapters"][0]["completion_policy"] = {"mode":"all_required_mastered", "required_node_ids":["b"],
                                                       "configured_by":"Synthetic teacher", "basis":"Synthetic requirement"}
        publish_synthetic(self.store, graph)
        self.assertTrue(self.workspace.view("synthetic")["chapters"][0]["passed"])
        view = self.workspace.report(self.payload(chapter_id="ch1"))
        self.assertTrue(view["workspace"]["reports"][0]["passed"])
        self.now += timedelta(days=2)
        current = self.workspace.view("synthetic")
        self.assertFalse(current["chapters"][0]["passed"])
        self.assertTrue(current["workspace"]["reports"][0]["passed"])

    def test_chapter_rule_rejects_cross_chapter_and_empty_targets(self):
        graph = self.store.load_graph("draft")
        for ids in ([], ["c"], ["a", "a"]):
            graph["chapters"][0]["completion_policy"] = {"mode":"all_required_mastered", "required_node_ids":ids,
                                                           "configured_by":"Test", "basis":"Test"}
            with self.assertRaises(CourseGraphError):
                validate_graph(graph)

    def test_next_lesson_uses_only_prerequisites_not_confusable_edges(self):
        self.workspace.onboard(self.payload())
        view = self.workspace.next_lesson(self.payload())
        self.assertEqual(view["current_lesson"]["node_id"], "a")
        self.assertIn("reason", view["current_lesson"])
        self.assertIn("policy_version", view["current_lesson"])

    def test_clicked_resource_does_not_become_learning_evidence(self):
        lesson = self.start()
        before = self.store.load_learner("synthetic")
        view = self.workspace.resource(self.payload(lesson_id=lesson["id"], resource_id="r_a"))
        self.assertEqual(view["learner"]["evidence"], before["evidence"])
        self.assertEqual(view["learner"]["states"], before["states"])
        self.assertEqual(len(view["learner"]["resource_uses"]), 1)

    def test_prerequisite_resource_use_records_its_actual_target(self):
        lesson = self.start(node="c")
        view = self.workspace.resource(self.payload(lesson_id=lesson["id"], resource_id="r_a"))
        use = view["learner"]["resource_uses"][-1]
        self.assertEqual(use["node_id"], "a")
        self.assertEqual(use["requested_node_id"], "c")

    def test_read_only_old_records_are_not_migrated_until_a_write(self):
        self.store.save_profile({"student_id":"legacy", "goals":"Existing goal"})
        before = self.store._read_learner("legacy")
        self.assertNotIn("workspace", before)
        view = self.workspace.view("legacy")
        self.assertEqual(view["learner"]["profile"]["goals"], "Existing goal")
        self.assertEqual(before, self.store._read_learner("legacy"))

    def test_api_and_separate_courses(self):
        from fastapi.testclient import TestClient
        with patch.object(api, "store", self.store), TestClient(app) as client:
            self.assertEqual(client.get('/learn').status_code, 200)
            self.assertEqual(client.get('/review').status_code, 200)
            self.assertEqual(client.get('/api/learning', params={"student_id":"../escape"}).status_code, 400)
            payload = self.payload()
            response = client.post('/api/learning/onboard', json=payload)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(client.post('/api/learning/next', json=self.payload()).status_code, 200)
            other = create_course(self.store, "Second course")["course"]["id"]
            before = self.store._read_learner("synthetic")
            self.assertIsNone(client.get('/api/learning', params={"student_id":"synthetic", "course_id":other}).json()["course"])
            self.assertEqual(before, self.store._read_learner("synthetic"))
            self.assertEqual(resolve_course(self.store, other)._read_learner("synthetic")["version"], 0)
            self.assertEqual(client.post('/api/learning/onboard', json={}).status_code, 400)
            self.assertEqual(client.post('/api/learning/nonexistent', json={}).status_code, 404)

    def test_teacher_task_edit_is_versioned_and_requires_new_review(self):
        from fastapi.testclient import TestClient
        with patch.object(api, "store", self.store), TestClient(app) as client:
            old = self.store.load_graph()
            body = {"expected_version":old["version"], "node_id":"a", "question":"New unseen question", "expected_answer":"Reference only",
                    "rubric":["Observable criterion"], "hint_levels":["h1", "h2", "h3", "h4"]}
            response = client.post('/api/learning/teacher/task', json=body)
            self.assertEqual(response.status_code, 200)
            draft = response.json()["graph"]
            self.assertEqual(draft["nodes"][0]["check_task"]["version"], 2)
            self.assertEqual(draft["nodes"][0]["review_status"], "draft")
            self.assertEqual(self.store.load_graph(), old)
            with self.assertRaises(CourseGraphError):
                self.store.publish(draft["version"], "Synthetic publisher", "Must reject stale review")
            self.assertEqual(client.post('/api/learning/teacher/task', json=body).status_code, 409)
            body.update(expected_version=draft["version"], hint_levels=["Only one"])
            self.assertEqual(client.post('/api/learning/teacher/task', json=body).status_code, 400)


if __name__ == "__main__":
    unittest.main()
