"""Synthetic bytes only: no camera opened, no real biometric data collected."""
import base64
import json
import os
import subprocess
import unittest
import uuid
from unittest.mock import patch

from learning_agent.course_graph import CourseGraphError
from pliac.media import MediaStore, capture_policy, validate_clip
import test_assessment
import test_access
from pliac.assessment import AssessmentService


class MediaTests(unittest.TestCase):
    setUp_base = test_assessment.AssessmentTests.setUp
    payload = test_assessment.AssessmentTests.payload

    def setUp(self):
        self.setUp_base()
        self.now = 100000.
        self.media = MediaStore(self.store, clock=lambda: self.now)
        self.env = patch.dict(os.environ, {"PLIAC_MEDIA_ENABLED": "1", "PLIAC_REQUIRE_AUTH": "1", "PLIAC_MEDIA_RETENTION_DAYS": "1", "PLIAC_MEDIA_CONTACT": "synthetic test contact"})
        self.env.start(); self.addCleanup(self.env.stop)
        validation = patch("pliac.media.validate_clip")
        validation.start(); self.addCleanup(validation.stop)
        self.task = self.service.start(self.payload(node_id="a"))["workspace"]["assessments"][-1]["id"]
        self.body = {"student_id": "synthetic", "activity_kind": "assessment", "activity_id": self.task,
                     "request_id": uuid.uuid4().hex, "accepted": True, "policy_version": capture_policy()["version"]}

    def start(self):
        return self.media.start(self.body)["id"]

    def upload(self, ident, **fields):
        # Header marker plus test bytes is a storage fixture, not a playable video.
        return self.media.upload({"student_id": "synthetic", "session_id": ident, "sequence": 0,
            "start_ms": 0, "duration_ms": 5000, "content_base64": base64.b64encode(b"\x1a\x45\xdf\xa3synthetic").decode()} | fields)

    def control(self, ident, operation):
        return self.media.control({"student_id": "synthetic", "session_id": ident, "operation": operation})

    def test_missing_policy_consent_or_real_activity_blocks_start(self):
        for changes in ({"accepted": False}, {"policy_version": "old"}, {"activity_id": "foreign"}):
            with self.assertRaises(CourseGraphError):
                self.media.start(self.body | changes)
        with patch.dict(os.environ, {"PLIAC_MEDIA_RETENTION_DAYS": "0"}):
            self.assertFalse(capture_policy()["enabled"])
            with self.assertRaises(CourseGraphError):
                self.start()

    def test_idempotent_start_and_upload_do_not_change_learning_records(self):
        before = self.store._read_learner("synthetic")
        ident = self.start()
        self.assertEqual(self.start(), ident)
        self.assertEqual(self.upload(ident), self.upload(ident))
        self.assertEqual(len(self.media.view("synthetic", ident)["clips"]), 1)
        self.assertEqual(self.store._read_learner("synthetic"), before)
        with self.assertRaises(CourseGraphError):
            self.upload(ident, duration_ms=1000)
        with self.assertRaises(CourseGraphError):
            self.media.start(self.body | {"request_id": uuid.uuid4().hex})

    def test_pause_stop_revoke_and_foreign_access(self):
        ident = self.start(); self.upload(ident)
        with self.assertRaises(CourseGraphError):
            self.media.read("someone_else", ident, 0)
        self.control(ident, "pause")
        with self.assertRaises(CourseGraphError):
            self.upload(ident, sequence=1, start_ms=5000)
        self.control(ident, "resume"); self.upload(ident, sequence=1, start_ms=5000)
        self.control(ident, "stop")
        self.assertTrue(self.media.read("synthetic", ident, 0))
        with self.assertRaises(CourseGraphError):
            self.control(ident, "resume")
        with patch.dict(os.environ, {"PLIAC_MEDIA_ENABLED": "0"}):
            self.control(ident, "revoke")
        self.assertEqual(self.media.view("synthetic", ident)["clips"], [])
        with self.assertRaises(CourseGraphError):
            self.media.read("synthetic", ident, 0)

    def test_expiry_deletes_bytes_even_when_read_returns_error(self):
        ident = self.start(); self.upload(ident)
        self.now += 86401
        with self.assertRaises(CourseGraphError):
            self.media.read("synthetic", ident, 0)
        with self.media.connection() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM clips").fetchone()[0], 0)
        self.assertEqual(self.media.view("synthetic", ident)["status"], "expired")

    def test_changed_policy_invalid_times_and_overlapping_chunks_rejected(self):
        ident = self.start(); self.upload(ident)
        for fields in ({"start_ms": float("nan")}, {"sequence": True}, {"sequence": 2}, {"sequence": 1, "start_ms": 4000}):
            with self.assertRaises(CourseGraphError):
                self.upload(ident, **fields)
        with patch.dict(os.environ, {"PLIAC_MEDIA_CONTACT": "changed contact"}), self.assertRaises(CourseGraphError):
            self.upload(ident, sequence=1, start_ms=5000)

    def test_revoke_during_decode_prevents_late_write(self):
        ident = self.start()
        with patch("pliac.media.validate_clip", side_effect=lambda _: self.control(ident, "revoke")):
            with self.assertRaises(CourseGraphError):
                self.upload(ident)
        self.assertEqual(self.media.view("synthetic", ident)["clips"], [])


class MediaHTTPTests(unittest.TestCase):
    setUp = test_access.AccessTests.setUp
    client = test_access.AccessTests.client
    register = test_access.AccessTests.register

    def test_logged_in_owner_only_and_revoke_invalidates_download(self):
        first, second = self.client(), self.client()
        student = self.register(first)["identity"]["student"]
        other = self.register(second)["identity"]["student"]
        state = AssessmentService(self.store).start({"student_id": student, "request_id": uuid.uuid4().hex,
            "expected_version": 0, "course_version": self.store.load_graph()["version"], "node_id": "a"})
        task = state["workspace"]["assessments"][-1]["id"]
        with patch.dict(os.environ, {"PLIAC_MEDIA_ENABLED": "1", "PLIAC_MEDIA_RETENTION_DAYS": "1", "PLIAC_MEDIA_CONTACT": "synthetic tester"}), patch("pliac.media.validate_clip"):
            policy = first.get("/api/media/policy").json()
            payload = {"student_id": student, "request_id": uuid.uuid4().hex, "activity_kind": "assessment",
                "activity_id": task, "accepted": True, "policy_version": policy["version"]}
            response = first.post("/api/media/start", json=payload)
            self.assertEqual(response.status_code, 200, response.text)
            ident = response.json()["id"]
            listed = first.get("/api/media/sessions", params={"student_id": student})
            self.assertEqual([item["id"] for item in listed.json()], [ident])
            self.assertEqual(second.get("/api/media/sessions", params={"student_id": other}).json(), [])
            self.assertEqual(second.get("/api/media/sessions", params={"student_id": student}).status_code, 403)
            query = {"student_id": student, "session_id": ident, "sequence": 0}
            self.assertEqual(second.get("/api/media/clip", params=query).status_code, 403)
            self.assertEqual(second.get("/api/media/clip", params=query | {"student_id": other}).status_code, 404)
            upload = first.post("/api/media/upload", json=query | {"start_ms": 0, "duration_ms": 100,
                "content_base64": base64.b64encode(b"\x1a\x45\xdf\xa3test").decode()})
            self.assertEqual(upload.status_code, 200, upload.text)
            download = first.get("/api/media/clip", params=query)
            self.assertEqual(download.status_code, 200)
            self.assertEqual(download.headers["cache-control"], "no-store")
            admin = self.client()
            self.assertEqual(admin.post('/api/access/admin', json={'secret': os.environ['PLIAC_ADMIN_SECRET']}).status_code, 200)
            self.assertEqual(admin.get('/api/media/review/clip', params=query).status_code, 403)
            with patch.dict(os.environ, {'PLIAC_MEDIA_REVIEW_ENABLED': '1'}):
                self.assertEqual(first.get('/api/media/review/clip', params=query).status_code, 403)
                reviewed = admin.get('/api/media/review/clip', params=query)
                self.assertEqual(reviewed.status_code, 200)
                self.assertEqual(reviewed.headers['cache-control'], 'no-store')
                self.assertEqual(admin.get('/api/media/review/sessions', params={'student_id': student}).status_code, 200)
                self.assertEqual(admin.post('/api/media/control', json={'student_id': student, 'session_id': ident, 'operation': 'revoke'}).status_code, 403)
                with MediaStore(self.store).connection() as db:
                    self.assertEqual(db.execute('SELECT COUNT(*) FROM review_access').fetchone()[0], 2)
            self.assertEqual(first.post("/api/media/control", json={"student_id": student, "session_id": ident, "operation": "revoke"}).status_code, 200)
            self.assertEqual(first.get("/api/media/clip", params=query).status_code, 404)
            with patch.dict(os.environ, {'PLIAC_MEDIA_REVIEW_ENABLED': '1'}):
                self.assertEqual(admin.get('/api/media/review/clip', params=query).status_code, 404)


class ClipValidationTests(unittest.TestCase):
    def test_actual_browser_webm_and_invalid_header(self):
        from playwright.sync_api import sync_playwright
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                page = browser.new_page()
                # Canvas test pattern only: never requests a camera or microphone.
                encoded = page.evaluate("""async () => {
                    const canvas = document.createElement('canvas');
                    canvas.width = 160; canvas.height = 120;
                    const context = canvas.getContext('2d');
                    const stream = canvas.captureStream(12);
                    const recorder = new MediaRecorder(stream, {mimeType:'video/webm;codecs=vp8'});
                    const chunks = [];
                    recorder.ondataavailable = e => chunks.push(e.data);
                    const done = new Promise(resolve => recorder.onstop = resolve);
                    recorder.start();
                    const timer = setInterval(() => {context.fillStyle = '#808080';context.fillRect(0,0,160,120)}, 50);
                    await new Promise(resolve => setTimeout(resolve, 600));
                    recorder.stop(); await done;
                    clearInterval(timer); stream.getTracks().forEach(track => track.stop());
                    const bytes = new Uint8Array(await new Blob(chunks).arrayBuffer());
                    return btoa(String.fromCharCode(...bytes));
                }""")
            finally:
                browser.close()
        validate_clip(base64.b64decode(encoded))
        with self.assertRaises(CourseGraphError):
            validate_clip(b"\x1a\x45\xdf\xa3synthetic-invalid-container")

    def invoke(self, streams=None, progress=b"frame=60\nout_time_us=5000000\nprogress=end\n"):
        video = {"codec_type": "video", "codec_name": "vp8", "width": 480, "height": 360}
        outputs = [subprocess.CompletedProcess([], 0, json.dumps({"streams": streams if streams is not None else [video]}).encode()),
                   subprocess.CompletedProcess([], 0, progress)]
        with patch("pliac.media.shutil.which", side_effect=lambda name: name), patch("pliac.media.subprocess.run", side_effect=outputs) as runner:
            validate_clip(b"synthetic protocol test")
            return runner.call_args_list

    def test_validated_video_decodes_whole_input_with_timeout(self):
        calls = self.invoke()
        self.assertEqual(len(calls), 2)
        self.assertIn("-xerror", calls[1].args[0])
        self.assertEqual(calls[1].kwargs["timeout"], 15)
        self.assertNotIn("-t", calls[1].args[0])

    def test_audio_extra_stream_and_oversized_video_rejected(self):
        video = {"codec_type": "video", "codec_name": "vp8", "width": 480, "height": 360}
        for streams in ([], [video, {"codec_type": "audio"}], [video | {"width": 4000}], [video | {"codec_name": "h264"}]):
            with self.subTest(streams=streams), self.assertRaises(CourseGraphError):
                self.invoke(streams)

    def test_no_frames_long_duration_and_incomplete_decode_rejected(self):
        for progress in (b"frame=0\nout_time_us=5000000\nprogress=end", b"frame=40\nout_time_us=30000000\nprogress=end", b"frame=40\nout_time_us=1000000\nprogress=continue"):
            with self.subTest(progress=progress), self.assertRaises(CourseGraphError):
                self.invoke(progress=progress)

    def test_missing_tools_and_decoder_failures_fail_closed(self):
        with patch("pliac.media.shutil.which", return_value=None), self.assertRaises(CourseGraphError):
            validate_clip(b"fake")
        for error in (subprocess.TimeoutExpired("ffprobe", 10), subprocess.CalledProcessError(1, "ffprobe")):
            with patch("pliac.media.shutil.which", return_value="tool"), patch("pliac.media.subprocess.run", side_effect=error), self.assertRaises(CourseGraphError):
                validate_clip(b"fake")


if __name__ == "__main__":
    unittest.main()
