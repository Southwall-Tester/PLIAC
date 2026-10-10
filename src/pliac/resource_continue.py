"""Discover valid saved resource positions, without creating learning evidence."""
import sqlite3
from contextlib import closing

from learning_agent.course_graph import CourseGraphError, safe_id
from .resource_document import ResourceDocument
from .resource_position import ResourcePositions


def recent_resources(store, documents, student):
    safe_id(student, '学习编号')
    path = store.output_dir / 'reading.sqlite3'
    graph = store.load_graph()
    if not path.is_file() or not graph:
        return []
    resources = {item['id']: item for item in graph['resources']
                 if item.get('review_status') in ('reviewed', 'auto_validated') and item.get('node_ids')}
    result = []
    with closing(sqlite3.connect(path)) as db:
        db.row_factory = sqlite3.Row
        tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        for table, kind in (('resource_positions', 'video'), ('document_resource_positions', 'document')):
            if table not in tables or kind == 'document' and documents is None:
                continue
            columns = {row[1] for row in db.execute(f'PRAGMA table_info({table})')}
            stamp = 'updated_at' if 'updated_at' in columns else '0 AS updated_at'
            rows = db.execute(f'SELECT resource,signature,{stamp} FROM {table} WHERE student=? ORDER BY updated_at DESC,resource LIMIT 10', (student,)).fetchall()
            for row in rows:
                resource = resources.get(row['resource'])
                if not resource:
                    continue
                try:
                    if kind == 'video':
                        valid = ResourcePositions(store).signature(student, row['resource']) == row['signature']
                    else:
                        with ResourceDocument(store, documents).document(student, row['resource']) as (_, meta):
                            valid = meta['signature'] == row['signature']
                except CourseGraphError:
                    continue
                if valid:
                    result.append({'resource_id': row['resource'], 'node_id': resource['node_ids'][0], 'kind': kind,
                                   'title': resource['title'], 'updated_at': row['updated_at']})
    return result
