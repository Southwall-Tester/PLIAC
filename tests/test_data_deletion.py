import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from learning_agent.course_graph import CourseGraphStore
from pliac.access import IdentityStore
from pliac.data_deletion import delete_learner
from pliac.data_inventory import learner_inventory


class DeletionTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name).resolve() / 'course_graph'
        self.store = CourseGraphStore(output_dir=self.root)
        for student in ('synthetic-a', 'synthetic-b'):
            learner = self.store._empty(student)
            learner['profile']['goals'] = 'Synthetic retained goal'
            self.store._commit(learner)
            self.store._commit(learner)
        with IdentityStore(self.root).connection() as db:
            for student in ('synthetic-a', 'synthetic-b'):
                db.execute('INSERT INTO identities VALUES (?,?)', (student, student + '-hash'))
                db.execute('INSERT INTO sessions VALUES (?,?,?,?)', (student + '-token', student, 'student', 1))
        with closing(sqlite3.connect(self.root / 'camera.sqlite3')) as db:
            db.executescript('CREATE TABLE sessions(id TEXT PRIMARY KEY, student TEXT);'
                             'CREATE TABLE clips(session_id TEXT REFERENCES sessions(id),content BLOB);'
                             'CREATE TABLE review_access(actor TEXT,student TEXT);')
            db.executemany('INSERT INTO sessions VALUES (?,?)', [('a', 'synthetic-a'), ('b', 'synthetic-b')])
            db.executemany('INSERT INTO clips VALUES (?,?)', [('a', b'aaa'), ('b', b'bbb')])
            db.commit()

    def remove(self, **kwargs):
        return delete_learner(self.root, 'synthetic-a', **({'offline_confirmed': True, 'confirm_student': 'synthetic-a'} | kwargs))

    def test_exact_learner_removed_other_records_preserved_and_retry_safe(self):
        other = self.store._read_learner('synthetic-b')
        before_other = learner_inventory(self.root, 'synthetic-b')
        result = self.remove()
        self.assertEqual(result['deleted_history_directories'], 1)
        self.assertEqual(result['affected_databases'], 2)
        self.assertEqual(self.store._read_learner('synthetic-b'), other)
        self.assertEqual(learner_inventory(self.root, 'synthetic-b'), before_other)
        remaining = learner_inventory(self.root, 'synthetic-a')
        self.assertEqual(remaining['histories'], [])
        self.assertEqual(remaining['databases'], [])
        self.assertEqual(self.remove()['affected_databases'], 0)

    def test_missing_confirmation_lock_and_unknown_schema_do_not_delete(self):
        before = learner_inventory(self.root, 'synthetic-a')
        for values in ({'offline_confirmed': False}, {'confirm_student': 'synthetic-b'}):
            with self.assertRaises(ValueError):
                self.remove(**values)
        lock = self.root / '.write.lock'
        lock.touch()
        with self.assertRaises(ValueError):
            self.remove()
        lock.unlink()
        self.assertEqual(learner_inventory(self.root, 'synthetic-a'), before)
        with closing(sqlite3.connect(self.root / 'camera.sqlite3')) as db:
            db.execute('CREATE TABLE unknown_data(student TEXT)')
            db.commit()
        with self.assertRaises(ValueError):
            self.remove()
        self.assertEqual(self.store._read_learner('synthetic-a')['version'], 2)

    def test_running_job_and_cross_student_audit_require_review(self):
        with closing(sqlite3.connect(self.root / 'teaching-jobs.sqlite3')) as db:
            db.execute('CREATE TABLE jobs(student TEXT,status TEXT)')
            db.execute('INSERT INTO jobs VALUES (?,?)', ('synthetic-a', 'running'))
            db.commit()
        with self.assertRaises(ValueError):
            self.remove()
        with closing(sqlite3.connect(self.root / 'teaching-jobs.sqlite3')) as db:
            db.execute("UPDATE jobs SET status='failed'")
            db.commit()
        with closing(sqlite3.connect(self.root / 'camera.sqlite3')) as db:
            db.execute('INSERT INTO review_access VALUES (?,?)', ('synthetic-a', 'synthetic-b'))
            db.commit()
        with self.assertRaises(ValueError):
            self.remove()
        self.assertEqual(self.store._read_learner('synthetic-a')['version'], 2)

    def test_partial_failure_is_explicit_and_can_be_resumed_offline(self):
        with patch('pliac.data_deletion.shutil.rmtree', side_effect=OSError('Synthetic filesystem failure')):
            with self.assertRaisesRegex(RuntimeError, 'may be partial'):
                self.remove()
        remaining = learner_inventory(self.root, 'synthetic-a')
        self.assertTrue(remaining['histories'])
        self.assertEqual(remaining['databases'], [])
        self.assertEqual(self.remove()['deleted_history_directories'], 1)
        self.assertEqual(self.store._read_learner('synthetic-b')['version'], 2)
