"""Executable experiments and task contracts with isolated synthetic learners."""
import contextlib
import io
import json
import sys
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from fastapi.testclient import TestClient
from learning_agent import api
from learning_agent.acceptance_course import AcceptanceCourseStore
from learning_agent.course_graph import CourseGraphError, CourseGraphStore
from pliac.main import app
from pliac.ml_lab import MLLab
from pliac.ml_engine import execute, reproduction


class MLLabTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.default = CourseGraphStore(output_dir=Path(self.temp.name))
        self.store = AcceptanceCourseStore(self.default)
        self.lab = MLLab(self.store)
        self.student = "synthetic-lab"

    def payload(self, **values):
        view = self.lab.view(self.student)
        return {"student_id": self.student, "course_version": 1, "expected_version": view["version"],
                "request_id": uuid.uuid4().hex, "session_id": view["active"]["id"] if view["active"] else None, **values}

    def act(self, operation, **values):
        return self.lab.act(operation, self.payload(**values))

    def run_model(self, depth, **values):
        return self.act("run", config={"train_percent": 60, "features": "sensors", "split": "separate", "depth": depth, **values})["active"]["runs"][-1]

    def test_actual_training_leakage_and_reproducible_python(self):
        settings = {"train_percent": 60, "features": "sensors", "split": "separate", "depth": 0}
        normal = execute(42, settings)
        self.assertEqual(normal["counts"], {"train": 360, "validation": 120, "test": 120})
        self.assertEqual(normal["overlap"], 0)
        self.assertGreater(normal["train_accuracy"], normal["validation_accuracy"])
        self.assertNotIn("test_accuracy", normal)
        leakage = execute(42, {**settings, "features": "receipt"})
        self.assertEqual(leakage["validation_accuracy"], 1)
        overlap = execute(42, {**settings, "split": "reuse"})
        self.assertEqual(overlap["overlap"], 360)
        self.assertEqual(overlap["validation_accuracy"], overlap["train_accuracy"])
        code = reproduction(42, settings, True)
        with contextlib.redirect_stdout(io.StringIO()) as output:
            exec(compile(code, "reproduce.py", "exec"), {})
        actual = execute(42, settings, test=True)
        self.assertIn(str(actual["test_accuracy"]), output.getvalue())

    def test_full_loop_freeze_transfer_and_shared_evidence(self):
        self.act("start", scene="space")
        result = self.act("check", answer={"target": "target", "features": "receipt", "timing": "after"})
        self.assertEqual(result["active"]["step"], 0)
        self.assertEqual(len(result["hint_texts"]), 1)
        self.assertNotIn("用 x1", result["hint_texts"][0])
        result = self.act("check", answer={"target": "target", "features": "sensors", "timing": "after"})
        self.assertEqual(result["active"]["step"], 1)
        bad = self.run_model(1, split="reuse")
        self.assertEqual(self.act("check", answer={"run_id": bad["id"]})["active"]["step"], 1)
        shallow = self.run_model(1)
        self.act("check", answer={"run_id": shallow["id"]})
        deep = self.run_model(0)
        self.act("check", answer={"run_id": deep["id"], "interpretation": "gap"})
        medium = self.run_model(4)
        best = max([shallow, deep, medium], key=lambda r: r["result"]["validation_accuracy"])
        result = self.act("check", answer={"run_id": best["id"], "basis": "validation", "note": "依据同一划分的验证准确率比较三个模型，选择表现最高的实验。"})
        self.assertEqual(result["active"]["step"], 4)
        self.assertIsNone(result["active"]["final"])
        with self.assertRaises(CourseGraphError):
            self.run_model(5)
        result = self.act("check", answer={"test_role": "report", "note": "测试集用于报告已经封存的方案，模型选择依据此前的验证结果。"})
        self.assertEqual(result["active"]["step"], 5)
        self.assertIn("test_accuracy", result["active"]["final"]["result"])
        original = result["active"]
        exported = self.lab.export(self.student)
        self.assertTrue(exported["assessment"]["practice_complete"])
        self.assertIn("inspect", exported["assessment"]["assisted_tasks"])
        self.assertEqual(exported["assessment"]["explanation_review"], "pending_human_review")
        self.assertEqual(self.store._read_learner(self.student)["diagnoses"], [])
        evidence = self.store._read_learner(self.student)["evidence"]
        self.assertTrue(any(e["source_type"] == "practice" and e["node_id"] == "leakage" for e in evidence))
        self.assertTrue(any(e["origin"] == "system_observation" for e in evidence))
        with patch("pliac.ml_lab.secrets.randbelow", return_value=original["seed"] + 1):
            new = self.act("start", scene="ocean")["active"]
        self.assertNotEqual(new["seed"], original["seed"])
        self.assertEqual(new["hints"], {})
        self.assertEqual(new["mode"], "transfer")
        self.assertEqual(self.lab.view(self.student)["lab"]["sessions"][0], original)
        self.assertEqual(MLLab(self.store).view(self.student)["active"], new)

    def test_idempotency_isolation_stale_requests_and_bounds(self):
        p = self.payload(scene="space")
        first = self.lab.act("start", p)
        self.assertEqual(self.lab.act("start", p)["version"], first["version"])
        with self.assertRaises(CourseGraphError):
            self.lab.act("start", {**p, "scene": "ocean"})
        with self.assertRaises(CourseGraphError):
            self.act("start", scene="ocean")
        bad = self.payload(config={"train_percent": 60, "depth": True, "features": "sensors", "split": "separate"})
        with self.assertRaises(CourseGraphError):
            self.lab.act("run", bad)
        self.assertEqual(self.lab.view(self.student)["version"], first["version"])
        stale = self.payload()
        self.act("hint")
        with self.assertRaises(CourseGraphError):
            self.lab.act("hint", stale)
        self.assertIsNone(self.lab.view("other-learner")["active"])
        with self.assertRaises(CourseGraphError):
            self.lab.view("../escape")

    def test_api_uses_isolated_platform_store_and_hides_future_hints(self):
        with patch.object(api, "store", self.default), TestClient(app) as client:
            self.assertEqual(client.get("/ml-lab").status_code, 200)
            self.assertEqual(client.post("/api/ml-lab/start", json=self.payload(scene="sport")).status_code, 200)
            view = client.get("/api/ml-lab", params={"student_id": self.student}).json()
            self.assertFalse(view["hint_texts"])
            self.assertNotIn("hints", view["tasks"][0])
            self.assertNotIn("test_accuracy", json.dumps(view))
            self.assertEqual(client.get("/api/ml-lab", params={"student_id": "../escape"}).status_code, 400)


if __name__ == "__main__":
    unittest.main()
