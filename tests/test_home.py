"""Read-only public previews and account-bound progress; synthetic temporary stores."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
import uuid
from unittest.mock import patch

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from learning_agent import api
from learning_agent.course_catalog import resolve_course
from learning_agent.course_graph import CourseGraphStore
from pliac.main import app
from pliac.workspace import LearningWorkspace


class HomeTests(unittest.TestCase):
    def setUp(self):
        temp = self.enterContext(tempfile.TemporaryDirectory())
        self.folder = Path(temp)
        self.store = CourseGraphStore(output_dir=self.folder / "course")
        self.enterContext(patch.object(api, "store", self.store))
        self.enterContext(patch.object(app.state, "auth_required", True, create=True))
        self.enterContext(patch.object(app.state, "account_directory", self.folder / "accounts", create=True))
        self.client = self.enterContext(TestClient(app))

    def test_guest_browses_without_creating_records_or_exposing_private_apis(self):
        for path in ("/", "/courses", "/preview?course_id=ml_acceptance_demo",
                     "/api/explore/courses", "/api/explore/preview?course_id=ml_acceptance_demo",
                     "/static/math/katex.min.js"):
            self.assertEqual(self.client.get(path).status_code, 200, path)
        self.assertFalse(self.store.output_dir.exists())
        self.assertFalse((self.folder / "accounts").exists())
        for path in ("/api/home/progress", "/api/learning", "/api/courses", "/api/handouts",
                     "/api/course-graph/teacher/export", "/api/assistant/profile", "/api/explore/private"):
            self.assertEqual(self.client.get(path).status_code, 401, path)
        for path in ("/api/explore/courses", "/api/explore/preview", "/api/learning/onboard"):
            self.assertEqual(self.client.post(path, json={}).status_code, 401, path)
        response = self.client.get("/learn?course_id=ml_acceptance_demo", follow_redirects=False)
        self.assertEqual(response.status_code, 303)
        self.assertIn("%2Flearn%3Fcourse_id%3Dml_acceptance_demo", response.headers["location"])

    def test_unpublished_and_newer_draft_fields_never_enter_public_preview(self):
        graph = self.store.load_graph("draft")
        ident = graph["id"]
        response = self.client.get("/api/explore/preview", params={"course_id": ident})
        self.assertEqual(response.status_code, 404)
        self.store.publish(graph["version"], "synthetic-test", "synthetic public test", personal_use=True)
        graph["title"] = "PRIVATE DRAFT TITLE"
        graph["nodes"][0]["description"] = "PRIVATE DRAFT TEXT"
        self.store.save_graph(graph, graph["version"])
        for path in ("/api/explore/courses", "/api/explore/preview?course_id=" + ident):
            response = self.client.get(path)
            self.assertEqual(response.status_code, 200, response.text)
            self.assertNotIn("PRIVATE DRAFT", response.text)
        for value in ("../private", "nonexistent", "..\\private"):
            self.assertIn(self.client.get("/api/explore/preview", params={"course_id": value}).status_code, (400, 404))

    def test_preview_omits_assessment_and_record_fields_and_escapes_authored_markup(self):
        result = self.client.get("/api/explore/preview?course_id=ml_acceptance_demo").json()
        self.assertIn("验收", result["course"]["label"])
        def keys(value):
            if isinstance(value, dict):
                return set(value) | set().union(*(keys(v) for v in value.values()))
            if isinstance(value, list):
                return set().union(*(keys(v) for v in value))
            return set()
        self.assertFalse(keys(result) & {"answer_key", "expected_answer", "check_task", "rubric", "student_id", "workspace", "source_ids"})
        graph = self.store.load_graph("draft")
        graph["nodes"][0]["lesson_content"] = [{"heading": "Synthetic", "text": '<img src=x onerror=alert(1)> **safe** $x^2$ [link](javascript:alert(1))'}]
        saved = self.store.save_graph(graph, graph["version"])["graph"]
        self.store.publish(saved["version"], "synthetic", "synthetic", personal_use=True)
        html = self.client.get("/api/explore/preview", params={"course_id": graph["id"]}).json()["nodes"][0]["paragraphs"][0]["html"]
        self.assertNotIn("<img", html)
        self.assertNotIn("<a ", html)
        self.assertIn("<strong>safe</strong>", html)
        self.assertIn('data-tex="x^2"', html)

    def test_progress_uses_session_identity_and_does_not_treat_reading_as_passed(self):
        alice = self.client.post("/api/account/register", json={"username": "alice", "password": "synthetic-password"}).json()["user"]
        store = resolve_course(self.store, "ml_acceptance_demo")
        workspace = LearningWorkspace(store)
        payload = dict(student_id=alice["student_id"], course_version=1, expected_version=0, request_id=uuid.uuid4().hex)
        state = workspace.onboard(payload)
        payload.update(expected_version=state["learner"]["version"], request_id=uuid.uuid4().hex)
        state = workspace.next_lesson(payload)
        response = self.client.get("/api/home/progress")
        self.assertEqual(response.headers["cache-control"], "no-store")
        own = next(c for c in response.json()["courses"] if c["course_id"] == "ml_acceptance_demo")
        self.assertEqual((own["studied"], own["passed"], own["current"]), (1, 0, True))
        self.assertEqual(own["current_title"], state["current_lesson"]["title"])
        with TestClient(app) as bob:
            bob.post("/api/account/register", json={"username": "bob", "password": "synthetic-password"})
            self.assertEqual(bob.get("/api/home/progress", params={"student_id": alice["student_id"]}).status_code, 403)
            other = next(c for c in bob.get("/api/home/progress").json()["courses"] if c["course_id"] == "ml_acceptance_demo")
            self.assertEqual((other["studied"], other["passed"], other["onboarded"]), (0, 0, False))


if __name__ == "__main__":
    unittest.main()
