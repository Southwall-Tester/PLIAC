"""Process-local PDF admission does not queue unbounded browser work."""
import asyncio
import threading
import unittest
from unittest.mock import AsyncMock, patch

from learning_agent.course_graph import CourseGraphError
from pliac.personal_export import render_pdf


class ExportCapacityTests(unittest.IsolatedAsyncioTestCase):
    async def test_limit_releases_after_cancellation_and_error(self):
        started = asyncio.Event()
        release = asyncio.Event()
        calls = 0

        async def renderer(kind, record):
            nonlocal calls
            calls += 1
            if calls == 2:
                started.set()
            await release.wait()
            if record.get('fail'):
                raise CourseGraphError('Synthetic rendering failure', 422)
            return b'%PDF-synthetic'

        with (patch('pliac.personal_export._PDF_SLOTS', threading.BoundedSemaphore(2)),
              patch('pliac.personal_export._render_pdf', side_effect=renderer)):
            first = asyncio.create_task(render_pdf('material', {}))
            second = asyncio.create_task(render_pdf('report', {}))
            try:
                await asyncio.wait_for(started.wait(), 3)
                with self.assertRaises(CourseGraphError) as caught:
                    await render_pdf('textbook', {})
                self.assertEqual(caught.exception.status_code, 429)
                self.assertEqual(calls, 2, 'Rejected request must not reach browser rendering')
                first.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await first
                release.set()
                self.assertEqual(await second, b'%PDF-synthetic')
                with self.assertRaises(CourseGraphError):
                    await render_pdf('material', {'fail': True})
                self.assertEqual(await render_pdf('material', {}), b'%PDF-synthetic')
            finally:
                release.set()
                for task in (first, second):
                    if not task.done():
                        task.cancel()
                await asyncio.gather(first, second, return_exceptions=True)

    async def test_invalid_content_also_returns_slot(self):
        slots = threading.BoundedSemaphore(1)
        with patch('pliac.personal_export._PDF_SLOTS', slots):
            with patch('pliac.personal_export._render_pdf', AsyncMock(side_effect=ValueError('synthetic'))):
                with self.assertRaises(ValueError):
                    await render_pdf('material', {})
            self.assertTrue(slots.acquire(blocking=False))
            slots.release()
