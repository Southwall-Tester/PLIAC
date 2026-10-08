"""Bounded OCR sessions and read-only cross-service task observation."""
from concurrent.futures import Future
import os
from pathlib import Path
import sys
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from learning_agent import documents
from learning_agent.course_graph import CourseGraphError


class OCRRuntimeTests(unittest.TestCase):
    def test_thread_budget_is_bounded_and_invalid_values_use_default(self):
        with patch.object(documents.os, "cpu_count", return_value=16):
            for value, expected in (("1", 1), ("2", 2), ("99", 4), ("0", 1), ("-8", 1), ("wrong", 4)):
                with patch.dict(os.environ, {"OCR_THREADS": value}):
                    self.assertEqual(documents.ocr_threads(), expected)
        with patch.object(documents.os, "cpu_count", return_value=1), patch.dict(os.environ, {"OCR_THREADS": "4"}):
            self.assertEqual(documents.ocr_threads(), 1)

    def test_default_reserves_cpu_capacity_and_handles_unknown_cpu_count(self):
        for cpu_count, expected in ((32, 4), (16, 4), (8, 2), (4, 1), (2, 1), (1, 1), (None, 1)):
            with patch.object(documents.os, "cpu_count", return_value=cpu_count), patch.dict(os.environ, {}, clear=True):
                self.assertEqual(documents.ocr_threads(), expected)
                os.environ["OCR_THREADS"] = "invalid"
                self.assertEqual(documents.ocr_threads(), expected)

    def test_all_sessions_disable_spinning_and_factory_is_restored(self):
        class Options:
            def __init__(self, cfg):
                self.intra_op_num_threads = cfg.intra_op_num_threads
                self.inter_op_num_threads = cfg.inter_op_num_threads
                self.entries = {}

            def add_session_config_entry(self, key, value):
                self.entries[key] = value

        class Ort:
            _init_sess_opts = staticmethod(Options)

        class Engine:
            def __init__(self, params):
                cfg = SimpleNamespace(intra_op_num_threads=params["EngineConfig.onnxruntime.intra_op_num_threads"],
                                      inter_op_num_threads=params["EngineConfig.onnxruntime.inter_op_num_threads"])
                self.sessions = [Ort._init_sess_opts(cfg) for _ in range(3)]

        cv_calls = []
        modules = {"cv2": SimpleNamespace(setNumThreads=cv_calls.append), "rapidocr": SimpleNamespace(RapidOCR=Engine),
                   "rapidocr.inference_engine.onnxruntime": SimpleNamespace(OrtInferSession=Ort)}
        original = Ort._init_sess_opts
        with patch.dict(sys.modules, modules), patch.dict(os.environ, {"OCR_THREADS": "2"}), patch.object(documents.os, "cpu_count", return_value=16):
            engine = documents.create_ocr_engine()
        self.assertEqual(cv_calls, [1])
        self.assertIs(Ort._init_sess_opts, original)
        for opts in engine.sessions:
            self.assertEqual(opts.intra_op_num_threads, 2)
            self.assertEqual(opts.inter_op_num_threads, 1)
            self.assertEqual(opts.entries, {"session.intra_op.allow_spinning": "0", "session.inter_op.allow_spinning": "0"})
        with patch.dict(sys.modules, modules), patch.object(modules["rapidocr"], "RapidOCR", side_effect=RuntimeError("synthetic init failure")):
            with self.assertRaises(RuntimeError):
                documents.create_ocr_engine()
        self.assertIs(Ort._init_sess_opts, original)

    def test_owner_probe_handles_current_and_invalid_pids(self):
        self.assertTrue(documents.process_alive(os.getpid()))
        for pid in (None, -1, 0, "12", True):
            self.assertFalse(documents.process_alive(pid))


class DocumentOwnershipTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.owner = documents.DocumentStore(Path(self.tmp.name))
        self.observer = documents.DocumentStore(Path(self.tmp.name))
        self.addCleanup(self.owner.executor.shutdown, wait=True)
        self.addCleanup(self.observer.executor.shutdown, wait=True)
        self.job = self.owner.create("test.txt")
        self.ident = self.job["id"]
        self.owner.source(self.ident).write_text("知识图谱包括实体。", encoding="utf-8")
        self.job_path = self.owner.directory(self.ident) / "job.json"

    def test_observer_keeps_live_owner_active_without_writing(self):
        self.owner.update(self.ident, status="parsing", worker_pid=os.getpid(), worker_active=True)
        before = self.job_path.read_bytes(), self.job_path.stat().st_mtime_ns
        self.assertEqual(self.observer.status(self.ident)["status"], "parsing")
        self.assertEqual(self.observer.listing()[0]["status"], "parsing")
        self.assertEqual((self.job_path.read_bytes(), self.job_path.stat().st_mtime_ns), before)
        with self.assertRaises(CourseGraphError) as error:
            self.observer.submit(self.ident)
        self.assertEqual(error.exception.status_code, 409)
        self.assertEqual(self.job_path.read_bytes(), before[0])

    def test_dead_owner_can_be_resumed_without_erasing_checkpoints(self):
        cached = self.owner.directory(self.ident) / "pages/1.json"
        documents.atomic_json(cached, {"page": 1, "text": "缓存原文", "ocr": True})
        cache_bytes, cache_time = cached.read_bytes(), cached.stat().st_mtime_ns
        self.owner.update(self.ident, status="parsing", worker_pid=987654, worker_active=True)
        before = self.job_path.read_bytes()
        with patch.object(documents, "process_alive", return_value=False):
            self.assertEqual(self.observer.status(self.ident)["status"], "partial")
            self.assertEqual(self.job_path.read_bytes(), before)
            with patch.object(self.observer.executor, "submit", return_value=Future()):
                resumed = self.observer.submit(self.ident)
        self.assertEqual(resumed["status"], "queued")
        self.assertEqual(resumed["worker_pid"], os.getpid())
        self.assertEqual((cached.read_bytes(), cached.stat().st_mtime_ns), (cache_bytes, cache_time))

    def test_cancel_request_is_visible_to_another_store(self):
        self.owner.update(self.ident, status="extracting", worker_pid=os.getpid(), worker_active=True)
        self.assertFalse(self.owner._is_cancelled(self.ident))
        self.observer.cancel(self.ident)
        self.assertTrue(self.owner._is_cancelled(self.ident))
        self.assertEqual(self.owner.status(self.ident)["status"], "cancelled")

    def test_cancelled_worker_must_finish_before_another_store_can_retry(self):
        entered, release = threading.Event(), threading.Event()
        original_extract = documents.extract_local

        def slow_page(*args):
            entered.set()
            if not release.wait(5):
                raise RuntimeError("synthetic worker wait timed out")
            return original_extract(*args)

        try:
            with patch.object(documents, "extract_local", side_effect=slow_page):
                self.owner.submit(self.ident)
                self.assertTrue(entered.wait(5))
                cancelled = self.observer.cancel(self.ident)
                self.assertEqual(cancelled["status"], "cancelled")
                self.assertTrue(cancelled["worker_active"])
                with self.assertRaises(CourseGraphError) as conflict:
                    self.observer.submit(self.ident)
                self.assertEqual(conflict.exception.status_code, 409)
                self.assertTrue(self.observer.status(self.ident)["worker_active"])
                release.set()
                self.owner.futures[self.ident].result(timeout=10)
        finally:
            release.set()
        finished = self.observer.status(self.ident)
        self.assertEqual(finished["status"], "cancelled")
        self.assertFalse(finished["worker_active"])
        checkpoint = next((self.owner.directory(self.ident) / "chunks").glob("*.json"))
        before = checkpoint.read_bytes(), checkpoint.stat().st_mtime_ns
        self.observer.submit(self.ident)
        self.observer.futures[self.ident].result(timeout=10)
        self.assertEqual(self.observer.status(self.ident)["status"], "completed")
        self.assertFalse(self.observer.status(self.ident)["worker_active"])
        self.assertEqual((checkpoint.read_bytes(), checkpoint.stat().st_mtime_ns), before)

    def test_live_pid_without_active_worker_is_read_as_interrupted(self):
        self.owner.update(self.ident, status="parsing", worker_pid=os.getpid(), worker_active=False)
        before = self.job_path.read_bytes()
        self.assertEqual(self.observer.status(self.ident)["status"], "partial")
        self.assertEqual(self.job_path.read_bytes(), before)

    def test_merged_counts_remain_visible_on_the_next_page(self):
        observed = []
        original = self.owner.update

        def record(*args, **kwargs):
            value = original(*args, **kwargs)
            if value["progress"]["current"] == 1 and value["status"] == "parsing":
                observed.append(value["stats"]["nodes"])
            return value

        with patch.object(documents, "text_pages", return_value=["知识图谱包括实体。", "知识图谱包括关系。"]), patch.object(self.owner, "update", side_effect=record):
            self.owner.run(self.ident)
        self.assertTrue(observed)
        self.assertGreater(observed[0], 0)
        self.assertEqual(self.owner.status(self.ident)["status"], "completed")


if __name__ == "__main__":
    unittest.main(verbosity=2)
