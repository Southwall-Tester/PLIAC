"""Cross-activity assistance uses actual lab operations and synthetic learners."""
import asyncio
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from learning_agent.acceptance_course import AcceptanceCourseStore
from learning_agent.course_graph import CourseGraphStore
from pliac.assessment import AssessmentService, evaluate_answer
from pliac.ml_lab import MLLab


class AssessmentLabHelpTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.store = AcceptanceCourseStore(CourseGraphStore(output_dir=Path(temp.name)))
        self.lab = MLLab(self.store)
        self.assessment = AssessmentService(self.store)
        self.student = 'synthetic-lab-assessment'
        self.lab.act('start', self.payload(scene='space'))

    def payload(self, **fields):
        return {'student_id': self.student, 'course_version': 1,
                'expected_version': self.store.load_learner(self.student)['version'],
                'request_id': uuid.uuid4().hex, **fields}

    def lab_act(self, operation, **fields):
        session = self.lab.view(self.student)['active']['id']
        return self.lab.act(operation, self.payload(session_id=session, **fields))

    def start(self, node='sample'):
        state = self.assessment.start(self.payload(node_id=node))
        return state['workspace']['assessments'][-1]['id']

    def submit(self, ident):
        record = next(item for item in self.store._read_learner(self.student)['workspace']['assessments'] if item['id'] == ident)
        request = self.payload(assessment_id=ident, answer=record['answer_key'])
        self.assessment.submit(request)
        self.assessment.submit(request)
        return self.assessment.assessment_snapshot(self.student, ident)[0]

    def test_related_hint_prevents_independent_mastery_and_freezes_submission(self):
        ident = self.start()
        with patch.object(self.store, '_stamp', return_value='2000-01-01T00:00:00Z'):
            self.lab_act('hint')
        record = self.submit(ident)
        self.assertEqual(len(record['assistance_lab_event_ids']), 1)
        self.assertEqual(record['assistance_turn_ids'], [])
        self.assertEqual(record['lab_assistance_policy'], 'saved-order-v1')
        self.assertEqual(record['prompt_level'], 1)
        proposal, metadata = asyncio.run(evaluate_answer(record, None))
        state = self.assessment.save_result(self.payload(assessment_id=ident), proposal, metadata)
        self.assertEqual(state['workspace']['assessments'][-1]['result']['status'], 'assisted_success')
        self.assertNotEqual(state['learner']['states']['sample']['status'], 'mastered')
        self.assertEqual(state['learner']['evidence'][-1]['context']['assistance_lab_event_ids'], record['assistance_lab_event_ids'])
        self.lab_act('hint')
        saved = self.assessment.assessment_snapshot(self.student, ident)[0]
        self.assertEqual(saved['assistance_lab_event_ids'], record['assistance_lab_event_ids'])

    def test_prior_hint_and_unrelated_node_do_not_taint_independent_answer(self):
        self.lab_act('hint')
        ident = self.start()
        self.assertEqual(self.submit(ident)['assistance_lab_event_ids'], [])
        other = self.start('partition')
        self.lab_act('hint')  # inspect maps only sample and leakage
        record = self.submit(other)
        self.assertEqual(record['assistance_lab_event_ids'], [])
        self.assertEqual(record['prompt_level'], 0)

    def test_failed_check_feedback_is_help_but_decline_and_pass_are_not(self):
        for _ in range(2):
            self.lab_act('check', answer={'target': 'receipt'})
        ident = self.start()
        self.lab_act('support', task_id='inspect', choice='continue')
        self.lab_act('check', answer={'target': 'target', 'features': 'sensors', 'timing': 'after'})
        self.assertEqual(self.submit(ident)['assistance_lab_event_ids'], [])

        # Fresh learner tests failure feedback delivered during a new assessment.
        self.student = 'synthetic-failure'
        self.lab.act('start', self.payload(scene='space'))
        ident = self.start()
        self.lab_act('check', answer={'target': 'receipt'})
        self.lab_act('check', answer={'target': 'receipt'})
        self.lab_act('support', task_id='inspect', choice='hint')
        record = self.submit(ident)
        events = self.store._read_learner(self.student)['workspace']['events']
        kinds = [event['kind'] for event in events if event['id'] in record['assistance_lab_event_ids']]
        self.assertEqual(kinds, ['ml_lab_check', 'ml_lab_check', 'ml_lab_support_choice'])

    def test_historical_mapping_and_legacy_task_are_explicit(self):
        ident = self.start()
        def legacy(graph, learner, workspace):
            workspace['assessments'][-1].pop('prior_lab_help_event_ids')
        self.assessment._mutate(self.payload(), 'synthetic_legacy', legacy)
        with patch.object(self.store, '_stamp', return_value='2099-01-01T00:00:00Z'):
            self.lab_act('hint')
        record = self.submit(ident)
        self.assertEqual(record['lab_assistance_policy'], 'legacy-time-v1')
        self.assertEqual(len(record['assistance_lab_event_ids']), 1)

        from pliac.lab_context import assessment_lab_help
        workspace = self.store._read_learner(self.student)['workspace']
        self.assertEqual(assessment_lab_help(workspace, 'sample', 2), [])
        workspace['ml_lab']['sessions'][0]['node_mapping']['sample'] = 'other-node'
        self.assertEqual(assessment_lab_help(workspace, 'sample', 1), [])


if __name__ == '__main__':
    unittest.main()
