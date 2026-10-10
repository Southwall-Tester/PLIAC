"""Video bookmarks preserve position, never learning completion."""
import hashlib
import json
import math
import time
from contextlib import closing
from learning_agent.course_graph import CourseGraphError, safe_id
from .reading_position import ReadingPositions


class ResourcePositions:
    def __init__(self, store):
        self.store = store
        self.reading = ReadingPositions(store)

    def signature(self, student, resource):
        safe_id(student, '学习编号'); safe_id(resource, '资源编号')
        graph = self.store._require_graph()
        item = next((item for item in graph['resources'] if item['id'] == resource and item.get('review_status') in ('reviewed', 'auto_validated')), None)
        if not item or item['format'] != 'video':
            raise CourseGraphError('当前课程没有该可用视频。', 404)
        return hashlib.sha256(json.dumps([graph['version'], item], sort_keys=True, ensure_ascii=False).encode()).hexdigest()

    def connection(self):
        db = self.reading.connection()
        db.execute('BEGIN IMMEDIATE')
        db.execute('''CREATE TABLE IF NOT EXISTS resource_positions (
            student TEXT, resource TEXT, signature TEXT, seconds REAL, revision INTEGER, request TEXT,
            PRIMARY KEY(student,resource))''')
        if 'updated_at' not in {row[1] for row in db.execute('PRAGMA table_info(resource_positions)')}:
            db.execute('ALTER TABLE resource_positions ADD COLUMN updated_at REAL NOT NULL DEFAULT 0')
        db.commit()
        return db

    def read(self, student, resource):
        signature = self.signature(student, resource)
        with closing(self.connection()) as db:
            row = db.execute('SELECT * FROM resource_positions WHERE student=? AND resource=?', (student, resource)).fetchone()
        if not row:
            return {'revision': 0, 'seconds': None}
        return {'revision': row['revision'], 'seconds': row['seconds'] if row['signature'] == signature else None, 'changed': row['signature'] != signature}

    def save(self, body):
        student, resource = body.get('student_id'), body.get('resource_id')
        signature = self.signature(student, resource)
        request = safe_id(body.get('request_id'), '请求编号')
        seconds, expected = body.get('seconds'), body.get('expected_revision')
        if type(seconds) not in (int, float) or not math.isfinite(seconds) or not 0 <= seconds <= 604800:
            raise CourseGraphError('播放位置无效。', 400)
        if type(expected) is not int or expected < 0:
            raise CourseGraphError('阅读版本无效。', 400)
        with closing(self.connection()) as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT * FROM resource_positions WHERE student=? AND resource=?', (student, resource)).fetchone()
            if row and row['request'] == request:
                if row['seconds'] != seconds or row['signature'] != signature:
                    raise CourseGraphError('同一请求不能改变播放位置。', 409)
            else:
                revision = row['revision'] if row else 0
                if revision != expected:
                    raise CourseGraphError('其他页面已更新播放位置，请重新读取。', 409)
                db.execute('INSERT OR REPLACE INTO resource_positions VALUES (?,?,?,?,?,?,?)', (student, resource, signature, seconds, revision + 1, request, time.time()))
            db.commit()
        return self.read(student, resource)
