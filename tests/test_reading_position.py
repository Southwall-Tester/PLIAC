import unittest
import uuid
import sqlite3
from contextlib import closing
from unittest.mock import patch
import test_access

from pliac.reading_position import ReadingPositions, recent_reading
from learning_agent.course_graph import CourseGraphError


class ReadingTests(unittest.TestCase):
    setUp = test_access.AccessTests.setUp
    client = test_access.AccessTests.client
    register = test_access.AccessTests.register

    def seed(self, student):
        learner = self.store._read_learner(student)
        learner['workspace'] = {'tutor_turns': [{'request_id': 'saved', 'course_version': 1, 'proposal': {'blocks': [{'text': 'synthetic paragraph'}]}}]}
        self.store._commit(learner)

    def body(self, **fields):
        return {'student_id': 'synthetic', 'material_id': 'saved', 'request_id': uuid.uuid4().hex,
                'expected_revision': 0, 'anchor': 'paragraph-0', 'offset': 24} | fields

    def test_idempotent_separate_revision_and_no_learning_evidence(self):
        self.seed('synthetic'); service = ReadingPositions(self.store)
        before = self.store._read_learner('synthetic')
        payload = self.body()
        self.assertEqual(service.read('synthetic', 'saved')['revision'], 0)
        first = service.save(payload)
        self.assertEqual(first, service.save(payload))
        self.assertEqual(first['revision'], 1)
        self.assertEqual(before, self.store._read_learner('synthetic'))
        with self.assertRaises(CourseGraphError):
            service.save(self.body(offset=60))
        with self.assertRaises(CourseGraphError):
            service.save(payload | {'offset': 25})

    def test_invalid_anchor_owner_and_offsets(self):
        self.seed('synthetic'); service = ReadingPositions(self.store)
        for changes in ({'anchor': 'paragraph-1'}, {'student_id': 'other'}, {'offset': float('nan')}, {'offset': True}, {'expected_revision': True}):
            with self.subTest(changes=changes), self.assertRaises(CourseGraphError):
                service.save(self.body(**changes))

    def test_material_change_does_not_restore_old_anchor(self):
        self.seed('synthetic'); service = ReadingPositions(self.store)
        service.save(self.body())
        learner = self.store._read_learner('synthetic')
        learner['workspace']['tutor_turns'][0]['proposal']['blocks'][0]['text'] = 'different'
        self.store._commit(learner)
        self.assertEqual(service.read('synthetic', 'saved'), {'revision': 1, 'position': None, 'changed': True})

    def test_http_identity_isolation(self):
        first, second = self.client(), self.client()
        student = self.register(first)['identity']['student']; self.register(second)
        self.seed(student)
        body = self.body(student_id=student)
        self.assertEqual(first.post('/api/learning/reading-position', json=body).status_code, 200)
        self.assertEqual(second.post('/api/learning/reading-position', json=body).status_code, 403)
        self.assertEqual(second.get('/api/learning/reading-position', params={'student_id': student, 'material_id': 'saved'}).status_code, 403)
        self.assertEqual(first.get('/api/learning/continue', params={'student_id': student}).json()['items'][0]['material_id'], 'saved')
        self.assertEqual(second.get('/api/learning/continue', params={'student_id': student}).status_code, 403)

    def test_recent_index_excludes_other_people_and_changed_material(self):
        self.seed('synthetic'); service = ReadingPositions(self.store)
        with patch('pliac.reading_position.time.time', return_value=1234):
            service.save(self.body())
        self.assertEqual(recent_reading(self.store, 'other'), {'items': []})
        result = recent_reading(self.store, 'synthetic')['items']
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['updated_at'], 1234)
        self.assertEqual(result[0]['course_id'], self.store.load_graph('draft')['id'])
        learner = self.store._read_learner('synthetic')
        learner['workspace']['tutor_turns'][0]['proposal']['blocks'][0]['text'] = 'changed'
        self.store._commit(learner)
        self.assertEqual(recent_reading(self.store, 'synthetic'), {'items': []})

    def test_existing_position_database_migrates_without_losing_bookmark(self):
        self.seed('synthetic'); service = ReadingPositions(self.store)
        _, signature = service.material('synthetic', 'saved')
        with closing(sqlite3.connect(service.path)) as db:
            db.execute('CREATE TABLE positions(student TEXT, material TEXT, signature TEXT, anchor TEXT, offset REAL, revision INTEGER, request_id TEXT, PRIMARY KEY(student,material))')
            db.execute('INSERT INTO positions VALUES (?,?,?,?,?,?,?)', ('synthetic', 'saved', signature, 'top', 12, 1, 'old'))
            db.commit()
        self.assertEqual(service.read('synthetic', 'saved')['position'], {'anchor': 'top', 'offset': 12})
        self.assertEqual(service.recent('synthetic')[0]['updated_at'], 0)

    def test_cross_course_index_sorts_actual_save_time(self):
        from learning_agent.course_catalog import create_course, resolve_course
        self.seed('synthetic')
        created = create_course(self.store, 'synthetic second course')
        second = resolve_course(self.store, created['course']['id'])
        learner = second._read_learner('synthetic')
        learner['workspace'] = self.store._read_learner('synthetic')['workspace']
        second._commit(learner)
        with patch('pliac.reading_position.time.time', return_value=100):
            ReadingPositions(self.store).save(self.body())
        with patch('pliac.reading_position.time.time', return_value=200):
            ReadingPositions(second).save(self.body())
        items = recent_reading(self.store, 'synthetic')['items']
        self.assertEqual([item['updated_at'] for item in items], [200, 100])
        self.assertEqual(items[0]['course_id'], created['course']['id'])
