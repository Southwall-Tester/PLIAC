"""Explicit reading anchors, separate from assessment versions and evidence."""
import hashlib
import json
import math
import sqlite3
import time
from contextlib import closing

from learning_agent.course_graph import CourseGraphError, safe_id


class ReadingPositions:
    def __init__(self, course_store):
        self.course = course_store
        self.path = course_store.output_dir / 'reading.sqlite3'

    def material(self, student, ident):
        safe_id(student, '学习编号'); safe_id(ident, '材料编号')
        workspace = self.course._read_learner(student).get('workspace', {})
        material = next((item for item in workspace.get('tutor_turns', []) if item['request_id'] == ident), None)
        if not material:
            raise CourseGraphError('未找到本人的学习材料。', 404)
        signature = hashlib.sha256(json.dumps(material, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        return material, signature

    def connection(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(self.path, timeout=5)
        db.row_factory = sqlite3.Row
        db.execute('BEGIN IMMEDIATE')
        db.execute('''CREATE TABLE IF NOT EXISTS positions (
            student TEXT, material TEXT, signature TEXT NOT NULL, anchor TEXT NOT NULL,
            offset REAL NOT NULL, revision INTEGER NOT NULL, request_id TEXT NOT NULL,
            PRIMARY KEY(student,material))''')
        if 'updated_at' not in {column[1] for column in db.execute('PRAGMA table_info(positions)')}:
            db.execute('ALTER TABLE positions ADD COLUMN updated_at REAL NOT NULL DEFAULT 0')
        db.commit()
        return db

    def recent(self, student):
        safe_id(student, '学习编号')
        if not self.path.is_file():
            return []
        workspace = self.course._read_learner(student).get('workspace', {})
        materials = {item['request_id']: item for item in workspace.get('tutor_turns', [])}
        with closing(self.connection()) as db:
            rows = db.execute('SELECT * FROM positions WHERE student=? ORDER BY updated_at DESC,material LIMIT 10', (student,)).fetchall()
        result = []
        for row in rows:
            material = materials.get(row['material'])
            if material is None:
                continue
            signature = hashlib.sha256(json.dumps(material, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
            if signature != row['signature']:
                continue
            blocks = material.get('proposal', {}).get('blocks', [])
            result.append({'material_id': row['material'], 'updated_at': row['updated_at'],
                           'title': blocks[0].get('heading', '个人学习材料') if blocks else '个人学习材料'})
        return result

    def read(self, student, ident):
        _, signature = self.material(student, ident)
        with closing(self.connection()) as db:
            row = db.execute('SELECT * FROM positions WHERE student=? AND material=?', (student, ident)).fetchone()
            if not row:
                return {'revision': 0, 'position': None}
            return {'revision': row['revision'], 'position': {'anchor': row['anchor'], 'offset': row['offset']} if row['signature'] == signature else None,
                    'changed': row['signature'] != signature}

    def save(self, body):
        student, ident = body.get('student_id'), body.get('material_id')
        material, signature = self.material(student, ident)
        request_id = safe_id(body.get('request_id'), '请求编号')
        anchors = {'top'} | {f'paragraph-{index}' for index, _ in enumerate(material.get('proposal', {}).get('blocks', []))}
        anchor, offset, expected = body.get('anchor'), body.get('offset'), body.get('expected_revision')
        if not isinstance(anchor, str) or anchor not in anchors:
            raise CourseGraphError('阅读锚点不属于该材料。', 400)
        if isinstance(offset, bool) or not isinstance(offset, (int, float)) or not math.isfinite(offset) or not 0 <= offset <= 10000:
            raise CourseGraphError('阅读偏移无效。', 400)
        if type(expected) is not int or expected < 0:
            raise CourseGraphError('阅读版本无效。', 400)
        with closing(self.connection()) as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT * FROM positions WHERE student=? AND material=?', (student, ident)).fetchone()
            if row and row['request_id'] == request_id:
                if row['anchor'] != anchor or row['offset'] != offset or row['signature'] != signature:
                    raise CourseGraphError('同一请求不能改变阅读位置。', 409)
            else:
                revision = row['revision'] if row else 0
                if expected != revision:
                    raise CourseGraphError('其他页面已更新续读位置，请重新读取后再保存。', 409)
                db.execute('INSERT OR REPLACE INTO positions (student,material,signature,anchor,offset,revision,request_id,updated_at) VALUES (?,?,?,?,?,?,?,?)',
                           (student, ident, signature, anchor, offset, revision + 1, request_id, time.time()))
            db.commit()
        return self.read(student, ident)


def recent_reading(default_store, student, documents=None):
    from learning_agent.course_catalog import list_courses, resolve_course
    from learning_agent.acceptance_course import DEMO_ID
    safe_id(student, '学习编号')
    courses = list_courses(default_store)
    if not any(item['id'] == DEMO_ID for item in courses):
        courses.append({'id': DEMO_ID})
    items = []
    for course in courses:
        store = resolve_course(default_store, course['id'])
        positions = ReadingPositions(store).recent(student)
        from .resource_continue import recent_resources
        positions.extend(recent_resources(store, documents, student))
        from .ml_lab import recent_lab
        positions.extend(recent_lab(store, student))
        if positions:
            graph = store.load_graph()
            title = graph['title'] if graph else '历史课程'
            items.extend(item | {'course_id': course['id'], 'course_title': title} for item in positions)
    return {'items': sorted(items, key=lambda item: (-item['updated_at'], item['course_id'], item.get('material_id', item.get('resource_id', '')), item.get('kind', 'material')))[:5]}
