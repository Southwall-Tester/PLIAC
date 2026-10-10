import hashlib
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from learning_agent.course_graph import CourseGraphStore, CourseGraphError
from pliac.data_inventory import learner_inventory


class InventoryTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name).resolve() / 'course_graph'
        self.root.mkdir()

    def fingerprints(self):
        return {str(path.relative_to(self.root)): hashlib.sha256(path.read_bytes()).hexdigest()
                for path in self.root.rglob('*') if path.is_file()}

    def test_history_database_and_media_counts_are_scoped_and_read_only(self):
        for location in (self.root, self.root / 'acceptance_demo/v1'):
            store = CourseGraphStore(output_dir=location)
            for student in ('student-a', 'student-b'):
                learner = store._empty(student)
                learner['profile']['goals'] = 'PRIVATE_CONTENT_NOT_IN_REPORT'
                store._commit(learner)
                store._commit(learner)
        with closing(sqlite3.connect(self.root / 'camera.sqlite3')) as db:
            db.executescript('CREATE TABLE sessions(id TEXT,student TEXT); CREATE TABLE clips(session_id TEXT,content BLOB);'
                             'CREATE TABLE review_access(actor TEXT,student TEXT); CREATE TABLE future_schema(private TEXT);')
            db.executemany('INSERT INTO sessions VALUES (?,?)', [('a', 'student-a'), ('b', 'student-b')])
            db.executemany('INSERT INTO clips VALUES (?,?)', [('a', b'12345'), ('b', b'OTHER_PRIVATE_VIDEO')])
            db.execute('INSERT INTO review_access VALUES (?,?)', ('student-a', 'student-b'))
            db.commit()
        before = self.fingerprints()
        result = learner_inventory(self.root, 'student-a')
        self.assertEqual(len(result['histories']), 2)
        self.assertTrue(all(item['revisions'] == 2 for item in result['histories']))
        counts = result['databases'][0]['counts']
        self.assertEqual(counts['sessions'], 1)
        self.assertEqual(counts['clips'], 1)
        self.assertEqual(counts['clip_bytes'], 5)
        self.assertEqual(counts['review_access'], 1)
        self.assertEqual(result['unknown_tables'], [{'database': 'camera.sqlite3', 'table': 'future_schema'}])
        self.assertFalse(result['deletion_performed'])
        self.assertNotIn('PRIVATE_CONTENT_NOT_IN_REPORT', str(result))
        self.assertNotIn('OTHER_PRIVATE_VIDEO', str(result))
        self.assertEqual(self.fingerprints(), before)

    def test_absent_learner_does_not_create_records_and_invalid_id_rejected(self):
        before = self.fingerprints()
        result = learner_inventory(self.root, 'absent')
        self.assertEqual(result['histories'], [])
        self.assertEqual(result['databases'], [])
        self.assertEqual(before, self.fingerprints())
        with self.assertRaises(CourseGraphError):
            learner_inventory(self.root, '../outside')
