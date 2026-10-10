import hashlib
import unittest
from unittest.mock import Mock, patch
import test_access

from pliac.source_preview import source_preview
from pliac.source_preview import source_page_image
from learning_agent.course_graph import CourseGraphError


class SourcePreviewTests(unittest.TestCase):
    setUp = test_access.AccessTests.setUp
    client = test_access.AccessTests.client
    register = test_access.AccessTests.register

    def prepare(self, student='synthetic'):
        text = '合成原文 <script>不是可执行内容</script>'
        ident = 'a' * 32
        self.source = {'id': 'document:test:2:0', 'origin': 'uploaded_document', 'document_id': ident,
                       'page': 2, 'title': '合成资料', 'content_digest': hashlib.sha256(text.encode()).hexdigest()}
        learner = self.store._read_learner(student)
        learner['workspace'] = {'tutor_turns': [{'request_id': 'saved', 'source_catalog': [self.source]}]}
        self.store._commit(learner)
        self.graph = {'nodes': [{'document_id': ident, 'document_evidence': [{'page': 2}]}]}
        self.documents = Mock()
        self.documents.page.return_value = {'text': text, 'private_internal_field': 'not returned'}

    def test_current_source_text_is_read_only_and_detects_revision(self):
        self.prepare(); before = self.store._read_learner('synthetic')
        with patch.object(self.store, 'load_graph', return_value=self.graph):
            value = source_preview(self.store, self.documents, 'synthetic', 'saved', self.source['id'])
            self.assertFalse(value['changed'])
            self.assertNotIn('private_internal_field', value)
            self.documents.page.return_value = {'text': 'changed original'}
            self.assertTrue(source_preview(self.store, self.documents, 'synthetic', 'saved', self.source['id'])['changed'])
        self.assertEqual(before, self.store._read_learner('synthetic'))

    def test_foreign_material_arbitrary_source_and_unlinked_page_rejected(self):
        self.prepare()
        with patch.object(self.store, 'load_graph', return_value=self.graph):
            for student, source in [('other', self.source['id']), ('synthetic', 'arbitrary-source')]:
                with self.assertRaises(CourseGraphError):
                    source_preview(self.store, self.documents, student, 'saved', source)
        with patch.object(self.store, 'load_graph', return_value={'nodes': []}), self.assertRaises(CourseGraphError):
            source_preview(self.store, self.documents, 'synthetic', 'saved', self.source['id'])
        self.documents.page.assert_not_called()

    def test_empty_page_not_replaced_with_generated_summary(self):
        self.prepare(); self.documents.page.return_value = {'text': ''}
        with patch.object(self.store, 'load_graph', return_value=self.graph), self.assertRaises(CourseGraphError):
            source_preview(self.store, self.documents, 'synthetic', 'saved', self.source['id'])

    def test_actual_protected_route_checks_owner(self):
        first, second = self.client(), self.client()
        student = self.register(first)['identity']['student']; self.register(second)
        self.prepare(student)
        query = {'student_id': student, 'material_id': 'saved', 'source_id': self.source['id']}
        with patch.object(self.store, 'load_graph', return_value=self.graph), patch('learning_agent.document_api.document_store', self.documents):
            result = first.get('/api/tutor/source-preview', params=query)
            self.assertEqual(result.status_code, 200, result.text)
            self.assertEqual(result.headers['cache-control'], 'no-store')
            self.assertEqual(second.get('/api/tutor/source-preview', params=query).status_code, 403)

    def test_pdf_image_uses_only_mapped_page_with_bounded_dimensions(self):
        import fitz
        self.prepare()
        path = self.store.output_dir / 'synthetic-source.pdf'
        with fitz.open() as pdf:
            pdf.new_page().insert_text((50, 60), 'UNRELATED PAGE')
            pdf.new_page(width=1800, height=2400).insert_text((50, 60), 'AUTHORIZED PAGE')
            pdf.save(path)
        self.documents.source.return_value = path
        with patch.object(self.store, 'load_graph', return_value=self.graph):
            content = source_page_image(self.store, self.documents, 'synthetic', 'saved', self.source['id'])
            image = fitz.Pixmap(content)
            self.assertEqual(max(image.width, image.height), 2200)
            self.assertTrue(content.startswith(b'\x89PNG'))
        with patch.object(self.store, 'load_graph', return_value={'nodes': []}), self.assertRaises(CourseGraphError):
            source_page_image(self.store, self.documents, 'synthetic', 'saved', self.source['id'])

    def test_protected_image_route_and_non_pdf_failure(self):
        import fitz
        first, second = self.client(), self.client()
        student = self.register(first)['identity']['student']; self.register(second)
        self.prepare(student)
        path = self.store.output_dir / 'synthetic-source.pdf'
        with fitz.open() as pdf:
            pdf.new_page(); pdf.new_page().insert_text((50, 60), 'Synthetic source')
            pdf.save(path)
        self.documents.source.return_value = path
        query = {'student_id': student, 'material_id': 'saved', 'source_id': self.source['id']}
        with patch.object(self.store, 'load_graph', return_value=self.graph), patch('learning_agent.document_api.document_store', self.documents):
            result = first.get('/api/tutor/source-page-image', params=query)
            self.assertEqual(result.status_code, 200, result.text[:100] if result.status_code != 200 else '')
            self.assertEqual(result.headers['cache-control'], 'no-store')
            self.assertEqual(result.headers['content-type'], 'image/png')
            self.assertEqual(second.get('/api/tutor/source-page-image', params=query).status_code, 403)
            self.documents.source.return_value = path.with_suffix('.txt')
            self.assertEqual(first.get('/api/tutor/source-page-image', params=query).status_code, 415)
