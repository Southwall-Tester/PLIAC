import unittest
import uuid
from unittest.mock import patch

import fitz
import test_access
from learning_agent.course_graph import CourseGraphError
from learning_agent.documents import DocumentStore
from pliac.resource_document import ResourceDocument
from test_course_graph import fixture
from test_learning_workspace import publish_synthetic


def prepare_pdf(store, documents):
    ident = documents.create('synthetic-reader.pdf')['id']
    with fitz.open() as pdf:
        for number in range(1, 4):
            page = pdf.new_page(width=600, height=450)
            page.insert_text((40, 60), f'Synthetic source page {number}', fontsize=22)
            page.insert_text((40, 100), '<script>not executable</script>', fontsize=14)
        pdf.save(documents.source(ident))
    graph = fixture()
    graph['version'] = store.load_graph('draft')['version']
    graph['resources'][0].update(title='合成 PDF 课件', url=f'/api/documents/{ident}/source#page=2')
    published = publish_synthetic(store, graph)
    return ident, published


class ResourceDocumentTests(unittest.TestCase):
    setUp = test_access.AccessTests.setUp
    client = test_access.AccessTests.client
    register = test_access.AccessTests.register

    def prepare(self):
        self.documents = DocumentStore(self.store.output_dir / 'test-documents')
        self.addCleanup(self.documents.executor.shutdown, wait=True)
        self.ident, self.graph = prepare_pdf(self.store, self.documents)
        self.service = ResourceDocument(self.store, self.documents)

    def body(self, info, **fields):
        return {'student_id': 'synthetic', 'resource_id': 'r_a', 'signature': info['signature'],
                'expected_revision': info['revision'], 'request_id': uuid.uuid4().hex,
                'page': 3, 'mode': 'text', 'zoom': 150, **fields}

    def test_complete_document_without_generated_citation_and_position_is_not_evidence(self):
        self.prepare()
        before = self.store._read_learner('synthetic')
        info = self.service.read('synthetic', 'r_a')
        self.assertEqual((info['page_count'], info['initial_page']), (3, 2))
        for page in (1, 3):
            text = self.service.page('synthetic', 'r_a', page, info['signature'], 'text')
            self.assertIn(f'Synthetic source page {page}', text['text'])
        image = self.service.page('synthetic', 'r_a', 2, info['signature'], 'page')
        self.assertTrue(image.startswith(b'\x89PNG'))
        self.assertLessEqual(max(fitz.Pixmap(image).width, fitz.Pixmap(image).height), 2200)
        request = self.body(info)
        saved = self.service.save(request)
        self.assertEqual(self.service.save(request), saved)
        self.assertEqual(saved['position'], {'page': 3, 'mode': 'text', 'zoom': 150})
        self.assertEqual(self.service.read('other', 'r_a')['position'], None)
        self.assertEqual(self.store._read_learner('synthetic'), before)
        with self.assertRaises(CourseGraphError):
            self.service.save({**request, 'page': 1})
        with self.assertRaises(CourseGraphError):
            self.service.save(self.body(info, page=1))

    def test_file_change_invalidates_pages_and_bookmarks_and_bad_input_is_rejected(self):
        self.prepare()
        info = self.service.read('synthetic', 'r_a')
        self.service.save(self.body(info))
        for page in (0, 4, True):
            with self.assertRaises(CourseGraphError):
                self.service.save(self.body(info, page=page))
        for fields in ({'zoom': True}, {'zoom': 900}, {'expected_revision': True}, {'mode': 'script'}):
            with self.assertRaises(CourseGraphError):
                self.service.save(self.body(info, **fields))
        with fitz.open(self.documents.source(self.ident)) as pdf:
            pdf[0].insert_text((40, 150), 'Updated source')
            pdf.saveIncr()
        changed = self.service.read('synthetic', 'r_a')
        self.assertTrue(changed['changed'])
        self.assertIsNone(changed['position'])
        self.assertEqual(changed['revision'], 1)
        with self.assertRaises(CourseGraphError):
            self.service.page('synthetic', 'r_a', 1, info['signature'], 'page')
        with self.assertRaises(CourseGraphError):
            self.service.save(self.body(info, expected_revision=1))

    def test_recent_resources_merge_by_saved_time_and_skip_invalid_versions(self):
        import copy
        from pliac.resource_position import ResourcePositions
        from pliac.reading_position import recent_reading
        self.prepare()
        graph = self.store.load_graph('draft')
        video = copy.deepcopy(graph['resources'][0])
        video.update(id='synthetic-video', format='video', title='合成视频', url='https://example.test/video.webm')
        graph['resources'].append(video)
        publish_synthetic(self.store, graph)
        info = self.service.read('synthetic', 'r_a')
        with patch('pliac.resource_document.time.time', return_value=10):
            self.service.save(self.body(info))
        request = {'student_id': 'synthetic', 'resource_id': video['id'], 'request_id': 'saved-video', 'expected_revision': 0, 'seconds': 12}
        with patch('pliac.resource_position.time.time', return_value=20):
            ResourcePositions(self.store).save(request)
        with patch('pliac.resource_position.time.time', return_value=999):
            ResourcePositions(self.store).save(request)
        entries = recent_reading(self.store, 'synthetic', self.documents)['items']
        self.assertEqual([(item['kind'], item['updated_at']) for item in entries], [('video', 20), ('document', 10)])
        self.assertEqual(entries[1]['node_id'], 'a')
        self.assertEqual(recent_reading(self.store, 'other', self.documents)['items'], [])
        with fitz.open(self.documents.source(self.ident)) as pdf:
            pdf[0].insert_text((40, 180), 'Changed file')
            pdf.saveIncr()
        entries = recent_reading(self.store, 'synthetic', self.documents)['items']
        self.assertEqual([item['kind'] for item in entries], ['video'])
        graph = self.store.load_graph('draft'); graph['resources'] = []
        publish_synthetic(self.store, graph)
        self.assertEqual(recent_reading(self.store, 'synthetic', self.documents)['items'], [])

    def test_legacy_bookmark_schema_keeps_position_without_inventing_recent_time(self):
        import sqlite3
        from contextlib import closing
        from pliac.resource_continue import recent_resources
        self.prepare()
        info = self.service.read('synthetic', 'r_a')
        self.service.save(self.body(info))
        path = self.store.output_dir / 'reading.sqlite3'
        with closing(sqlite3.connect(path)) as db:
            db.execute('ALTER TABLE document_resource_positions DROP COLUMN updated_at')
            db.commit()
        entries = recent_resources(self.store, self.documents, 'synthetic')
        self.assertEqual(entries[0]['updated_at'], 0)
        restored = self.service.read('synthetic', 'r_a')
        self.assertEqual(restored['position']['page'], 3)
        self.assertEqual(restored['revision'], 1)
        self.assertEqual(recent_resources(self.store, self.documents, 'synthetic')[0]['updated_at'], 0)

    def test_only_explicit_published_local_pdf_resource_is_readable(self):
        self.prepare()
        for resource in ('unknown', '../source'):
            with self.assertRaises(CourseGraphError):
                self.service.read('synthetic', resource)
        for change in ({'review_status': 'draft'}, {'url': 'https://example.test/file.pdf'},
                       {'url': '/api/documents/../../source'}):
            graph = self.store.load_graph()
            graph['resources'][0].update(change)
            with patch.object(self.store, '_require_graph', return_value=graph), self.assertRaises(CourseGraphError):
                self.service.read('synthetic', 'r_a')
        with patch.object(self.documents, 'source', return_value=self.documents.source(self.ident).with_suffix('.txt')):
            with self.assertRaises(CourseGraphError) as caught:
                self.service.read('synthetic', 'r_a')
            self.assertEqual(caught.exception.status_code, 415)

    def test_protected_metadata_page_and_save_check_identity(self):
        self.prepare()
        first, second = self.client(), self.client()
        student = self.register(first)['identity']['student']; self.register(second)
        query = {'student_id': student, 'resource_id': 'r_a'}
        with patch('learning_agent.document_api.document_store', self.documents):
            result = first.get('/api/tutor/resource-document', params=query)
            self.assertEqual(result.status_code, 200, result.text)
            self.assertEqual(result.headers['cache-control'], 'no-store')
            info = result.json()
            page = {**query, 'page': 3, 'signature': info['signature']}
            image = first.get('/api/tutor/resource-document-page', params=page)
            self.assertEqual(image.status_code, 200, image.text[:100] if image.status_code != 200 else '')
            self.assertEqual(image.headers['content-type'], 'image/png')
            self.assertEqual(image.headers['cache-control'], 'no-store')
            request = self.body(info, student_id=student)
            self.assertEqual(first.post('/api/tutor/resource-document-position', json=request).status_code, 200)
            self.assertEqual(second.get('/api/tutor/resource-document', params=query).status_code, 403)
            self.assertEqual(second.get('/api/tutor/resource-document-page', params=page).status_code, 403)
            self.assertEqual(second.post('/api/tutor/resource-document-position', json=request).status_code, 403)
            self.assertEqual(first.get(f'/api/documents/{self.ident}/source').status_code, 200)


if __name__ == '__main__':
    unittest.main()
