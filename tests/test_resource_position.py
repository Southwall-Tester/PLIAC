import unittest
import uuid
import test_access
from test_learning_workspace import publish_synthetic
from pliac.resource_position import ResourcePositions
from learning_agent.course_graph import CourseGraphError


class VideoPositionTests(unittest.TestCase):
    setUp = test_access.AccessTests.setUp
    client = test_access.AccessTests.client
    register = test_access.AccessTests.register

    def prepare(self):
        graph = self.store.load_graph('draft')
        graph['resources'][0]['format'] = 'video'
        publish_synthetic(self.store, graph)
        self.resource = graph['resources'][0]['id']
        return ResourcePositions(self.store)

    def body(self, **values):
        return {'student_id': 'synthetic', 'resource_id': self.resource, 'seconds': 12.5,
                'expected_revision': 0, 'request_id': uuid.uuid4().hex} | values

    def test_save_restore_conflict_and_no_mastery_change(self):
        service = self.prepare()
        before = self.store._read_learner('synthetic')
        body = self.body()
        result = service.save(body)
        self.assertEqual(result, service.save(body))
        self.assertEqual(service.read('synthetic', self.resource)['seconds'], 12.5)
        self.assertIsNone(service.read('other', self.resource)['seconds'])
        with self.assertRaises(CourseGraphError): service.save(self.body(seconds=20))
        for bad in (True, float('nan'), -1, 604801):
            with self.assertRaises(CourseGraphError): service.save(self.body(seconds=bad))
        self.assertEqual(self.store._read_learner('synthetic'), before)
        graph = self.store.load_graph('draft')
        graph['resources'][0]['url'] = 'https://example.test/changed.webm'
        publish_synthetic(self.store, graph)
        self.assertTrue(service.read('synthetic', self.resource)['changed'])
        self.assertIsNone(service.read('synthetic', self.resource)['seconds'])

    def test_protected_read_and_write(self):
        self.prepare()
        first, second = self.client(), self.client()
        student = self.register(first)['identity']['student']; self.register(second)
        body = self.body(student_id=student)
        self.assertEqual(first.post('/api/tutor/resource-position', json=body).status_code, 200)
        self.assertEqual(second.post('/api/tutor/resource-position', json=body).status_code, 403)
        query = {'student_id': student, 'resource_id': self.resource}
        self.assertEqual(second.get('/api/tutor/resource-position', params=query).status_code, 403)
        self.assertEqual(first.get('/api/tutor/resource-position', params=query).json()['seconds'], 12.5)

    def test_segment_draft_does_not_change_live_bookmark_until_activation(self):
        from pliac.resources import resource_choices
        service = self.prepare()
        service.save(self.body())
        graph = self.store.load_graph('draft')
        graph['resources'][0]['video_segment'] = {'start_seconds': 20, 'end_seconds': 40}
        saved = self.store.save_graph(graph, graph['version'])['graph']
        self.assertEqual(saved['resources'][0]['review_status'], 'draft')
        self.assertNotIn('reviewer', saved['resources'][0])
        self.assertEqual(service.read('synthetic', self.resource)['seconds'], 12.5)
        choices = resource_choices(self.store, 'synthetic', graph['resources'][0]['node_ids'][0])
        self.assertIsNone(choices['resources'][0]['video_segment'])
        publish_synthetic(self.store, saved)
        changed = service.read('synthetic', self.resource)
        self.assertTrue(changed['changed'])
        self.assertIsNone(changed['seconds'])
        self.assertEqual(changed['revision'], 1)
        self.assertEqual(self.store._read_learner('synthetic')['evidence'], [])
