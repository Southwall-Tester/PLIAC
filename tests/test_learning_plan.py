"""Scope negotiation against authored course structure and isolated learner state."""
import json
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient
from learning_agent.course_graph import CourseGraphStore, CourseGraphError
from pliac.main import app
from pliac.workspace import LearningWorkspace
from pliac.learning_plan import LearningPlans, PlanProposal, plan_context, validate_plan, prerequisites, plan_focus
from test_learning_workspace import platform_fixture, publish_synthetic


class LearningPlanTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        seed = root / "seed.json"
        seed.write_text(json.dumps(platform_fixture()), encoding="utf-8")
        self.store = CourseGraphStore(seed, root / "records")
        publish_synthetic(self.store)
        scope = patch("learning_agent.api.store", self.store)
        scope.start(); self.addCleanup(scope.stop)
        self.client = TestClient(app); self.addCleanup(self.client.close)
        self.workspace = LearningWorkspace(self.store)
        self.plans = LearningPlans(self.store)
        self.proposal = PlanProposal(status="proposed", summary="系统学习合成课程", target_node_ids=list("abcd"),
            learning_order=list("abcd"), start_node_id="a", rationale="依据真实先修关系安排", clarification="")

    def payload(self, **fields):
        return {"student_id": "synthetic", "request_id": uuid.uuid4().hex, "expected_version": self.store.load_learner("synthetic")["version"],
                "course_version": self.store.load_graph()["version"]} | fields

    def begin(self, **fields):
        return self.workspace.onboard(self.payload(goals="系统学习本课程", plan_mode="systematic", preferred_form="mixed",
                                                   start_node_id="", agent_guided=True) | fields)

    def context(self):
        learner = self.store.load_learner("synthetic")
        return plan_context(self.store.load_graph(), learner, learner["workspace"]["teaching_flow"]["plan_request"])

    def request(self):
        flow = self.workspace.view("synthetic")["workspace"]["teaching_flow"]
        return self.payload(plan_request_id=flow["plan_request"]["id"])

    def generate(self, proposal=None):
        with patch("pliac.tutor_api.configured_api", return_value=None), patch("pliac.learning_plan.generate_plan", AsyncMock(return_value=(proposal or self.proposal, {"model": "synthetic"}))) as model:
            response = self.client.post("/api/tutor/plan", json=self.request())
            self.assertEqual(response.status_code, 200, response.text)
            return response.json(), model

    def test_no_silent_scope_reduction_or_fabricated_nodes(self):
        self.begin()
        context = self.context()
        self.assertEqual(validate_plan(self.proposal, context), self.proposal)
        for changes in ({"target_node_ids": ["a"], "learning_order": ["a"]},
                        {"target_node_ids": ["a", "b", "c", "foreign"], "learning_order": ["a", "b", "c", "foreign"]},
                        {"learning_order": ["a", "a", "c", "d"]}, {"learning_order": ["b", "c", "a", "d"]}):
            with self.subTest(changes=changes), self.assertRaises(CourseGraphError):
                validate_plan(self.proposal.model_copy(update=changes), context)
        self.assertNotIn("TEACHER_ONLY", json.dumps(context))

    def test_course_change_requires_new_scope_before_resuming(self):
        from pliac.teaching_flow import TeachingFlow
        self.begin()
        result, _ = self.generate()
        plan = result["plan"]
        self.plans.accept(self.payload(plan_id=plan["id"], start_node_id="a"))
        graph = self.store.load_graph("draft")
        graph["nodes"][0]["description"] += " Synthetic updated scope."
        publish_synthetic(self.store, graph)
        flow = TeachingFlow(self.store)
        for operation in ("resume", "choose", "continue"):
            with self.subTest(operation=operation), self.assertRaises(CourseGraphError) as error:
                flow.command(self.payload(operation=operation, node_id="a"))
            self.assertEqual(error.exception.status_code, 409)
        paused = flow.command(self.payload(operation="pause"))
        self.assertFalse(paused["workspace"]["teaching_flow"]["enabled"])
        current = self.begin()
        self.assertEqual(current["workspace"]["learning_plans"][0], plan)
        self.assertEqual(current["workspace"]["teaching_flow"]["plan_request"]["course_version"], graph["version"] + 1)
        result, _ = self.generate()
        accepted = self.plans.accept(self.payload(plan_id=result["plan"]["id"], start_node_id="a"))
        self.assertEqual(len(accepted["workspace"]["learning_plans"]), 2)
        self.assertTrue(accepted["workspace"]["teaching_flow"]["enabled"])

    def test_prerequisites_are_not_confusable_relations_and_anchor_is_kept(self):
        self.begin(plan_mode="topic", start_node_id="c")
        proposal = self.proposal.model_copy(update={"target_node_ids": ["c"], "learning_order": ["c"], "start_node_id": "c"})
        validate_plan(proposal, self.context())
        self.assertEqual(prerequisites(self.store.load_graph(), ["c"]), ["a", "b"])
        with self.assertRaises(CourseGraphError):
            validate_plan(self.proposal, self.context())

    def test_missing_lab_or_unavailable_goal_requires_clarification(self):
        self.begin(plan_mode="task", preferred_form="lab")
        with self.assertRaises(CourseGraphError):
            validate_plan(self.proposal, self.context())
        clarify = PlanProposal(status="clarify", summary="现有课程尚未绑定实验", target_node_ids=[], learning_order=[], start_node_id="",
            rationale="不能创建不存在的实验", clarification="是否先学习本课程概念？")
        result, _ = self.generate(clarify)
        response = self.client.post("/api/tutor/plan/apply", json=self.payload(plan_id=result["plan"]["id"]))
        self.assertEqual(response.status_code, 409)
        self.assertEqual(result["state"]["learner"]["evidence"], [])

    def test_generation_is_idempotent_and_adoption_does_not_mark_mastery(self):
        self.begin()
        request = self.request()
        with patch("pliac.tutor_api.configured_api", return_value=None), patch("pliac.learning_plan.generate_plan", AsyncMock(return_value=(self.proposal, {"model": "synthetic"}))) as model:
            first = self.client.post("/api/tutor/plan", json=request)
            repeat = self.client.post("/api/tutor/plan", json=request | {"request_id": uuid.uuid4().hex})
        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual(repeat.status_code, 200, repeat.text)
        self.assertEqual(model.await_count, 1)
        record = first.json()["plan"]
        self.assertEqual(len(repeat.json()["state"]["workspace"]["learning_plans"]), 1)
        apply = self.payload(plan_id=record["id"], start_node_id="c")
        result = self.client.post("/api/tutor/plan/apply", json=apply)
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(self.client.post("/api/tutor/plan/apply", json=apply).status_code, 200)
        state = result.json()
        self.assertEqual(state["workspace"]["teaching_flow"]["pending"]["node_id"], "c")
        self.assertEqual(state["workspace"]["teaching_flow"]["pending"]["reason"], "plan_accepted")
        self.assertEqual(state["learner"]["evidence"], [])
        self.assertEqual(state["learner"]["diagnoses"], [])

    def test_goal_changed_during_generation_rejects_stale_plan(self):
        self.begin()
        async def generate(*args):
            self.begin(goals="新的目标", plan_mode="topic")
            return self.proposal, {"model": "synthetic"}
        with patch("pliac.tutor_api.configured_api", return_value=None), patch("pliac.learning_plan.generate_plan", generate):
            response = self.client.post("/api/tutor/plan", json=self.request())
        self.assertEqual(response.status_code, 409)
        state = self.workspace.view("synthetic")
        self.assertEqual(state["workspace"].get("learning_plans", []), [])
        self.assertEqual(state["learner"]["profile"]["goals"], "新的目标")

    def test_paused_planning_does_not_call_model(self):
        from pliac.teaching_flow import TeachingFlow
        self.begin()
        TeachingFlow(self.store).command(self.payload(operation="pause"))
        with patch("pliac.learning_plan.generate_plan", AsyncMock()) as model:
            response = self.client.post("/api/tutor/plan", json=self.request())
        self.assertEqual(response.status_code, 409)
        model.assert_not_awaited()

    def test_saved_request_cannot_claim_a_different_course_version(self):
        self.begin()
        request = self.request()
        self.generate()
        with patch("pliac.learning_plan.generate_plan", AsyncMock()) as model:
            response = self.client.post("/api/tutor/plan", json=request | {"course_version": request["course_version"] + 1})
        self.assertEqual(response.status_code, 409)
        model.assert_not_awaited()

    def test_course_update_prevents_old_plan_adoption(self):
        self.begin()
        saved, _ = self.generate()
        publish_synthetic(self.store)
        response = self.client.post("/api/tutor/plan/apply", json=self.payload(plan_id=saved["plan"]["id"]))
        self.assertEqual(response.status_code, 409)

    def test_only_supported_mastery_moves_to_next_planned_node(self):
        self.begin()
        saved, _ = self.generate()
        self.plans.accept(self.payload(plan_id=saved["plan"]["id"]))
        learner = self.store.load_learner("synthetic")
        graph = self.store.load_graph()
        trigger = {"reason": "assessment_evaluated"}
        for status in ("unknown", "uncertain", "needs_review"):
            learner["states"]["a"]["status"] = status
            self.assertEqual(plan_focus(graph, learner, "a", trigger), "a")
        learner["states"]["a"]["status"] = "mastered"
        self.assertEqual(plan_focus(graph, learner, "a", trigger), "b")
        self.assertEqual(plan_focus(graph, learner, "a", {"reason": "reading_finished"}), "a")
        learner["states"]["b"]["status"] = "mastered"
        self.assertEqual(plan_focus(graph, learner, "a", trigger), "c")


if __name__ == "__main__":
    unittest.main()
