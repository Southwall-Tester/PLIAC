import unittest
import test_assessment
from pliac.workspace import LearningWorkspace
from pliac.tutor import teaching_context
from learning_agent.course_graph import CourseGraphError


class PreferenceTests(unittest.TestCase):
    setUp = test_assessment.AssessmentTests.setUp
    payload = test_assessment.AssessmentTests.payload

    def test_preferences_persist_without_resetting_plan_or_adding_evidence(self):
        service = LearningWorkspace(self.store)
        service.onboard(self.payload(goals='goal', agent_guided=True, start_node_id='a', plan_mode='topic'))
        before = self.store._read_learner('synthetic')
        request = self.payload(interests=['体育', '体育'], explanation_preferences='先例子后公式')
        service.preferences(request)
        service.preferences(request)
        after = self.store._read_learner('synthetic')
        self.assertEqual(after['workspace']['teaching_flow'], before['workspace']['teaching_flow'])
        self.assertEqual(after['evidence'], before['evidence'])
        self.assertEqual(after['diagnoses'], before['diagnoses'])
        self.assertEqual(after['version'], before['version'] + 1)
        context = teaching_context(self.store.load_graph(), self.store.load_learner('synthetic'), 'a', 'explain')
        self.assertEqual(context['learner']['interests'], ['体育'])
        self.assertEqual(context['learner']['explanation_preferences'], '先例子后公式')
        service.preferences(self.payload(interests=[], explanation_preferences=''))
        context = teaching_context(self.store.load_graph(), self.store.load_learner('synthetic'), 'a', 'explain')
        self.assertEqual(context['learner']['explanation_preferences'], '')
        self.assertEqual(context['learner']['interests'], [])

    def test_limits_and_conflicts_do_not_overwrite(self):
        service = LearningWorkspace(self.store)
        stale = self.payload(interests=['old'])
        service.preferences(self.payload(interests=['new']))
        for payload in (stale, self.payload(interests=['x'] * 31), self.payload(explanation_preferences='x' * 1001)):
            with self.assertRaises(CourseGraphError):
                service.preferences(payload)
        self.assertEqual(self.store._read_learner('synthetic')['profile']['interests'], ['new'])
