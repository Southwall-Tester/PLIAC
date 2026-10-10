import os
import unittest
import uuid
import test_access
from pliac.teaching_jobs import TeachingJobs
from learning_agent.course_graph import CourseGraphError


class RecoveryTests(unittest.TestCase):
    setUp = test_access.AccessTests.setUp
    client = test_access.AccessTests.client
    register = test_access.AccessTests.register

    def exhaust(self, student='synthetic', request='job'):
        jobs = TeachingJobs(self.store)
        for _ in range(3):
            owner, _ = jobs.claim(student, request, 'fingerprint')
            jobs.update(student, request, owner, 'failed')
        return jobs, owner

    def payload(self, **values):
        return {'student_id': 'synthetic', 'job_id': 'job', 'request_id': uuid.uuid4().hex,
                'reason': 'Synthetic provider check complete', 'expected_attempts': 3, 'expected_limit': 3} | values

    def test_recovery_preserves_attempts_and_fences_old_owner(self):
        jobs, owner = self.exhaust()
        body = self.payload()
        recovered = jobs.recover('admin', body)
        self.assertEqual(recovered['attempts'], 3)
        self.assertEqual(recovered['retry_limit'], 6)
        self.assertEqual(jobs.recover('admin', body), recovered)
        with self.assertRaises(CourseGraphError):
            jobs.update('synthetic', 'job', owner, 'generated', {})
        with self.assertRaises(CourseGraphError):
            jobs.recover('admin', body | {'reason': 'different'})
        with self.assertRaises(CourseGraphError):
            jobs.claim('synthetic', 'job', 'changed-context')
        jobs.claim('synthetic', 'job', 'fingerprint')
        self.assertEqual(jobs.status('synthetic', 'job')['attempts'], 4)
        with jobs.connection() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM recoveries').fetchone()[0], 1)

    def test_running_generated_and_cumulative_limit_block_recovery(self):
        jobs = TeachingJobs(self.store)
        owner, _ = jobs.claim('synthetic', 'job', 'fingerprint')
        with self.assertRaises(CourseGraphError):
            jobs.recover('admin', self.payload(expected_attempts=1))
        jobs.update('synthetic', 'job', owner, 'generated', {'saved': True})
        with self.assertRaises(CourseGraphError):
            jobs.recover('admin', self.payload(expected_attempts=1))
        jobs, _ = self.exhaust(request='exhausted')
        for limit in (3, 6, 9):
            jobs.recover('admin', self.payload(job_id='exhausted', expected_attempts=limit, expected_limit=limit))
            for _ in range(3):
                owner, _ = jobs.claim('synthetic', 'exhausted', 'fingerprint')
                jobs.update('synthetic', 'exhausted', owner, 'failed')
        with self.assertRaises(CourseGraphError):
            jobs.recover('admin', self.payload(job_id='exhausted', expected_attempts=12, expected_limit=12))

    def test_protected_admin_only(self):
        student_client, admin = self.client(), self.client()
        student = self.register(student_client)['identity']['student']
        self.exhaust(student)
        payload = self.payload(student_id=student)
        self.assertEqual(student_client.post('/api/tutor/job-recovery', json=payload).status_code, 403)
        self.assertEqual(admin.post('/api/tutor/job-recovery', json=payload).status_code, 401)
        admin.post('/api/access/admin', json={'secret': os.environ['PLIAC_ADMIN_SECRET']})
        result = admin.post('/api/tutor/job-recovery', json=payload)
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(result.json()['retry_remaining'], 3)
