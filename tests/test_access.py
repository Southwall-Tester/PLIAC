"""Protected real API checks against isolated records, not real student data."""
import json
import os
import tempfile
import time
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from learning_agent.course_graph import CourseGraphStore
from pliac.access import COOKIE, IdentityStore, published_document
from pliac.main import app
from test_learning_workspace import platform_fixture, publish_synthetic


class AccessTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        root = Path(folder.name)
        seed = root / "seed.json"
        seed.write_text(json.dumps(platform_fixture()), encoding="utf-8")
        self.store = CourseGraphStore(seed, root / "records")
        publish_synthetic(self.store)
        for target in (patch("learning_agent.api.store", self.store),
                       patch.dict(os.environ, {"PLIAC_REQUIRE_AUTH": "1", "PLIAC_ADMIN_SECRET": "synthetic-admin-" + "x" * 32})):
            target.start()
            self.addCleanup(target.stop)
        self.identities = IdentityStore(self.store.output_dir)

    def client(self):
        client = TestClient(app, base_url="https://testserver")
        self.addCleanup(client.close)
        return client

    def register(self, client):
        response = client.post("/api/access/anonymous", json={})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def note(self, student, **fields):
        return {"student_id": student, "request_id": uuid.uuid4().hex, "expected_version": 0,
                "course_version": self.store.load_graph()["version"], "node_id": "a", "text": "private learner note"} | fields

    def test_cookie_is_required_and_identity_cannot_be_claimed_by_number(self):
        client = self.client()
        self.assertEqual(client.get("/api/learning?student_id=known").status_code, 401)
        self.assertEqual(client.get("/api/tutor/export/word?student_id=known&kind=report&artifact_id=sample").status_code, 401)
        self.assertEqual(client.post("/api/access/anonymous", json={"student_id": "known"}).status_code, 400)
        created = self.register(client)
        student = created["identity"]["student"]
        self.assertNotEqual(student, "known")
        cookie = client.cookies.get(COOKIE)
        self.assertNotIn(cookie, json.dumps(created))
        self.assertEqual(client.get("/api/access/session").json()["identity"]["student"], student)
        again = self.register(client)
        self.assertEqual(again["identity"]["student"], student)
        self.assertNotIn("recovery_code", again)
        # Only token/code hashes are stored, never their reusable plaintext.
        with self.identities.connection() as db:
            values = str([tuple(row) for row in db.execute("SELECT * FROM identities")])
            values += str([tuple(row) for row in db.execute("SELECT * FROM sessions")])
        self.assertNotIn(cookie, values)
        self.assertNotIn(created["recovery_code"], values)

    def test_textbook_cannot_read_another_students_report(self):
        owner, other = self.client(), self.client()
        student = self.register(owner)['identity']['student']
        stranger = self.register(other)['identity']['student']
        saved = owner.post('/api/tutor/notes', json=self.note(student))
        report = owner.post('/api/tutor/report', json={
            'student_id': student, 'request_id': uuid.uuid4().hex,
            'course_version': self.store.load_graph()['version'],
            'expected_version': saved.json()['learner']['version']})
        self.assertEqual(report.status_code, 200, report.text)
        ident = report.json()['workspace']['stage_reports'][-1]['id']
        params = {'student_id': student, 'report_id': ident}
        self.assertEqual(owner.get('/api/tutor/textbook', params=params).status_code, 200)
        self.assertEqual(other.get('/api/tutor/textbook', params=params).status_code, 403)
        params['student_id'] = stranger
        self.assertEqual(other.get('/api/tutor/textbook', params=params).status_code, 404)

    def test_own_body_reaches_handler_and_foreign_reads_writes_are_denied(self):
        first, second = self.client(), self.client()
        a = self.register(first)["identity"]["student"]
        b = self.register(second)["identity"]["student"]
        saved = first.post("/api/tutor/notes", json=self.note(a))
        self.assertEqual(saved.status_code, 200, saved.text)
        self.assertIn("private learner note", saved.text)
        own = first.get("/api/learning", params={"student_id": a})
        self.assertEqual(own.status_code, 200)
        self.assertEqual(own.headers["cache-control"], "no-store")
        for route in ("/api/learning", "/api/course-graph", "/api/course-graph/learner/export",
                      "/api/ml-lab", "/api/ml-lab/export", "/api/tutor/archive", "/api/tutor/jobs/example",
                      "/api/tutor/export/pdf"):
            with self.subTest(route=route):
                response = second.get(route, params={"student_id": a})
                self.assertEqual(response.status_code, 403, response.text)
                self.assertNotIn("private learner note", response.text)
        for route in ("/api/tutor/notes", "/api/tutor/reply", "/api/tutor/flow", "/api/tutor/assessment/submit", "/api/learning/onboard", "/api/learning/preferences", "/api/ml-lab/start"):
            with self.subTest(write=route):
                self.assertEqual(second.post(route, json=self.note(a)).status_code, 403)
        self.assertEqual(second.get("/api/learning", params=[("student_id", a), ("student_id", b)]).status_code, 403)
        self.assertEqual(second.post("/api/tutor/notes", json=self.note(b)).status_code, 200)
        self.assertEqual(self.store.load_learner(a)["version"], 1)

    def test_management_drafts_and_arbitrary_lab_operations_are_not_student_permissions(self):
        client = self.client()
        student = self.register(client)["identity"]["student"]
        for route in ("/api/learning/teacher", "/api/course-graph/teacher/export", "/api/course-graph/teacher/audit", "/api/documents",
                      "/api/documents/unlinked/source", "/api/course-assets/training-blueprints"):
            self.assertEqual(client.get(route, params={"student_id": student}).status_code, 403, route)
        for route in ("/api/course-graph/diagnoses", "/api/course-graph/evidence", "/api/course-graph/publish", "/api/tutor/activate",
                      "/api/learning/teacher/task", "/api/ml-lab/unreviewed-new-operation"):
            self.assertEqual(client.post(route, json=self.note(student)).status_code, 403, route)
        self.assertEqual(client.get("/api/course-graph?view=draft&view=published").status_code, 403)
        public = client.get("/api/course-graph")
        self.assertEqual(public.status_code, 200)
        self.assertNotIn("TEACHER_ONLY", public.text)

    def test_recovery_rotates_code_and_revokes_every_old_session(self):
        old, restored = self.client(), self.client()
        created = self.register(old)
        student = created["identity"]["student"]
        self.assertEqual(old.post("/api/tutor/notes", json=self.note(student)).status_code, 200)
        response = restored.post("/api/access/recover", json={"recovery_code": created["recovery_code"]})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["identity"]["student"], student)
        self.assertEqual(response.json()["identity"]["role"], "learner")
        self.assertNotEqual(response.json()["recovery_code"], created["recovery_code"])
        self.assertEqual(old.get("/api/learning", params={"student_id": student}).status_code, 401)
        self.assertEqual(old.post("/api/access/recover", json={"recovery_code": created["recovery_code"]}).status_code, 403)
        self.assertIn("private learner note", restored.get("/api/learning", params={"student_id": student}).text)
        self.assertEqual(restored.post("/api/access/logout").status_code, 200)
        self.assertIsNone(restored.get("/api/access/session").json()["identity"])
        self.assertEqual(restored.get("/api/courses").status_code, 401)

    def test_admin_is_explicit_and_cross_site_requests_are_rejected(self):
        client = self.client()
        self.register(client)
        self.assertEqual(client.post("/api/access/admin", json={"secret": "错误"}).status_code, 403)
        response = client.post("/api/access/admin", json={"secret": os.environ["PLIAC_ADMIN_SECRET"]})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["identity"]["role"], "admin")
        self.assertIn("HttpOnly", response.headers["set-cookie"])
        self.assertIn("Secure", response.headers["set-cookie"])
        self.assertIn("SameSite=strict", response.headers["set-cookie"])
        self.assertEqual(client.get("/api/course-graph/teacher/export").status_code, 200)
        self.assertEqual(client.post("/api/access/logout", headers={"Origin": "https://foreign.invalid"}).status_code, 403)
        self.assertEqual(client.post("/api/access/logout", headers={"Sec-Fetch-Site": "cross-site"}).status_code, 403)
        self.assertEqual(client.post("/api/access/logout", headers={"Origin": "https://testserver"}).status_code, 200)

    def test_expired_sessions_oversized_requests_and_insecure_shared_access_fail(self):
        client = self.client()
        student = self.register(client)["identity"]["student"]
        for value in ([], "x", None):
            self.assertEqual(client.post("/api/tutor/notes", json=value).status_code, 400)
        self.assertEqual(client.post("/api/tutor/notes", content=b"x" * (2 * 1024 * 1024 + 1)).status_code, 400)
        with self.identities.connection() as db:
            db.execute("UPDATE sessions SET expires=?", (time.time() - 1,))
        self.assertEqual(client.get("/api/learning", params={"student_id": student}).status_code, 401)
        with TestClient(app, base_url="http://testserver") as shared:
            self.assertEqual(shared.post("/api/access/anonymous", json={}).status_code, 403)
        # Real loopback is permitted for local development, not X-Forwarded-For spoofing.
        with TestClient(app, base_url="http://testserver", client=("127.0.0.1", 1)) as local:
            self.assertEqual(local.post("/api/access/anonymous", json={}).status_code, 200)

    def test_identity_attempts_are_bounded_and_old_window_expires(self):
        client = self.client()
        for _ in range(10):
            self.assertEqual(client.post("/api/access/recover", json={"recovery_code": "invalid" * 8}).status_code, 403)
        self.assertEqual(client.post("/api/access/recover", json={"recovery_code": "invalid" * 8}).status_code, 429)
        with self.identities.connection() as db:
            db.execute("UPDATE attempts SET created=?", (time.time() - 601,))
        self.assertEqual(client.post("/api/access/recover", json={"recovery_code": "invalid" * 8}).status_code, 403)

    def test_course_catalog_and_sources_only_use_published_content(self):
        from learning_agent.course_catalog import create_course
        client = self.client()
        self.register(client)
        original = self.store.load_graph()
        draft = self.store.load_graph("draft")
        draft["title"] = "PRIVATE_DRAFT_TITLE"
        draft["nodes"][0]["document_id"] = "unpublished-document"
        draft["nodes"][0]["document_evidence"] = [{"page": 1, "text": "draft text"}]
        self.store.save_graph(draft, draft["version"])
        create_course(self.store, "PRIVATE_NEW_COURSE")
        catalog = client.get("/api/courses")
        self.assertEqual(catalog.status_code, 200)
        self.assertEqual(catalog.json()["courses"][0]["title"], original["title"])
        self.assertNotIn("PRIVATE_", catalog.text)
        self.assertFalse(published_document("unpublished-document"))
        publish_synthetic(self.store)
        self.assertTrue(published_document("unpublished-document"))
        self.assertFalse(published_document("other-document"))

    def test_archive_and_continue_never_disclose_draft_labels(self):
        from pliac.reading_position import ReadingPositions
        client = self.client()
        student = self.register(client)["identity"]["student"]
        original = self.store.load_graph()
        self.assertEqual(client.post('/api/tutor/notes', json=self.note(student)).status_code, 200)
        learner = self.store._read_learner(student)
        learner['workspace']['tutor_turns'] = [{'request_id': 'saved-material', 'course_version': original['version'],
            'created_at': '2026-10-10T00:00:00Z', 'proposal': {'target_node_id': 'a', 'blocks': [{'heading': 'Saved title'}]}}]
        self.store._commit(learner)
        ReadingPositions(self.store).save({'student_id': student, 'material_id': 'saved-material',
            'request_id': 'save-position', 'expected_revision': 0, 'anchor': 'top', 'offset': 0})
        draft = self.store.load_graph('draft')
        draft['title'] = 'PRIVATE_DRAFT_COURSE'
        draft['nodes'][0]['title'] = 'PRIVATE_DRAFT_NODE'
        self.store.save_graph(draft, draft['version'])
        for endpoint in ('/api/tutor/archive', '/api/learning/continue'):
            response = client.get(endpoint, params={'student_id': student})
            self.assertEqual(response.status_code, 200)
            self.assertNotIn('PRIVATE_DRAFT', response.text)
        # Publishing a renamed course must not relabel v1 records as v2 concepts.
        publish_synthetic(self.store)
        archive = client.get('/api/tutor/archive', params={'student_id': student}).json()
        self.assertEqual(archive['courses'][0]['items'][0]['node_title'], original['nodes'][0]['title'])


if __name__ == "__main__":
    unittest.main()
