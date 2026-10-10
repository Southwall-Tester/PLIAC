import copy
import unittest
from unittest.mock import Mock
import test_access
from test_recommendation import fixture, resource
from pliac.resources import resource_choices


class ChoiceTests(unittest.TestCase):
    def test_video_segment_contract_and_context(self):
        from learning_agent.course_graph import validate_graph, CourseGraphError
        from test_course_graph import fixture as course_fixture
        from pliac.tutor import teaching_context
        graph = course_fixture()
        item = graph['resources'][0]
        item.update(format='video', video_segment={'start_seconds': 12.5, 'end_seconds': 50})
        validate_graph(graph)
        available = copy.deepcopy(graph)
        available['resources'][0]['review_status'] = 'auto_validated'
        context = teaching_context(available, {'version': 0, 'profile': {}, 'states': {}}, item['node_ids'][0], '合成问题')
        self.assertEqual(context['resources'][0]['video_segment'], item['video_segment'])
        for segment in (None, {}, {'start_seconds': True, 'end_seconds': 2},
                        {'start_seconds': 2, 'end_seconds': 1}, {'start_seconds': 0, 'end_seconds': float('inf')},
                        {'start_seconds': -1, 'end_seconds': 2}, {'start_seconds': 0, 'end_seconds': 604801}):
            with self.subTest(segment=segment), self.assertRaises(CourseGraphError):
                altered = copy.deepcopy(graph)
                altered['resources'][0]['video_segment'] = segment
                validate_graph(altered)
        item['format'] = 'lesson'
        with self.assertRaises(CourseGraphError):
            validate_graph(graph)

    def test_pending_prerequisites_warn_without_hiding_target_material(self):
        graph = fixture() | {'version': 2}
        graph['resources'] = [resource('target', ['d'], prereqs=['c'], review='auto_validated', kind='video'),
                              resource('draft', ['d'], review='draft'), resource('base', ['a'])]
        store = Mock()
        store._require_graph.return_value = graph
        store._derive.return_value = {'states': {}}
        before = copy.deepcopy(graph)
        result = resource_choices(store, 'synthetic', 'd')
        items = {item['id']: item for item in result['resources']}
        self.assertEqual(set(items), {'target', 'base'})
        self.assertTrue(items['target']['for_current'])
        self.assertEqual(items['target']['missing_prerequisites'], [{'id': 'c', 'title': 'C'}])
        self.assertFalse(items['base']['for_current'])
        self.assertEqual(graph, before)
        store._commit.assert_not_called()

    def test_automatic_resource_is_not_mislabeled_human_review(self):
        graph = fixture() | {'version': 1}
        graph['resources'] = [resource('auto', ['a'], review='auto_validated')]
        store = Mock(); store._require_graph.return_value = graph
        store._derive.return_value = {'states': {}}
        reason = resource_choices(store, 'synthetic', 'a')['resources'][0]['reason']
        self.assertIn('自动核验', reason)
        self.assertNotIn('人工审核', reason)


class ChoiceAccessTests(unittest.TestCase):
    setUp = test_access.AccessTests.setUp
    client = test_access.AccessTests.client
    register = test_access.AccessTests.register

    def test_actual_route_owner_and_read_only(self):
        first, second = self.client(), self.client()
        student = self.register(first)['identity']['student']; self.register(second)
        before = self.store._read_learner(student)
        query = {'student_id': student, 'node_id': 'a'}
        result = first.get('/api/tutor/resources', params=query)
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(result.headers['cache-control'], 'no-store')
        self.assertEqual(second.get('/api/tutor/resources', params=query).status_code, 403)
        self.assertEqual(self.store._read_learner(student), before)
