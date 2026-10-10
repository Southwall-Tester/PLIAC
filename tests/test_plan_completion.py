"""Plan closure uses real saved synthetic assessments, not mocked mastery flags."""
import unittest
import copy

import test_assessment
from pliac.learning_plan import LearningPlans, PlanProposal, plan_context
from pliac.notebook import Notebook
from pliac.reports import StageReports


class PlanCompletionTests(unittest.TestCase):
    setUp = test_assessment.AssessmentTests.setUp
    payload = test_assessment.AssessmentTests.payload

    def adopt(self, targets=("a",)):
        plans = LearningPlans(self.store)
        state = plans.onboard(self.payload(goals="合成目标", plan_mode="topic", agent_guided=True))
        request = state["workspace"]["teaching_flow"]["plan_request"]
        context = plan_context(self.store.load_graph(), self.store.load_learner("synthetic"), request)
        proposal = PlanProposal(status="proposed", summary="合成范围", target_node_ids=list(targets),
            learning_order=list(targets), start_node_id="a", rationale="合成课程依据", clarification="")
        state = plans.save_proposal(self.payload(plan_request_id=request["id"]), proposal, {}, context)
        ident = state["workspace"]["learning_plans"][-1]["id"]
        plans.accept(self.payload(plan_id=ident))

    def evaluate(self, assisted=False):
        state = self.service.start(self.payload(node_id="a"))
        ident = state["workspace"]["assessments"][-1]["id"]
        if assisted:
            self.service.start(self.payload(node_id="a"))
            ident = self.service.view("synthetic")["workspace"]["assessments"][-1]["id"]
        self.service.submit(self.payload(assessment_id=ident, answer="synthetic answer"))
        request = self.payload(assessment_id=ident)
        return request, self.service.save_result(request, self.proposal, {"model": "synthetic"})

    def test_supported_scope_closes_once_and_report_is_scoped_snapshot(self):
        Notebook(self.store).save(self.payload(node_id="b", text="Unrelated note"))
        self.adopt()
        request, state = self.evaluate()
        report = state["workspace"]["stage_reports"][-1]
        self.assertEqual(set(report["nodes"]), {"a"})
        self.assertEqual(report["notes"], [])
        self.assertEqual(report["learner_version"], state["learner"]["version"])
        flow = state["workspace"]["teaching_flow"]
        self.assertFalse(flow["enabled"])
        self.assertIsNone(flow["pending"])
        self.assertEqual(state["workspace"]["learning_plans"][-1]["completion"]["report_id"], report["id"])
        self.service.save_result(request, self.proposal, {})
        Notebook(self.store).save(self.payload(node_id="a", text="Later note"))
        self.assertEqual(self.service.view("synthetic")["workspace"]["stage_reports"], [report])
        self.assertNotIn("TEACHER_ONLY", str(report))

    def test_partial_scope_does_not_close(self):
        self.adopt(("a", "b"))
        _, state = self.evaluate()
        self.assertNotIn("completion", state["workspace"]["learning_plans"][-1])
        self.assertEqual(state["workspace"].get("stage_reports", []), [])

    def test_exposed_answer_does_not_close(self):
        self.adopt()
        _, state = self.evaluate(assisted=True)
        self.assertNotIn("completion", state["workspace"]["learning_plans"][-1])
        self.assertNotEqual(state["learner"]["states"]["a"]["status"], "mastered")

    def test_hundred_existing_reports_do_not_silently_block_completion(self):
        self.adopt()
        Notebook(self.store).save(self.payload(node_id='b', text='Synthetic previous learning'))
        sample = StageReports(self.store).save(self.payload())['workspace']['stage_reports'][0]
        learner = self.store._read_learner('synthetic')
        historical = [copy.deepcopy(sample) | {'id': f'historical-{index}'} for index in range(100)]
        learner['workspace']['stage_reports'] = copy.deepcopy(historical)
        self.store._commit(learner)
        request, state = self.evaluate()
        reports = state['workspace']['stage_reports']
        self.assertEqual(len(reports), 101)
        self.assertEqual(reports[:100], historical)
        self.assertFalse(state['workspace']['teaching_flow']['enabled'])
        self.assertEqual(state['workspace']['learning_plans'][-1]['completion']['report_id'], reports[-1]['id'])
        again = self.service.save_result(request, self.proposal, {})
        self.assertEqual(again['workspace']['stage_reports'], reports)
        self.assertEqual(again['learner']['states']['a']['status'], 'mastered')

    def test_new_goal_keeps_completed_scope_and_immutable_report(self):
        self.adopt()
        _, completed = self.evaluate()
        reports = copy.deepcopy(completed['workspace']['stage_reports'])
        plans = copy.deepcopy(completed['workspace']['learning_plans'])
        state = LearningPlans(self.store).onboard(self.payload(goals='新的合成目标', plan_mode='topic', agent_guided=True))
        self.assertEqual(state['workspace']['stage_reports'], reports)
        self.assertEqual(state['workspace']['learning_plans'], plans)
        self.assertTrue(state['workspace']['teaching_flow']['enabled'])
        self.assertIsNotNone(state['workspace']['teaching_flow']['plan_request'])
        self.assertNotEqual(state['learner']['profile']['goals'], reports[-1]['goals'])


if __name__ == "__main__":
    unittest.main()
