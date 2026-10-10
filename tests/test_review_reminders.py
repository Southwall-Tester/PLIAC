"""Reminder state is derived read-only and scoped to the authenticated learner."""
import copy
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import test_assessment
import test_access
from test_learning_workspace import publish_synthetic
from learning_agent.course_graph import CourseGraphStore
from pliac.review_reminders import review_reminders


class ReminderTests(unittest.TestCase):
    setUp = test_assessment.AssessmentTests.setUp
    payload = test_assessment.AssessmentTests.payload

    def finish(self, passed):
        ident = self.service.start(self.payload(node_id='a'))['workspace']['assessments'][-1]['id']
        self.service.submit(self.payload(assessment_id=ident, answer='synthetic answer'))
        proposal = self.proposal.model_copy(deep=True)
        proposal.criteria[0].outcome = 'met' if passed else 'not_met'
        self.service.save_result(self.payload(assessment_id=ident), proposal, {})

    def test_empty_learner_and_read_only_remedial_reminder(self):
        self.assertEqual(review_reminders(self.store, 'synthetic')['items'], [])
        self.finish(False)
        before = copy.deepcopy(self.store._read_learner('synthetic'))
        items = review_reminders(self.store, 'synthetic')['items']
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]['kind'], 'needs_work')
        self.assertEqual(items[0]['node_id'], 'a')
        self.assertEqual(self.store._read_learner('synthetic'), before)
        self.assertEqual(review_reminders(self.store, 'other')['items'], [])

    def test_due_and_changed_content_are_distinct(self):
        self.finish(True)
        self.assertEqual(review_reminders(self.store, 'synthetic')['items'], [])
        with patch.object(CourseGraphStore, '_now', return_value=datetime.now(timezone.utc) + timedelta(days=100)):
            self.assertEqual(review_reminders(self.store, 'synthetic')['items'][0]['kind'], 'review_due')
        graph = self.store.load_graph('draft')
        graph['nodes'][0]['description'] += ' Synthetic course revision.'
        publish_synthetic(self.store, graph)
        self.assertEqual(review_reminders(self.store, 'synthetic')['items'][0]['kind'], 'version_changed')


class ReminderAccessTests(unittest.TestCase):
    setUp = test_access.AccessTests.setUp
    client = test_access.AccessTests.client
    register = test_access.AccessTests.register

    def test_http_owner_and_no_cache(self):
        first, second = self.client(), self.client()
        student = self.register(first)['identity']['student']
        self.register(second)
        response = first.get('/api/learning/review-reminders', params={'student_id': student})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.headers['cache-control'], 'no-store')
        self.assertEqual(second.get('/api/learning/review-reminders', params={'student_id': student}).status_code, 403)
