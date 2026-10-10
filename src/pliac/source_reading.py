"""Explicit source bookmarks, independent of learning evidence and progress."""
import hashlib
import json
from contextlib import closing

from learning_agent.course_graph import CourseGraphError, safe_id
from .reading_position import ReadingPositions
from .source_preview import source_reference


class SourceReading:
    def __init__(self, store, documents):
        self.store, self.documents = store, documents
        self.reading = ReadingPositions(store)

    def connection(self):
        db = self.reading.connection()
        db.execute('''CREATE TABLE IF NOT EXISTS source_positions (
            student TEXT, material TEXT, document TEXT, source TEXT, signature TEXT,
            mode TEXT, zoom INTEGER, revision INTEGER, request TEXT,
            PRIMARY KEY(student,material,document))''')
        db.commit()
        return db

    def signature(self, source):
        path = self.documents.source(source['document_id'])
        if not path.is_file():
            raise CourseGraphError('原文件不存在，不能保存或恢复阅读位置。', 404)
        with path.open('rb') as stream:
            digest = hashlib.file_digest(stream, 'sha256').hexdigest()
        return hashlib.sha256(json.dumps([source, digest], sort_keys=True, ensure_ascii=False).encode()).hexdigest()

    def read(self, student, material, source_id):
        source = source_reference(self.store, student, material, source_id)
        with closing(self.connection()) as db:
            row = db.execute('SELECT * FROM source_positions WHERE student=? AND material=? AND document=?',
                             (student, material, source['document_id'])).fetchone()
        if not row:
            return {'revision': 0, 'position': None}
        try:
            saved = source_reference(self.store, student, material, row['source'])
            valid = saved['document_id'] == source['document_id'] and self.signature(saved) == row['signature']
        except CourseGraphError:
            valid = False
        return {'revision': row['revision'], 'changed': not valid,
                'position': {'source_id': row['source'], 'mode': row['mode'], 'zoom': row['zoom'], 'page': saved['page']} if valid else None}

    def save(self, body):
        student, material, source_id = body.get('student_id'), body.get('material_id'), body.get('source_id')
        source = source_reference(self.store, student, material, source_id)
        mode, zoom, expected = body.get('mode'), body.get('zoom'), body.get('expected_revision')
        request = safe_id(body.get('request_id'), '请求编号')
        if mode not in ('text', 'page') or type(zoom) is not int or zoom not in (100, 150, 200):
            raise CourseGraphError('阅读模式或放大比例无效。', 400)
        if type(expected) is not int or expected < 0:
            raise CourseGraphError('阅读版本无效。', 400)
        signature = self.signature(source)
        with closing(self.connection()) as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT * FROM source_positions WHERE student=? AND material=? AND document=?',
                             (student, material, source['document_id'])).fetchone()
            if row and row['request'] == request:
                if (row['source'], row['signature'], row['mode'], row['zoom']) != (source_id, signature, mode, zoom):
                    raise CourseGraphError('同一请求不能保存不同原文位置。', 409)
            else:
                revision = row['revision'] if row else 0
                if expected != revision:
                    raise CourseGraphError('其他页面已保存原文位置，请重新读取后再保存。', 409)
                db.execute('INSERT OR REPLACE INTO source_positions VALUES (?,?,?,?,?,?,?,?,?)',
                           (student, material, source['document_id'], source_id, signature, mode, zoom, revision + 1, request))
            db.commit()
        return self.read(student, material, source_id)
