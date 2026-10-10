"""Synthetic activity times; no device, video decoder or model."""
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from pliac.media_timeline import activity_timeline


class TimelineTests(unittest.TestCase):
    def setUp(self):
        self.events = []
        self.store = SimpleNamespace(_read_learner=lambda student: {'workspace': {'events': self.events if student == 'owner' else []}})
        self.session = {'status': 'closed', 'activity_kind': 'lab', 'activity_id': 'lab-one', 'started': 1000,
            'clips': [{'sequence': 0, 'start_ms': 0, 'duration_ms': 1000}, {'sequence': 1, 'start_ms': 2000, 'duration_ms': 1000}]}

    def add(self, ident, offset, **fields):
        self.events.append({'id': ident, 'kind': 'ml_lab_check', 'session_id': 'lab-one', 'passed': False,
            'created_at': datetime.fromtimestamp(1000 + offset, timezone.utc).isoformat(), **fields})

    def test_scope_gaps_and_whitelisted_fields(self):
        self.add('before', -1)
        self.add('in-clip', .5, answer='PRIVATE ANSWER', secret='PRIVATE SECRET')
        self.add('gap', 1.5)
        self.add('after', 5)
        self.add('other', .5, session_id='another-lab')
        self.add('unrelated', .5, kind='onboarding')
        items = activity_timeline(self.store, 'owner', self.session)['items']
        self.assertEqual([item['id'] for item in items], ['in-clip', 'gap'])
        self.assertEqual(items[0]['sequences'], [0])
        self.assertEqual(items[1]['sequences'], [])
        self.assertNotIn('PRIVATE', str(items))
        self.assertEqual(activity_timeline(self.store, 'other', self.session)['items'], [])

    def test_revoked_expired_and_empty_media_have_no_timeline(self):
        self.add('check', .5)
        for changes in ({'status': 'revoked'}, {'status': 'expired'}, {'clips': []}):
            self.assertEqual(activity_timeline(self.store, 'owner', self.session | changes)['items'], [])

    def test_assessment_and_material_require_explicit_activity_match(self):
        self.add('assessment', .5, kind='assessment_submitted', assessment_id='assessment-one')
        self.add('material', .5, kind='teaching_reading_finished', turn_id='material-one')
        for kind, ident in [('assessment', 'assessment-one'), ('material', 'material-one')]:
            result = activity_timeline(self.store, 'owner', self.session | {'activity_kind': kind, 'activity_id': ident})
            self.assertEqual([item['id'] for item in result['items']], [kind])
