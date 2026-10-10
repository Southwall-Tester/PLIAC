"""Durable knowledge activation with synthetic audits and no paid calls."""
import asyncio
import os
import unittest
from unittest.mock import patch

import httpx
import test_knowledge_activation
from pliac.main import app
from learning_agent.course_graph import CourseGraphError


class ActivationJobTests(unittest.IsolatedAsyncioTestCase):
    setUp = test_knowledge_activation.ActivationTests.setUp

    async def test_protected_status_and_activation_require_admin(self):
        secret = 'synthetic-activation-admin-' + 'x' * 32
        with patch('learning_agent.api.store', self.store), patch.dict(os.environ, {'PLIAC_REQUIRE_AUTH': '1', 'PLIAC_ADMIN_SECRET': secret}):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='https://test') as client:
                self.assertEqual((await client.get('/api/tutor/activation-status')).status_code, 401)
                self.assertEqual((await client.post('/api/access/anonymous', json={})).status_code, 200)
                self.assertEqual((await client.get('/api/tutor/activation-status')).status_code, 403)
                self.assertEqual((await client.post('/api/tutor/activate', json={'expected_version': 1})).status_code, 403)
                self.assertEqual((await client.post('/api/access/admin', json={'secret': secret})).status_code, 200)
                self.assertEqual((await client.get('/api/tutor/activation-status')).status_code, 200)

    async def test_concurrent_requests_share_generation_and_retry_uses_cache(self):
        entered, release = asyncio.Event(), asyncio.Event()
        calls = 0
        async def generate(*args):
            nonlocal calls
            calls += 1
            entered.set()
            await release.wait()
            return self.audit, {'model': 'synthetic'}
        with patch('learning_agent.api.store', self.store), patch('pliac.tutor_api.configured_api', return_value=None), patch('pliac.knowledge_activation.audit_knowledge', side_effect=generate):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
                initial = await client.get('/api/tutor/activation-status')
                self.assertEqual(initial.json()['status'], 'not_started')
                first = asyncio.create_task(client.post('/api/tutor/activate', json={'expected_version': 1}))
                try:
                    await asyncio.wait_for(entered.wait(), 5)
                    duplicate = await client.post('/api/tutor/activate', json={'expected_version': 1})
                    self.assertEqual(duplicate.status_code, 409, duplicate.text)
                    running = await client.get('/api/tutor/activation-status')
                    self.assertEqual(running.json()['status'], 'running')
                    self.assertEqual(running.json()['job_id'], initial.json()['job_id'])
                finally:
                    release.set()
                self.assertEqual((await first).status_code, 200)
                again = await client.post('/api/tutor/activate', json={'expected_version': 1})
                self.assertEqual(again.status_code, 200, again.text)
                self.assertEqual(calls, 1)
                status = await client.get('/api/tutor/activation-status')
                self.assertEqual(status.json()['status'], 'generated')
                self.assertEqual(status.json()['attempts'], 1)

    async def test_publish_failure_reuses_audit_but_source_change_blocks(self):
        async def generate(*args):
            return self.audit, {'model': 'synthetic'}
        with patch('learning_agent.api.store', self.store), patch('pliac.tutor_api.configured_api', return_value=None), patch('pliac.knowledge_activation.audit_knowledge', side_effect=generate) as provider:
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
                with patch('pliac.knowledge_activation.activate_snapshot', side_effect=CourseGraphError('Synthetic write failure', 503)):
                    self.assertEqual((await client.post('/api/tutor/activate', json={'expected_version': 1})).status_code, 503)
                self.assertIsNone(self.store.load_graph())
                self.assertEqual((await client.post('/api/tutor/activate', json={'expected_version': 1})).status_code, 200)
                self.assertEqual(provider.call_count, 1)

    async def test_source_changes_during_audit_cannot_publish(self):
        async def generate(*args):
            return self.audit, {'model': 'synthetic'}
        changed = self.context | {'sources': [{'id': 'book', 'text': 'Changed actual text'}]}
        with patch('learning_agent.api.store', self.store), patch('pliac.tutor_api.configured_api', return_value=None), patch('pliac.knowledge_activation.audit_knowledge', side_effect=generate), patch('pliac.knowledge_activation.activation_context', side_effect=[self.context, changed]):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
                result = await client.post('/api/tutor/activate', json={'expected_version': 1})
                self.assertEqual(result.status_code, 409, result.text)
                self.assertIsNone(self.store.load_graph())
