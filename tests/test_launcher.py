"""Interpreter-selection regressions; synthetic paths stay in a temporary tree."""
import contextlib
import io
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import launch


class LauncherTests(unittest.TestCase):
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
