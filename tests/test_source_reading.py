import unittest
import uuid
from unittest.mock import patch

import test_source_preview
from pliac.source_reading import SourceReading
from learning_agent.course_graph import CourseGraphError


class SourceReadingTests(unittest.TestCase):
    setUp = test_source_preview.SourcePreviewTests.setUp
    client = test_source_preview.SourcePreviewTests.client
    register = test_source_preview.SourcePreviewTests.register
    prepare = test_source_preview.SourcePreviewTests.prepare

    def setup_source(self, student='synthetic'):
        self.prepare(student)
        self.path = self.store.output_dir / 'source.txt'
        self.path.write_text('synthetic original', encoding='utf-8')
        self.documents.source.return_value = self.path
        return SourceReading(self.store, self.documents)

    def body(self, **changes):
        return {'student_id': 'synthetic', 'material_id': 'saved', 'source_id': self.source['id'],
                'mode': 'page', 'zoom': 150, 'expected_revision': 0, 'request_id': uuid.uuid4().hex} | changes

    def test_save_restore_idempotence_and_no_learning_mutation(self):
        service = self.setup_source()
        before = self.store._read_learner('synthetic')
        with patch.object(self.store, 'load_graph', return_value=self.graph):
            self.assertEqual(service.read('synthetic', 'saved', self.source['id'])['revision'], 0)
            body = self.body()
            value = service.save(body)
            self.assertEqual(value, service.save(body))
            self.assertEqual(value['position']['page'], 2)
            self.assertEqual(value['position']['zoom'], 150)
            with self.assertRaises(CourseGraphError):
                service.save(self.body(zoom=200))
            with self.assertRaises(CourseGraphError):
                service.save(body | {'mode': 'text'})
        self.assertEqual(before, self.store._read_learner('synthetic'))

    def test_changed_original_and_unlinked_reference_do_not_restore(self):
        service = self.setup_source()
        with patch.object(self.store, 'load_graph', return_value=self.graph):
            service.save(self.body())
            self.path.write_text('changed original', encoding='utf-8')
            value = service.read('synthetic', 'saved', self.source['id'])
            self.assertTrue(value['changed']); self.assertIsNone(value['position'])
            for change in ({'zoom': True}, {'zoom': 400}, {'mode': 'html'}, {'student_id': 'other'}):
                with self.assertRaises(CourseGraphError):
                    service.save(self.body(**change))
        with patch.object(self.store, 'load_graph', return_value={'nodes': []}), self.assertRaises(CourseGraphError):
            service.read('synthetic', 'saved', self.source['id'])

    def test_protected_api_isolation(self):
        first, second = self.client(), self.client()
        student = self.register(first)['identity']['student']; self.register(second)
        self.setup_source(student)
        body = self.body(student_id=student)
        query = {key: body[key] for key in ('student_id', 'material_id', 'source_id')}
        with patch.object(self.store, 'load_graph', return_value=self.graph), patch('learning_agent.document_api.document_store', self.documents):
            self.assertEqual(first.post('/api/tutor/source-position', json=body).status_code, 200)
            self.assertEqual(first.get('/api/tutor/source-position', params=query).json()['position']['mode'], 'page')
            self.assertEqual(second.get('/api/tutor/source-position', params=query).status_code, 403)
            self.assertEqual(second.post('/api/tutor/source-position', json=body).status_code, 403)
