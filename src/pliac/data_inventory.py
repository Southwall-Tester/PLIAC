"""Read-only learner storage inventory; not a deletion command or completeness guarantee."""
import hashlib
import sqlite3
from contextlib import closing
from pathlib import Path

from learning_agent.course_graph import safe_id
from .runtime_backup import checked_path

# Tables shared by the existing identity, task, reading and media stores.
TABLES = {'identities', 'sessions', 'jobs', 'recoveries', 'positions', 'source_positions',
          'resource_positions', 'document_resource_positions', 'review_access'}


def learner_inventory(course_root, student):
    safe_id(student, '学习编号')
    root = checked_path(course_root)
    if not root.is_dir():
        raise ValueError('Course runtime directory does not exist.')
    name = student + '-' + hashlib.sha256(student.encode('ascii')).hexdigest()[:16]
    histories, databases, unknown = [], [], []
    # Reject redirects before enumerating their contents; do not follow junctions.
    pending = [root]
    paths = []
    while pending:
        parent = pending.pop()
        for path in parent.iterdir():
            checked_path(path)
            paths.append(path)
            if path.is_dir():
                pending.append(path)
    for directory in paths:
        if directory.name == name and directory.parent.name == 'learners' and directory.is_dir():
            owned = [path for path in paths if path.is_relative_to(directory) and path.is_file()]
            histories.append({'directory': directory.relative_to(root).as_posix(),
                              'files': len(owned), 'bytes': sum(path.stat().st_size for path in owned),
                              'revisions': sum(path.is_dir() and path.parent == directory / 'revisions' for path in paths)})
    for path in paths:
        if not path.is_file() or path.suffix != '.sqlite3':
            continue
        rows = {}
        with closing(sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True, timeout=5)) as db:
            db.execute('PRAGMA query_only=ON')
            db.execute('BEGIN')
            tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            for table in sorted(tables):
                if table.startswith('sqlite_'):
                    continue
                if table == 'attempts':
                    continue  # Peer-based rate limits have no asserted student ownership.
                if table == 'clips' and path.name == 'camera.sqlite3' and 'sessions' in tables:
                    count, size = db.execute('SELECT COUNT(*), COALESCE(SUM(length(content)),0) FROM clips '
                                            'WHERE session_id IN (SELECT id FROM sessions WHERE student=?)', (student,)).fetchone()
                    rows['clips'] = count
                    rows['clip_bytes'] = size
                elif table in TABLES:
                    columns = {row[1] for row in db.execute(f'PRAGMA table_info("{table}")')}
                    if 'student' not in columns:
                        unknown.append({'database': path.relative_to(root).as_posix(), 'table': table})
                        continue
                    predicate = 'student=? OR actor=?' if 'actor' in columns else 'student=?'
                    args = (student, student) if 'actor' in columns else (student,)
                    rows[table] = db.execute(f'SELECT COUNT(*) FROM "{table}" WHERE {predicate}', args).fetchone()[0]
                else:
                    unknown.append({'database': path.relative_to(root).as_posix(), 'table': table})
            db.rollback()
        if any(rows.values()):
            databases.append({'database': path.relative_to(root).as_posix(), 'counts': rows})
    return {'student': student, 'histories': histories, 'databases': databases, 'unknown_tables': unknown,
            'deletion_performed': False,
            'limitations': ['Counts are per-store observations, not an atomic cross-store snapshot.',
                            'External backups, browser caches, downloads, provider logs and unrecognized files are not inventoried.',
                            'Shared peer rate-limit rows are not attributed to this student.',
                            'This report does not authorize deletion or prove privacy erasure.']}
