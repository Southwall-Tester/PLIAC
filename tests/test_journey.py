"""Synthetic entry-assessment, provenance and route-orchestration contracts."""
import asyncio
from contextlib import asynccontextmanager
import copy
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from fastapi import FastAPI
from fastapi.testclient import TestClient
from learning_agent import api
from learning_agent import course_graph
from learning_agent.course_graph import CourseGraphError, CourseGraphStore
from learnmargin.models import APIConfig
from pliac import journey
from pliac.api import router
from pliac.workspace import LearningWorkspace
from test_learning_workspace import platform_fixture, publish_synthetic

CONFIG = APIConfig(base_url="http://127.0.0.1:9999/v1", api_key="synthetic", model="synthetic")


def result(priority="a", signal="needs_support", quote="还没理解"):
    return journey.RouteReply(
        summary="合成个性化路线", teaching_approach="先做小例子，再独立练习",
        priorities=[{"node_id": priority, "reason": "针对学习目标先学习", "focus": "先解释再应用", "pace": "steady"}],
        diagnosis=[{"node_id": "a", "quote": quote, "signal": signal, "reason": "合成作答分析"}])


@asynccontextmanager
async def lifespan(app):
    yield
    await journey.close_journeys()


class JourneyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        seed = self.root / "seed.json"
        graph = platform_fixture()
        for node, title in zip(graph["nodes"], ["路径定位", "文本搜索", "管道组合", "Shell自动化"]):
            node["title"] = title
            node["description"] = title + "课程"
        seed.write_text(json.dumps(graph, ensure_ascii=False), encoding="utf-8")
        self.store = CourseGraphStore(seed, self.root / "records")
        publish_synthetic(self.store)
        self.workspace = LearningWorkspace(self.store)
        self.enterContext(patch.object(api, "store", self.store))
        self.config = self.enterContext(patch.object(journey, "configured_api", return_value=CONFIG))
        self.model = self.enterContext(patch.object(journey.JourneyProvider, "plan", return_value=result()))
        app = FastAPI(lifespan=lifespan)
        app.include_router(router)
        self.client = self.enterContext(TestClient(app))
        self.onboard()

    def payload(self, student="s1", **values):
        return {"student_id": student, "course_version": self.store.load_graph()["version"],
                "expected_version": self.store.load_learner(student)["version"],
                "request_id": uuid.uuid4().hex, **values}

    def onboard(self, student="s1", goals="路径定位", **kwargs):
        values = {"goals": goals, "background": "零基础",
                  "self_assessments": {"a": "confident", "b": "unsure", "c": "new", "d": "new"}, **kwargs}
        return self.workspace.onboard(self.payload(student, **values))

    def view(self, student="s1"):
        response = self.client.get("/api/learning/journey", params={"student_id": student})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def submit(self, student="s1", text="还没理解", payload=None):
        body = payload or self.payload(student, answers=[{"node_id": q["node_id"], "text": text}
                                                        for q in self.view(student)["questions"]])
        return self.client.post("/api/learning/journey/assessment", json=body)

    def wait(self, student="s1"):
        for _ in range(150):
            data = self.view(student)
            if data["stage"] != "planning":
                return data
            time.sleep(.01)
        self.fail("Synthetic planner did not finish")

    def test_profile_gate_questions_and_public_answer_separation(self):
        self.assertEqual(self.view("fresh")["stage"], "profile")
        self.assertEqual(self.submit("fresh").status_code, 409)
        view = self.view()
        self.assertEqual(view["stage"], "assessment")
        self.assertEqual({q["self_assessment"] for q in view["questions"]}, {"confident", "unsure"})
        self.assertEqual({q["node_id"] for q in view["questions"]}, {"a", "b"})
        self.assertLessEqual(len(view["questions"]), 3)
        self.assertIsNone(view["progress"])
        self.assertNotIn("TEACHER_ONLY", json.dumps(view))

    def test_all_new_skips_questions_and_plans_from_profile_without_diagnoses(self):
        self.onboard(self_assessments={n: "new" for n in "abcd"})
        self.model.return_value = result().model_copy(update={"diagnosis": []})
        before = self.store.load_learner("s1")
        self.assertEqual(self.view()["questions"], [])
        payload = self.payload(answers=[])
        self.assertEqual(self.submit(payload=payload).status_code, 200)
        planned = self.wait()
        self.assertEqual(planned["stage"], "ready")
        self.assertEqual(planned["route"]["source"], "model")
        self.assertEqual(planned["route"]["calibration"], [])
        context = self.model.call_args.args[0]
        self.assertEqual(context["assessment_mode"], "profile_only")
        self.assertEqual(context["questions"], [])
        self.assertEqual(context["baseline"], [])
        self.assertTrue(all("expected_answer" not in node for node in context["course"]["nodes"]))
        self.assertEqual(context["profile"]["goals"], before["profile"]["goals"])
        after = self.store.load_learner("s1")
        active = after["workspace"]["journey"]["active"]
        self.assertEqual(active["questions"], [])
        self.assertEqual(active["answers"], [])
        self.assertEqual(active["evidence"], [])
        self.assertEqual(active["model_diagnosis"], [])
        self.assertEqual(after["evidence"], before["evidence"])
        self.assertEqual(after["diagnoses"], before["diagnoses"])
        self.assertEqual(after["states"], before["states"])
        self.assertEqual(self.submit(payload=payload).status_code, 200)
        self.assertEqual(self.view()["assessment_id"], planned["assessment_id"])
        self.assertEqual(self.model.call_count, 1)
        self.assertEqual(self.store.load_learner("s1")["workspace"]["journey"]["history"], [])

    def test_all_new_algorithm_route_has_no_invented_baseline_or_diagnosis(self):
        self.onboard(self_assessments={n: "new" for n in "abcd"})
        self.config.side_effect = CourseGraphError("课程模型尚未配置。", 503)
        self.assertEqual(self.submit(payload=self.payload(answers=[])).status_code, 200)
        planned = self.wait()
        self.assertEqual(planned["stage"], "ready")
        self.assertEqual(planned["route"]["source"], "algorithm")
        self.assertEqual(planned["route"]["calibration"], [])
        self.assertEqual(planned["progress"]["phase"], "ready")
        active = self.store.load_learner("s1")["workspace"]["journey"]["active"]
        self.assertEqual(active["evidence"], [])
        self.assertEqual(active["model_diagnosis"], [])
        self.model.assert_not_called()

    def test_new_topics_cannot_be_submitted_or_given_model_diagnoses(self):
        answers = [{"node_id": n, "text": "还没理解"} for n in "abc"]
        self.assertEqual(self.submit(payload=self.payload(answers=answers)).status_code, 400)
        self.model.assert_not_called()
        self.onboard(self_assessments={n: "new" for n in "abcd"})
        self.assertEqual(self.submit(payload=self.payload(answers=[])).status_code, 200)
        self.assertEqual(self.wait()["stage"], "failed")
        self.assertEqual(self.store.load_learner("s1")["workspace"]["journey"]["active"]["model_diagnosis"], [])

    def test_progress_reports_actual_model_wait_and_completion(self):
        started = threading.Event()
        release = threading.Event()

        async def wait_for_model(context):
            started.set()
            await asyncio.to_thread(release.wait, 5)
            return result()

        self.model.side_effect = wait_for_model
        phases = []
        progress = journey._progress
        def record_progress(*args):
            phases.append(args[-1])
            return progress(*args)
        with patch.object(journey, "_progress", side_effect=record_progress):
            try:
                self.assertEqual(self.submit().status_code, 200)
                self.assertTrue(started.wait(5))
                pending = self.view()
                self.assertEqual(pending["stage"], "planning")
                self.assertEqual(pending["progress"]["phase"], "model_wait")
                self.assertEqual(set(pending["progress"]), {"phase", "label", "started_at", "updated_at"})
                self.assertTrue(pending["progress"]["started_at"])
                self.assertNotIn("percent", pending["progress"])
                release.set()
                ready = self.wait()
                self.assertEqual(ready["stage"], "ready")
                self.assertEqual(ready["progress"]["phase"], "ready")
                self.assertEqual(ready["progress"]["started_at"], pending["progress"]["started_at"])
                self.assertEqual(phases, ["preparing", "model_wait", "validating", "saving"])
            finally:
                release.set()

    def test_missing_or_previous_course_self_assessment_blocks_route_planning(self):
        for problem in ("missing", "previous_course", "invalid_value"):
            with self.subTest(problem=problem):
                self.onboard()
                with self.store._writer():
                    learner = self.store._read_learner("s1")
                    assessments = learner["workspace"]["self_assessments"]
                    if problem == "missing":
                        assessments.pop("d")
                    elif problem == "previous_course":
                        assessments["d"]["course_version"] = self.store.load_graph()["version"] - 1
                    else:
                        assessments["d"]["value"] = "unvalidated"
                    self.store._commit(learner)
                self.model.reset_mock()
                response = self.submit()
                self.assertEqual(409, response.status_code)
                self.assertIn("回到起点自评", response.json()["detail"])
                self.model.assert_not_called()
                self.assertIsNone(self.store._read_learner("s1").get("workspace", {}).get("journey", {}).get("active"))

    def test_model_route_and_raw_baseline_are_separate_from_mastery(self):
        before = self.store.load_learner("s1")
        self.assertEqual(self.submit().status_code, 200)
        data = self.wait()
        self.assertEqual(data["stage"], "ready")
        self.assertEqual(data["route"]["source"], "model")
        context = self.model.call_args.args[0]
        references = {n["node_id"]: n["expected_answer"] for n in context["course"]["nodes"] if "expected_answer" in n}
        self.assertEqual(set(references), {q["node_id"] for q in data["questions"]})
        graph = self.store.load_graph()
        self.assertTrue(all(references[n["id"]] == n["expected_answer"][:1500]
                            for n in graph["nodes"] if n["id"] in references))
        self.assertEqual(len(context["course"]["nodes"]), len(graph["nodes"]))
        self.assertTrue(all(len(n["description"]) <= 300 for n in context["course"]["nodes"]))
        after = self.store.load_learner("s1")
        self.assertEqual(after["evidence"], before["evidence"])
        self.assertEqual(after["diagnoses"], before["diagnoses"])
        self.assertEqual(after["states"], before["states"])
        active = after["workspace"]["journey"]["active"]
        self.assertEqual(active["evidence"][0]["origin"], "learner_expression")
        self.assertEqual(active["model_diagnosis"][0]["origin"], "model_diagnosis")
        self.assertEqual(active["initial_profile"]["course_id"], self.store.load_graph()["id"])
        self.assertEqual(data["route"]["calibration"][0]["calibration"], "overestimated")

    def test_goal_difference_changes_algorithm_route_without_fabricated_model(self):
        self.config.side_effect = CourseGraphError("课程模型尚未配置。", 503)
        self.submit()
        first = self.wait()["route"]
        self.onboard("s2", goals="文本搜索")
        self.submit("s2")
        second = self.wait("s2")["route"]
        self.assertEqual(first["source"], "algorithm")
        self.assertEqual(first["steps"][0]["node_id"], "a")
        self.assertEqual(second["steps"][0]["node_id"], "b")
        self.assertTrue(all(x["signal"] == "unknown" for x in second["calibration"]))
        self.model.assert_not_called()

    def test_baseline_change_revises_calibration_and_preserves_history(self):
        self.submit()
        first = self.wait()
        old = copy.deepcopy(self.store.load_learner("s1")["workspace"]["journey"]["active"])
        self.model.return_value = result("b", "ready_to_practice", "我能解释")
        self.submit(text="我能解释")
        second = self.wait()
        current = self.store.load_learner("s1")["workspace"]["journey"]
        self.assertEqual(current["history"][0], old)
        self.assertNotEqual(first["assessment_id"], second["assessment_id"])
        self.assertEqual(second["route"]["steps"][0]["node_id"], "b")
        self.assertEqual(next(x for x in second["route"]["calibration"] if x["node_id"] == "a")["calibration"],
                         "calibrated_confident")
        self.assertEqual(next(x for x in second["route"]["steps"] if x["node_id"] == "a")["pace"], "quick")

    def test_invalid_or_unattributed_model_output_fails_and_can_retry(self):
        self.model.return_value = result("invented")
        self.submit()
        failed = self.wait()
        self.assertEqual(failed["stage"], "failed")
        self.assertIsNone(failed["route"])
        self.model.return_value = result(quote="不是学生原话")
        self.submit()
        self.assertEqual(self.wait()["stage"], "failed")
        self.model.return_value = result()
        self.submit()
        self.assertEqual(self.wait()["stage"], "ready")
        self.assertEqual(len(self.store.load_learner("s1")["workspace"]["journey"]["history"]), 2)

    def test_prerequisite_topology_only_and_existing_frontier_still_applies(self):
        self.model.return_value = result("d")
        self.submit()
        route = self.wait()["route"]
        order = [s["node_id"] for s in route["steps"]]
        for source, target in (("a", "c"), ("b", "c"), ("c", "d")):
            self.assertLess(order.index(source), order.index(target))
        # Reverse confusable d -> a never constrains order.
        self.assertEqual(set(order), {"a", "b", "c", "d"})
        learner = self.store.load_learner("s1")
        selected = self.workspace._choose_node(self.store.load_graph(), learner, learner["workspace"])
        self.assertIn(selected, {"a", "b"})
        lesson = self.workspace.next_lesson(self.payload())["current_lesson"]
        self.assertIn("先做小例子", lesson["reason"])
        self.assertIn("learning_focus", lesson)

    def test_idempotency_and_invalid_duplicate_answers(self):
        payload = self.payload(answers=[{"node_id": q["node_id"], "text": "还没理解"} for q in self.view()["questions"]])
        self.submit(payload=payload)
        first = self.wait()
        self.assertEqual(self.submit(payload=payload).status_code, 200)
        self.assertEqual(self.wait()["assessment_id"], first["assessment_id"])
        self.assertEqual(self.model.call_count, 1)
        duplicate = self.payload(answers=[{"node_id": "a", "text": "还没理解"}] * 4)
        self.assertEqual(self.submit(payload=duplicate).status_code, 400)
        self.assertEqual(self.view()["assessment_id"], first["assessment_id"])

    def test_concurrent_submission_does_not_duplicate_running_analysis(self):
        started, release = threading.Event(), threading.Event()
        async def slow(context):
            started.set()
            await asyncio.to_thread(release.wait, 5)
            return result()
        self.model.side_effect = slow
        try:
            self.assertEqual(self.submit().status_code, 200)
            self.assertTrue(started.wait(5))
            self.assertEqual(self.submit().status_code, 409)
        finally:
            release.set()
        completed = self.wait()
        self.assertEqual(completed["stage"], "ready", completed["error"])
        self.assertEqual(self.model.call_count, 1)

    def test_windows_head_read_contention_does_not_fail_route_progress(self):
        original_progress, original_replace = journey._progress, course_graph.os.replace
        blocked = []

        def replace_with_reader(source, target):
            if Path(target).name == "HEAD.json" and not blocked:
                blocked.append(Path(target))
                error = PermissionError("Synthetic Windows reader still holds HEAD.json")
                error.winerror = 5
                raise error
            return original_replace(source, target)

        def saving_progress(*args):
            if args[-1] == "saving":
                with patch.object(course_graph.os, "replace", side_effect=replace_with_reader):
                    return original_progress(*args)
            return original_progress(*args)

        with patch.object(journey, "_progress", side_effect=saving_progress):
            self.assertEqual(self.submit().status_code, 200)
            completed = self.wait()
        self.assertEqual(completed["stage"], "ready", completed["error"])
        self.assertEqual(len(blocked), 1)
        self.assertEqual(self.model.call_count, 1)
        active = self.store.load_learner("s1")["workspace"]["journey"]["active"]
        self.assertEqual(active["id"], completed["assessment_id"])
        self.assertEqual(active["progress"]["phase"], "ready")
        self.assertTrue(active["evidence"])

    def test_windows_atomic_replace_failure_is_bounded_and_preserves_original(self):
        target = self.root / "unchanged.json"
        target.write_text('{"original": true}', encoding="utf-8")
        denied = PermissionError("Synthetic persistent Windows access failure")
        denied.winerror = 5
        with patch.object(course_graph.os, "replace", side_effect=denied) as replace, \
             patch.object(course_graph.time, "sleep") as sleep:
            with self.assertRaises(PermissionError):
                course_graph._atomic_json(target, {"replacement": True})
        self.assertEqual(replace.call_count, 5)
        self.assertEqual([call.args[0] for call in sleep.call_args_list], [.01, .02, .04, .08])
        self.assertEqual(json.loads(target.read_text(encoding="utf-8")), {"original": True})
        self.assertFalse(list(self.root.glob(".graph-*.tmp")))

    def test_other_atomic_replace_errors_are_not_retried(self):
        target = self.root / "unchanged.json"
        target.write_text('{"original": true}', encoding="utf-8")
        denied = PermissionError("Synthetic non-sharing permission failure")
        denied.winerror = 87
        for error in (denied, OSError("Synthetic unrelated storage failure")):
            with self.subTest(error=type(error).__name__), \
                 patch.object(course_graph.os, "replace", side_effect=error) as replace, \
                 patch.object(course_graph.time, "sleep") as sleep:
                with self.assertRaises(type(error)):
                    course_graph._atomic_json(target, {"replacement": True})
            self.assertEqual(replace.call_count, 1)
            sleep.assert_not_called()
            self.assertEqual(json.loads(target.read_text(encoding="utf-8")), {"original": True})
            self.assertFalse(list(self.root.glob(".graph-*.tmp")))

    def test_windows_snapshot_read_contention_is_retried(self):
        target = self.root / "snapshot.json"
        target.write_text('{"version": 7}', encoding="utf-8")
        shared = PermissionError(13, "Synthetic Windows sharing conflict")
        shared.winerror = 32
        errors = [shared]
        if course_graph.os.name == "nt":
            errors.append(PermissionError(13, "Synthetic Windows CRT access conflict"))
        for error in errors:
            with self.subTest(winerror=getattr(error, "winerror", None)), \
                 patch.object(Path, "read_text", side_effect=[error, '{"version": 7}']) as read, \
                 patch.object(course_graph.time, "sleep") as sleep:
                self.assertEqual(course_graph._read_json(target), {"version": 7})
            self.assertEqual(read.call_count, 2)
            sleep.assert_called_once_with(.01)

    def test_persistent_snapshot_read_conflict_is_bounded(self):
        target = self.root / "snapshot.json"
        target.write_text('{"version": 7}', encoding="utf-8")
        denied = PermissionError("Synthetic persistent Windows read conflict")
        denied.winerror = 5
        with patch.object(Path, "read_text", side_effect=denied) as read, \
             patch.object(course_graph.time, "sleep") as sleep:
            with self.assertRaises(CourseGraphError) as raised:
                course_graph._read_json(target)
        self.assertIs(raised.exception.__cause__, denied)
        self.assertEqual(read.call_count, 5)
        self.assertEqual(sleep.call_count, 4)

    def test_invalid_or_missing_snapshot_is_not_retried(self):
        target = self.root / "snapshot.json"
        target.write_text("{not-json", encoding="utf-8")
        for path, cause in [(target, json.JSONDecodeError), (self.root / "missing.json", FileNotFoundError)]:
            with self.subTest(cause=cause.__name__), patch.object(course_graph.time, "sleep") as sleep:
                with self.assertRaises(CourseGraphError) as raised:
                    course_graph._read_json(path)
            self.assertIsInstance(raised.exception.__cause__, cause)
            sleep.assert_not_called()

    def test_new_assessment_starts_while_previous_task_is_finishing(self):
        committed, release_old = threading.Event(), threading.Event()
        second_started, release_new = threading.Event(), threading.Event()
        original_finish = journey._finish
        held_assessments = []

        def finish_then_wait(*args):
            outcome = original_finish(*args)
            if not held_assessments:
                held_assessments.append(args[2])
                committed.set()
                if not release_old.wait(5):
                    raise AssertionError("Previous task was not released")
            return outcome

        async def plan(context):
            if committed.is_set():
                second_started.set()
                await asyncio.to_thread(release_new.wait, 5)
            return result()

        self.model.side_effect = plan
        with patch.object(journey, "_finish", side_effect=finish_then_wait):
            try:
                first = self.submit()
                self.assertEqual(first.status_code, 200)
                self.assertTrue(committed.wait(5))
                first_id = self.view()["assessment_id"]
                first_key = journey.key(self.store, "s1", first_id)
                first_task = journey.TASKS[first_key]
                body = self.payload(answers=[{"node_id": q["node_id"], "text": "还没理解"}
                                             for q in self.view()["questions"]])
                second = self.submit(payload=body)
                self.assertEqual(second.status_code, 200)
                second_id = second.json()["assessment_id"]
                self.assertNotEqual(second_id, first_id)
                self.assertTrue(second_started.wait(5))
                second_key = journey.key(self.store, "s1", second_id)
                second_task = journey.TASKS[second_key]
                self.assertIsNot(second_task, first_task)

                release_old.set()
                async def wait_for_previous():
                    await asyncio.wait_for(asyncio.shield(first_task), 5)
                self.client.portal.call(wait_for_previous)
                self.assertNotIn(first_key, journey.TASKS)
                self.assertIs(journey.TASKS[second_key], second_task)
                self.assertEqual(self.view()["stage"], "planning")
                self.assertEqual(self.submit(payload=body).status_code, 200)
                self.assertIs(journey.TASKS[second_key], second_task)
                self.assertEqual(self.model.call_count, 2)

                release_new.set()
                self.assertEqual(self.wait()["stage"], "ready")
                saved = self.store.load_learner("s1")["workspace"]["journey"]
                self.assertEqual(saved["active"]["id"], second_id)
                self.assertEqual(saved["history"][0]["id"], first_id)
                self.assertEqual(saved["history"][0]["stage"], "ready")
            finally:
                release_old.set()
                release_new.set()

    def test_shutdown_cancels_current_assessment_and_allows_retry(self):
        started = threading.Event()

        async def blocked(context):
            started.set()
            await asyncio.Event().wait()

        self.model.side_effect = blocked
        self.assertEqual(self.submit().status_code, 200)
        self.assertTrue(started.wait(5))
        before = copy.deepcopy(self.store.load_learner("s1")["workspace"]["journey"]["active"])
        self.client.portal.call(journey.close_journeys)
        self.assertEqual(self.view()["stage"], "failed")
        self.assertNotIn(journey.key(self.store, "s1", before["id"]), journey.TASKS)
        after = self.store.load_learner("s1")["workspace"]["journey"]["active"]
        self.assertEqual(after["evidence"], before["evidence"])
        self.model.side_effect = None
        self.assertEqual(self.submit().status_code, 200)
        self.assertEqual(self.wait()["stage"], "ready")

    def test_student_and_store_isolation_and_legacy_learning(self):
        self.submit()
        completed = self.wait()
        self.assertEqual(completed["stage"], "ready", completed["error"])
        self.assertEqual(self.view("someone_else")["stage"], "profile")
        another = CourseGraphStore(self.store.seed_path, self.root / "other")
        publish_synthetic(another)
        self.assertEqual(journey.view(another, "s1")["stage"], "profile")
        self.onboard("legacy")
        lesson = self.workspace.next_lesson(self.payload("legacy"))["current_lesson"]
        self.assertEqual(lesson["node_id"], "a")
        self.assertNotIn("route_source", lesson)

    def test_restart_marks_interrupted_plan_failed_and_preserves_raw(self):
        payload = self.payload(answers=[{"node_id": q["node_id"], "text": "还没理解"} for q in self.view()["questions"]])
        current = journey._start(self.store, payload)
        with self.store._writer():
            learner = self.store._read_learner("s1")
            learner["workspace"]["journey"]["active"]["runtime_id"] = "previous-process"
            self.store._commit(learner)
        interrupted = self.view()
        self.assertEqual(interrupted["stage"], "failed")
        self.assertEqual(interrupted["assessment_id"], current["id"])
        self.submit()
        completed = self.wait()
        self.assertEqual(completed["stage"], "ready", completed["error"])

    def test_profile_changed_during_model_call_uses_latest_profile(self):
        contexts = []
        started, release = threading.Event(), threading.Event()
        async def slow(context):
            contexts.append(context)
            if len(contexts) == 1:
                started.set()
                await asyncio.to_thread(release.wait, 5)
            return result("b" if context["profile"]["goals"] == "文本搜索" else "a")
        self.model.side_effect = slow
        try:
            self.assertEqual(self.submit().status_code, 200)
            self.assertTrue(started.wait(5))
            self.onboard(goals="文本搜索")
        finally:
            release.set()
        completed = self.wait()
        self.assertEqual(completed["stage"], "ready", completed["error"])
        self.assertEqual(completed["route"]["steps"][0]["node_id"], "b")
        self.assertEqual(contexts[-1]["profile"]["goals"], "文本搜索")

    def test_sampling_checks_at_most_three_known_topics_and_skips_new_prerequisites(self):
        graph = self.store.load_graph()
        for letter in "efghijkl":
            node = copy.deepcopy(graph["nodes"][0])
            node.update(id=letter, title=letter, chapter_id="ch2")
            graph["nodes"].append(node)
        declared = {n["id"]: {"value": "new"} for n in graph["nodes"]}
        declared["j"]["value"] = "confident"
        declared["k"]["value"] = "unsure"
        declared["l"]["value"] = "confident"
        declared["d"]["value"] = "unsure"
        selected = journey.questions(graph, {"goals": ""}, declared)
        self.assertEqual(len(selected), 3)
        self.assertEqual({q["self_assessment"] for q in selected}, {"confident", "unsure"})
        self.assertTrue({q["node_id"] for q in selected} <= {"j", "k", "l", "d"})
        for ident in ("j", "k", "l"):
            declared[ident]["value"] = "new"
        selected = journey.questions(graph, {"goals": ""}, declared)
        self.assertEqual([q["node_id"] for q in selected], ["d"])
        declared["d"]["value"] = "new"
        self.assertEqual(journey.questions(graph, {"goals": ""}, declared), [])


if __name__ == "__main__":
    unittest.main()
