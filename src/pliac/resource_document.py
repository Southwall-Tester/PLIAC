"""Read an explicitly published course PDF without requiring a generated citation."""
import hashlib
import json
import re
import time
from contextlib import closing, contextmanager

import fitz

from learning_agent.course_graph import CourseGraphError, safe_id
from .reading_position import ReadingPositions


class ResourceDocument:
    def __init__(self, store, documents):
        self.store, self.documents = store, documents
        self.reading = ReadingPositions(store)

    @contextmanager
    def document(self, student, resource):
        safe_id(student, '学习编号'); safe_id(resource, '资源编号')
        graph = self.store._require_graph()
        item = next((item for item in graph['resources'] if item['id'] == resource
                     and item.get('review_status') in ('reviewed', 'auto_validated')), None)
        match = re.fullmatch(r'/api/documents/([A-Za-z0-9_-]+)/source(?:#page=([1-9]\d*))?', item.get('url', '')) if item else None
        if not match:
            raise CourseGraphError('当前课程没有该可阅读的本地资料。', 404)
        path = self.documents.source(match[1])
        if path.suffix.lower() != '.pdf':
            raise CourseGraphError('此阅读器支持 PDF 和 PDF 版课件；其他文件请使用原文件入口。', 415)
        if not path.is_file():
            raise CourseGraphError('原文件不存在。', 404)
        with path.open('rb') as stream:
            digest = hashlib.file_digest(stream, 'sha256').hexdigest()
        signature = hashlib.sha256(json.dumps([graph['version'], item, digest], sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        try:
            with fitz.open(path) as pdf:
                if pdf.needs_pass or len(pdf) < 1:
                    raise CourseGraphError('原文件需要密码或没有可阅读页面。', 409)
                yield pdf, {'title': item['title'], 'page_count': len(pdf), 'signature': signature,
                            'initial_page': min(int(match[2] or 1), len(pdf))}
        except CourseGraphError:
            raise
        except (RuntimeError, ValueError) as exc:
            raise CourseGraphError('PDF 原文件无法读取，请检查文件或使用原文件入口。', 409) from exc

    def connection(self):
        db = self.reading.connection()
        db.execute('BEGIN IMMEDIATE')
        db.execute('''CREATE TABLE IF NOT EXISTS document_resource_positions (
            student TEXT, resource TEXT, signature TEXT, page INTEGER, mode TEXT, zoom INTEGER,
            revision INTEGER, request TEXT, PRIMARY KEY(student,resource))''')
        if 'updated_at' not in {row[1] for row in db.execute('PRAGMA table_info(document_resource_positions)')}:
            db.execute('ALTER TABLE document_resource_positions ADD COLUMN updated_at REAL NOT NULL DEFAULT 0')
        db.commit()
        return db

    def read(self, student, resource):
        with self.document(student, resource) as (_, meta), closing(self.connection()) as db:
            row = db.execute('SELECT * FROM document_resource_positions WHERE student=? AND resource=?', (student, resource)).fetchone()
            valid = row is not None and row['signature'] == meta['signature']
            return {**meta, 'revision': row['revision'] if row else 0,
                    'changed': row is not None and not valid,
                    'position': {key: row[key] for key in ('page', 'mode', 'zoom')} if valid else None}

    @staticmethod
    def check_page(meta, page, signature):
        if signature != meta['signature']:
            raise CourseGraphError('课程资源或原文件已更新，请重新打开资料；旧位置不会套用。', 409)
        if type(page) is not int or not 1 <= page <= meta['page_count']:
            raise CourseGraphError('页码超出当前文件范围。', 400)

    def page(self, student, resource, number, signature, mode):
        if mode not in ('text', 'page'):
            raise CourseGraphError('阅读模式无效。', 400)
        with self.document(student, resource) as (pdf, meta):
            self.check_page(meta, number, signature)
            page = pdf[number - 1]
            if mode == 'text':
                text = page.get_text()
                if len(text) > 200_000:
                    raise CourseGraphError('本页文字超过显示限制，请使用原版式模式。', 413)
                return {'page': number, 'text': text,
                        'notice': '文字来自当前 PDF 页面，未执行 OCR；扫描页没有文字时请查看原版式。'}
            longest = max(page.rect.width, page.rect.height)
            if longest <= 0:
                raise CourseGraphError('原文件页尺寸无效。', 409)
            return page.get_pixmap(matrix=fitz.Matrix(min(2, 2200 / longest), min(2, 2200 / longest)), alpha=False).tobytes('png')

    def save(self, body):
        student, resource = body.get('student_id'), body.get('resource_id')
        page, mode, zoom = body.get('page'), body.get('mode'), body.get('zoom')
        request = safe_id(body.get('request_id'), '请求编号')
        expected = body.get('expected_revision')
        if mode not in ('text', 'page') or type(zoom) is not int or zoom not in (100, 150, 200):
            raise CourseGraphError('阅读模式或放大比例无效。', 400)
        if type(expected) is not int or expected < 0:
            raise CourseGraphError('阅读版本无效。', 400)
        with self.document(student, resource) as (_, meta), closing(self.connection()) as db:
            self.check_page(meta, page, body.get('signature'))
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT * FROM document_resource_positions WHERE student=? AND resource=?', (student, resource)).fetchone()
            if row and row['request'] == request:
                if (row['signature'], row['page'], row['mode'], row['zoom']) != (meta['signature'], page, mode, zoom):
                    raise CourseGraphError('同一请求不能保存不同阅读位置。', 409)
            else:
                revision = row['revision'] if row else 0
                if expected != revision:
                    raise CourseGraphError('其他页面已保存位置，请重新读取后再保存。', 409)
                db.execute('INSERT OR REPLACE INTO document_resource_positions VALUES (?,?,?,?,?,?,?,?,?)',
                           (student, resource, meta['signature'], page, mode, zoom, revision + 1, request, time.time()))
            db.commit()
        return self.read(student, resource)
