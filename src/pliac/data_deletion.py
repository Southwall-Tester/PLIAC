"""Explicit offline deletion of known learner stores. Never called by student routes."""
import hashlib
import shutil
import sqlite3
from contextlib import closing

from .data_inventory import learner_inventory, TABLES
from .runtime_backup import checked_path

DATABASES = {'identities.sqlite3', 'teaching-jobs.sqlite3', 'reading.sqlite3', 'camera.sqlite3'}


def delete_learner(course_root, student, *, offline_confirmed=False, confirm_student=''):
    if not offline_confirmed or confirm_student != student:
        raise ValueError('Deletion requires stopped writers and explicit confirmation of the exact learner ID.')
    root = checked_path(course_root)
    inventory = learner_inventory(root, student)
    if inventory['unknown_tables']:
        raise ValueError('Unrecognized tables require review before any deletion.')
    if any(root.rglob('.write.lock')):
        raise ValueError('A write lock exists; nothing deleted.')
    expected_name = student + '-' + hashlib.sha256(student.encode('ascii')).hexdigest()[:16]
    histories = []
    for entry in inventory['histories']:
        target = checked_path(root / entry['directory'])
        if target == root or not target.is_relative_to(root) or target.parent.name != 'learners' or target.name != expected_name:
            raise ValueError('Invalid learner history directory; nothing deleted.')
        histories.append(target)
    databases = []
    # Validate every affected database before making destructive changes.
    for entry in inventory['databases']:
        path = checked_path(root / entry['database'])
        if not path.is_relative_to(root) or path.name not in DATABASES:
            raise ValueError('Unrecognized database location; nothing deleted.')
        with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)) as db:
            tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if 'jobs' in tables and db.execute("SELECT 1 FROM jobs WHERE student=? AND status='running' LIMIT 1", (student,)).fetchone():
                raise ValueError('Resolve running learner jobs before deletion.')
            if path.name == 'identities.sqlite3' and db.execute("SELECT 1 FROM sessions WHERE student=? AND role='admin' LIMIT 1", (student,)).fetchone():
                raise ValueError('Administrative identities require a separate retention review.')
            for table in ('recoveries', 'review_access'):
                if table in tables and db.execute(f'SELECT 1 FROM "{table}" WHERE actor=? AND student!=? LIMIT 1', (student, student)).fetchone():
                    raise ValueError('Cross-learner operator audit records require a separate review.')
        databases.append(path)
    try:
        for path in databases:
            with closing(sqlite3.connect(path.as_uri() + '?mode=rw', uri=True)) as db:
                db.execute('PRAGMA foreign_keys=ON')
                db.execute('PRAGMA secure_delete=ON')
                with db:
                    db.execute('BEGIN IMMEDIATE')
                    tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                    if path.name == 'camera.sqlite3' and 'clips' in tables:
                        db.execute('DELETE FROM clips WHERE session_id IN (SELECT id FROM sessions WHERE student=?)', (student,))
                    # Sessions precede identities so their references are not left dangling.
                    for table in sorted(tables & TABLES, key=lambda name: name == 'identities'):
                        db.execute(f'DELETE FROM "{table}" WHERE student=?', (student,))
        for target in histories:
            # Recheck the resolved, exact descendant immediately before recursive removal.
            if checked_path(target) != target or not target.is_relative_to(root) or target.name != expected_name:
                raise ValueError('Learner directory changed during deletion.')
            shutil.rmtree(target)
        after = learner_inventory(root, student)
        if after['histories'] or after['databases'] or after['unknown_tables']:
            raise ValueError('Post-deletion inventory still contains data requiring review.')
    except Exception as exc:
        raise RuntimeError('Deletion may be partial. Keep services stopped and inspect the learner inventory before retrying.') from exc
    return {'student': student, 'deleted_history_directories': len(histories), 'affected_databases': len(databases),
            'known_runtime_records_remaining': False,
            'notice': 'Known local records removed. This does not erase backups, downloads, provider logs, browser caches or physical storage remnants.'}
