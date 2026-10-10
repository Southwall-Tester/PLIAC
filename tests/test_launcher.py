"""Interpreter-selection regressions; synthetic paths stay in a temporary tree."""
import contextlib
import io
import json
from email.message import Message
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import launch
import run as runner


class LauncherTests(unittest.TestCase):
    def test_student_missing_build_stops_before_server_import(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(runner, "ROOT", Path(folder)), patch.object(sys, "argv", ["run.py", "--student-workspace"]), contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(runner.main(), 1)
            self.assertIn("npm run build", output.getvalue())

    def test_student_reuses_protected_server_without_catalog_access(self):
        health = io.BytesIO(json.dumps({"app": "learning-agent", "capabilities": ["learnmargin_graph", "scoped_learning_units"], "student_entry": "/app/"}).encode())
        page = io.BytesIO(b"<html></html>")
        page.headers = Message()
        page.headers["Content-Type"] = "text/html; charset=utf-8"
        with patch.object(runner.urllib.request, "urlopen", side_effect=[health, page]) as request:
            self.assertTrue(runner.existing(8010, True))
            self.assertEqual([call.args[0] for call in request.call_args_list], ["http://127.0.0.1:8010/health", "http://127.0.0.1:8010/app/"])

    def test_student_rejects_legacy_server_and_unbuilt_app(self):
        def health(entry):
            return io.BytesIO(json.dumps({"app": "learning-agent", "capabilities": ["learnmargin_graph", "scoped_learning_units"], "student_entry": entry}).encode())
        with patch.object(runner.urllib.request, "urlopen", return_value=health(None)) as request:
            self.assertFalse(runner.existing(8010, True))
            self.assertEqual(request.call_count, 1)
        with patch.object(runner.urllib.request, "urlopen", side_effect=[health("/app/"), OSError("unbuilt")]):
            self.assertFalse(runner.existing(8010, True))

    def test_access_status_comes_from_running_service(self):
        for value in (True, False, "true"):
            with patch.object(runner.urllib.request, "urlopen", return_value=io.BytesIO(json.dumps({"protected": value}).encode())):
                self.assertIs(runner.access_status(8010), value if isinstance(value, bool) else None)
        with patch.object(runner.urllib.request, "urlopen", side_effect=OSError("offline")):
            self.assertIsNone(runner.access_status(8010))

    def test_student_main_reuse_opens_new_entry_and_reports_actual_access(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "web/dist").mkdir(parents=True)
            (root / "web/dist/index.html").touch()
            with patch.object(runner, "ROOT", root), patch.object(sys, "argv", ["run.py", "--student-workspace"]), patch.object(runner.socket, "socket") as socket, patch.object(runner, "existing", return_value=True), patch.object(runner, "access_status", return_value=True), patch.object(runner.webbrowser, "open") as browser, patch("uvicorn.Server") as server, contextlib.redirect_stdout(io.StringIO()) as output:
                socket.return_value.bind.side_effect = OSError("occupied")
                self.assertEqual(runner.main(), 0)
                browser.assert_called_once_with("http://127.0.0.1:8010/app/")
                server.assert_not_called()
                socket.return_value.close.assert_called_once()
                self.assertIn("身份保护已开启", output.getvalue())
                self.assertIn("手动停止旧服务", output.getvalue())

    def test_reuse_requires_current_course_api_contract(self):
        health = {"app": "learning-agent", "capabilities": ["learnmargin_graph", "scoped_learning_units"]}
        for course, accepted in [({"id": "old"}, False),
                                 ({"id": "current", "capabilities": {}, "presentation": {}}, True)]:
            replies = [io.BytesIO(json.dumps(value).encode()) for value in [health, {"courses": [course]}]]
            with patch.object(runner.urllib.request, "urlopen", side_effect=replies):
                self.assertEqual(runner.existing(8010), accepted)
        with patch.object(runner.urllib.request, "urlopen", return_value=io.BytesIO(json.dumps({"app": "learning-agent", "capabilities": ["learnmargin_graph"]}).encode())):
            self.assertFalse(runner.existing(8010))

    def test_project_environment_then_current_then_path_without_duplicates(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            venv = root / ".venv" / "Scripts" / "python.exe"
            current = root / "system" / "python.exe"
            conda = root / "conda" / "python.exe"
            for file in (venv, current, conda):
                file.parent.mkdir(parents=True)
                file.touch()
            with patch.object(launch, "ROOT", root), patch.object(sys, "executable", str(current)), patch.dict(os.environ, {"PATH": os.pathsep.join([str(current.parent), str(conda.parent)])}):
                self.assertEqual(list(launch.candidates()), [venv, current, conda])

    def test_missing_dependencies_fall_back_and_preserve_arguments(self):
        with patch.object(launch, "candidates", return_value=iter([Path("system.exe"), Path("conda.exe")])), patch.object(launch, "available", side_effect=[False, True]), patch.object(subprocess, "call", return_value=7) as call, patch.object(sys, "argv", ["launch.py", "--no-browser", "--port", "8030"]), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(launch.main(), 7)
            args = call.call_args.args[0]
            self.assertEqual(args[0], "conda.exe")
            self.assertEqual(args[-3:], ["--no-browser", "--port", "8030"])

    def test_no_environment_reports_exact_install_command(self):
        output = io.StringIO()
        with patch.object(launch, "candidates", return_value=iter([Path(sys.executable)])), patch.object(launch, "available", return_value=False), patch.object(subprocess, "call") as call, contextlib.redirect_stdout(output):
            self.assertEqual(launch.main(), 1)
            call.assert_not_called()
        self.assertIn(f'& "{sys.executable}" -m pip install -r requirements.txt', output.getvalue())

    def test_unresponsive_candidate_is_skipped(self):
        with patch.object(subprocess, "run", side_effect=subprocess.TimeoutExpired("python", 20)):
            self.assertFalse(launch.available(Path("python.exe")))


if __name__ == "__main__":
    unittest.main()
