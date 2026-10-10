import json
import sqlite3
import shutil
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from pliac.runtime_backup import backup, restore


class BackupTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.data = self.root / 'runtime'
        (self.data / 'course_graph').mkdir(parents=True)
        (self.data / 'documents').mkdir()
        (self.data / 'course_graph/draft.json').write_text('{"synthetic":true}', encoding='utf-8')
        (self.data / 'documents/source.txt').write_text('Synthetic course source', encoding='utf-8')
        (self.data / 'models.json').write_text('SYNTHETIC_SECRET', encoding='utf-8')
        db = sqlite3.connect(self.data / 'course_graph/identities.sqlite3')
        db.execute('CREATE TABLE example(value TEXT)')
        db.execute("INSERT INTO example VALUES ('synthetic')")
        db.commit(); db.close()
        self.snapshot = self.root / 'snapshot'

    def test_offline_copy_and_new_directory_restore(self):
        result = backup(self.data, self.snapshot, offline_confirmed=True)
        self.assertEqual(result['files'], 3)
        self.assertFalse((self.snapshot / 'models.json').exists())
        target = self.root / 'restored'
        restore(self.snapshot, target)
        self.assertEqual((target / 'documents/source.txt').read_text(), 'Synthetic course source')
        with closing(sqlite3.connect(target / 'course_graph/identities.sqlite3')) as db:
            self.assertEqual(db.execute('PRAGMA integrity_check').fetchone()[0], 'ok')
            self.assertEqual(db.execute('SELECT value FROM example').fetchone()[0], 'synthetic')
        with self.assertRaises(ValueError):
            restore(self.snapshot, target)

    def test_confirmation_lock_overlap_and_tamper_are_rejected(self):
        with self.assertRaises(ValueError):
            backup(self.data, self.snapshot)
        with self.assertRaises(ValueError):
            backup(self.data, self.data / 'snapshot', offline_confirmed=True)
        lock = self.data / 'course_graph/.write.lock'
        lock.touch()
        with self.assertRaises(ValueError):
            backup(self.data, self.snapshot, offline_confirmed=True)
        lock.unlink()
        backup(self.data, self.snapshot, offline_confirmed=True)
        (self.snapshot / 'documents/source.txt').write_text('changed')
        target = self.root / 'rejected'
        with self.assertRaises(ValueError):
            restore(self.snapshot, target)
        self.assertFalse(target.exists())

    def test_manifest_cannot_restore_unlisted_paths(self):
        backup(self.data, self.snapshot, offline_confirmed=True)
        path = self.snapshot / 'manifest.json'
        manifest = json.loads(path.read_text())
        manifest['files']['../outside.txt'] = 'fake'
        path.write_text(json.dumps(manifest))
        with self.assertRaises(ValueError):
            restore(self.snapshot, self.root / 'rejected')
        self.assertFalse((self.root / 'outside.txt').exists())

    def test_restored_course_and_learner_are_readable_by_application(self):
        from learning_agent.course_graph import CourseGraphStore
        from test_learning_workspace import platform_fixture, publish_synthetic

        seed = self.root / 'seed.json'
        seed.write_text(json.dumps(platform_fixture()), encoding='utf-8')
        runtime = self.root / 'application'
        store = CourseGraphStore(seed, runtime / 'course_graph')
        publish_synthetic(store)
        store.save_profile({'student_id': 'synthetic', 'expected_version': 0,
                            'goals': 'Understand validation', 'background': 'Synthetic learner'})
        expected_graph = store.load_graph()
        expected_learner = store.load_learner('synthetic')
        backup(runtime, self.snapshot, offline_confirmed=True)
        target = self.root / 'application-restored'
        restore(self.snapshot, target)
        restored = CourseGraphStore(seed, target / 'course_graph')
        self.assertEqual(restored.load_graph(), expected_graph)
        self.assertEqual(restored.load_learner('synthetic'), expected_learner)
        restored.save_profile({'student_id': 'synthetic',
                               'expected_version': expected_learner['version'],
                               'goals': 'Continue after restore'})
        self.assertEqual(restored.load_learner('synthetic')['profile']['goals'], 'Continue after restore')
        self.assertEqual(store.load_learner('synthetic'), expected_learner)

    def test_redirected_store_is_rejected(self):
        runtime = self.root / 'redirected'
        runtime.mkdir()
        try:
            (runtime / 'documents').symlink_to(self.data / 'documents', target_is_directory=True)
        except OSError:
            self.skipTest('Creating symlinks is not allowed in this environment.')
        with self.assertRaises(ValueError):
            backup(runtime, self.snapshot, offline_confirmed=True)
        self.assertFalse(self.snapshot.exists())

    def test_existing_backup_is_not_overwritten(self):
        self.snapshot.mkdir()
        marker = self.snapshot / 'keep.txt'
        marker.write_text('preserve')
        with self.assertRaises(FileExistsError):
            backup(self.data, self.snapshot, offline_confirmed=True)
        self.assertEqual(marker.read_text(), 'preserve')

    def test_source_change_does_not_produce_completed_manifest(self):
        copy = shutil.copyfile

        def changing_copy(source, destination):
            result = copy(source, destination)
            Path(source).write_bytes(b'changed during backup')
            return result

        with patch('pliac.runtime_backup.shutil.copyfile', side_effect=changing_copy):
            with self.assertRaises(ValueError):
                backup(self.data, self.snapshot, offline_confirmed=True)
        self.assertFalse((self.snapshot / 'manifest.json').exists())
