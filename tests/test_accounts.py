"""Local account authentication and cross-account isolation in temporary stores."""
import json
from pathlib import Path
import sys
import tempfile
import time
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from learning_agent import api
from learning_agent.course_graph import CourseGraphStore
from pliac import accounts
from pliac.main import app
from pliac import margin


class AccountTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.enterContext(patch.object(app.state, "auth_required", True, create=True))
        self.enterContext(patch.object(app.state, "account_directory", self.folder / "account", create=True))
        self.enterContext(patch.object(api, "store", CourseGraphStore(output_dir=self.folder / "course")))
        self.client = self.enterContext(TestClient(app))

    def register(self, username="alice", password="synthetic-secret-42", client=None):
        response = (client or self.client).post("/api/account/register", json={
            "username": username, "password": password, "display_name": username.title()})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()["user"]

    def test_production_defaults_require_login_and_keep_login_assets_public(self):
        self.assertEqual(self.client.get("/api/learning?student_id=anonymous").status_code, 401)
        self.assertEqual(self.client.get("/api/assistant/profile?owner=" + "a" * 32).status_code, 401)
        self.assertEqual(self.client.get("/api/account/me").status_code, 401)
        self.assertEqual(self.client.get("/?course_id=linux", follow_redirects=False).status_code, 200)
        response = self.client.get("/learn?course_id=linux", follow_redirects=False)
        self.assertEqual(response.status_code, 303)
        self.assertTrue(response.headers["location"].startswith("/login?next="))
        for url in ("/login", "/static/login.js", "/static/login.css", "/health"):
            self.assertEqual(self.client.get(url).status_code, 200)
        with patch.object(app.state, "auth_required", False):
            response = self.client.get("/api/account/me")
            self.assertEqual(response.json(), {"authenticated": False, "testing": True})
        self.assertEqual(self.client.get("/api/account/me").status_code, 401)

    def test_registration_hash_cookie_and_stable_identity_across_login(self):
        user = self.register()
        self.assertRegex(user["student_id"], r"^u_[a-f0-9]{24}$")
        self.assertRegex(user["assistant_owner"], r"^[a-f0-9]{32}$")
        self.assertEqual(self.client.get("/api/account/me").json()["user"], user)
        raw = (self.folder / "account/current.json").read_text(encoding="utf-8")
        token = self.client.cookies.get(accounts.COOKIE)
        self.assertNotIn("synthetic-secret-42", raw)
        self.assertNotIn(token, raw)
        self.assertIn("pbkdf2_sha256", raw)
        self.assertEqual(self.client.post("/api/account/logout").status_code, 200)
        self.assertEqual(self.client.get("/api/account/me").status_code, 401)
        result = self.client.post("/api/account/login", json={"username": "ALICE", "password": "synthetic-secret-42"})
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json()["user"], user)
        cookie = result.headers["set-cookie"].lower()
        self.assertIn("httponly", cookie)
        self.assertIn("samesite=lax", cookie)
        self.assertIn("path=/", cookie)
        self.assertNotEqual(token, self.client.cookies.get(accounts.COOKIE))

    def test_accounts_cannot_read_or_write_each_others_owner_or_student_records(self):
        alice = self.register()
        conversation = self.client.post("/api/assistant/conversations", json={})
        self.assertEqual(conversation.status_code, 200, conversation.text)
        ident = conversation.json()["id"]
        with TestClient(app) as other:
            bob = self.register("bob-user", client=other)
            self.assertNotEqual(alice["student_id"], bob["student_id"])
            self.assertNotEqual(alice["assistant_owner"], bob["assistant_owner"])
            for path in (
                f"/api/assistant/conversations/{ident}?owner={alice['assistant_owner']}",
                f"/api/course-graph/learner/export?student_id={alice['student_id']}",
                f"/api/handouts?assistant_owner={alice['assistant_owner']}",
            ):
                self.assertEqual(other.get(path).status_code, 403, path)
            self.assertEqual(other.get(f"/api/assistant/conversations/{ident}").status_code, 404)
            for body in ({"student_id": alice["student_id"]}, {"nested": {"owner": alice["assistant_owner"]}}):
                response = other.post("/api/learning/onboard", json=body)
                self.assertEqual(response.status_code, 403, response.text)
            # The JSON endpoint accepts raw bodies too; a content-type change
            # must not bypass identity enforcement.
            response = other.post("/api/assistant/conversations", content=json.dumps({"owner": alice["assistant_owner"]}),
                                  headers={"Content-Type": "text/plain"})
            self.assertEqual(response.status_code, 403)
            duplicate = f"/api/assistant/profile?owner={bob['assistant_owner']}&owner={alice['assistant_owner']}"
            self.assertEqual(other.get(duplicate).status_code, 403)
        self.assertEqual(self.client.get(f"/api/assistant/conversations/{ident}").status_code, 200)
        self.assertEqual(len(list((self.folder / "course/assistant").glob("*/*.json"))), 1)

    def test_logout_revokes_cookie_replay_and_session_expiration(self):
        self.register()
        token = self.client.cookies.get(accounts.COOKIE)
        self.client.post("/api/account/logout")
        self.client.cookies.set(accounts.COOKIE, token)
        self.assertEqual(self.client.get("/api/account/me").status_code, 401)
        self.client.cookies.clear()
        self.client.post("/api/account/login", json={"username": "alice", "password": "synthetic-secret-42"})
        path = self.folder / "account/current.json"
        state = json.loads(path.read_text(encoding="utf-8"))
        for session in state["sessions"].values():
            session["expires_at"] = time.time() - 1
        path.write_text(json.dumps(state), encoding="utf-8")
        self.assertEqual(self.client.get("/api/account/me").status_code, 401)

    def test_personal_handout_path_ids_check_session_ownership(self):
        alice = self.register()
        store = margin.storage(api.store)
        job = dict(id=uuid.uuid4().hex, student_id=alice["student_id"], status="completed",
                   created_at="2026-10-20T00:00:00+00:00")
        store.save_job(job)
        folder = store.directory("jobs", job["id"])
        (folder / "lesson.json").write_text('{"private":"alice only"}', encoding="utf-8")
        url = f"/api/handouts/{job['id']}/artifacts/lesson.json"
        self.assertEqual(self.client.get(url).status_code, 200)
        with TestClient(app) as other:
            self.register("bob-reader", client=other)
            self.assertEqual(other.get(url).status_code, 404)
            self.assertEqual(other.get(f"/api/handouts/{job['id']}/practice").status_code, 404)
            self.assertEqual(other.post(f"/api/handouts/{job['id']}/cancel").status_code, 404)
            self.assertEqual(other.get(url, params={"student_id": alice["student_id"]}).status_code, 403)

    def test_login_error_is_generic_and_account_paths_use_random_ids(self):
        self.register()
        known = self.client.post("/api/account/login", json={"username": "alice", "password": "invalid-password"})
        unknown = self.client.post("/api/account/login", json={"username": "missing-user", "password": "invalid-password"})
        self.assertEqual(known.status_code, 401)
        self.assertEqual(known.json(), unknown.json())
        for name in ("../../victim", "..\\victim", "/absolute/path", "bad\x00name"):
            response = self.client.post("/api/account/register", json={"username": name, "password": "valid-password"})
            self.assertEqual(response.status_code, 400, response.text)
        self.assertEqual([path.name for path in (self.folder / "account").iterdir()], ["current.json"])
        self.assertEqual(self.client.get("/api/course-graph/learner/export?student_id=../../victim").status_code, 403)

    def test_safe_redirects_and_cross_origin_rejection(self):
        for target in ("//evil.example", "https://evil.example", "/\\evil.example", "/%2f%2fevil.example",
                       "/%0d%0alocation:evil", "/login"):
            self.assertEqual(accounts.safe_return_to(target), "/courses", target)
        self.assertEqual(accounts.safe_return_to("/learn?course_id=linux"), "/learn?course_id=linux")
        result = self.client.post("/api/account/register", json={"username": "alice", "password": "valid-password"},
                                  headers={"Origin": "https://outside.example"})
        self.assertEqual(result.status_code, 403)
        self.register()
        self.assertEqual(self.client.post("/api/assistant/conversations", json={},
                                         headers={"Origin": "https://outside.example"}).status_code, 403)
        result = self.client.post("/api/account/login", json={"username": "alice", "password": "synthetic-secret-42",
                                                              "next": "//evil.example"})
        self.assertEqual(result.json()["next"], "/courses")

    def test_concurrent_registration_keeps_all_accounts_and_sessions(self):
        def register(number):
            return accounts._register(self.folder / "account", {
                "username": f"parallel-{number}", "password": "parallel-test-password"}, "")
        with ThreadPoolExecutor(max_workers=4) as executor:
            created = list(executor.map(register, range(4)))
        state = json.loads((self.folder / "account/current.json").read_text(encoding="utf-8"))
        self.assertEqual(len(state["users"]), 4)
        self.assertEqual(len(state["sessions"]), 4)
        self.assertEqual(len({user["password_hash"]["salt"] for user in state["users"].values()}), 4)
        self.assertEqual(len({user["student_id"] for user, _ in created}), 4)
        self.assertFalse((self.folder / "account/.write.lock").exists())


if __name__ == "__main__":
    unittest.main()
