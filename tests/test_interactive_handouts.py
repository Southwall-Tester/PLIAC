"""Interactive delivery: bounded edits, isolated controls, and validated prefix recovery."""
import asyncio
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest

import httpx

from tests import test_margin_progress as fixtures
from learnmargin.models import APIConfig, GeneratedLessonSection
from learnmargin.provider import Provider
from learnmargin.section_review import SectionAudit, apply_audit
from learnmargin.storage import Store
from learning_agent.course_graph import CourseGraphError
from pliac import margin


class InteractiveProvider(fixtures.LessonProvider):
    async def generate(self, schema, system, prompt, images=()):
        if schema is SectionAudit:
            self.calls.append((self.current_task.get(), schema))
            return SectionAudit(verdict="accept", findings="Synthetic review completed.", corrections=[])
        return await super().generate(schema, system, prompt, images)


class InteractivePipelineTests(unittest.IsolatedAsyncioTestCase):
    # Reuse the fixture, not the legacy-mode tests.
    run_lesson = fixtures.LessonProgressTests.run_lesson
    cancel_task = staticmethod(fixtures.LessonProgressTests.cancel_task)

    def setUp(self):
        fixtures.LessonProgressTests.setUp(self)
        self.request.delivery_mode = "interactive"
        self.provider = InteractiveProvider(self.plan, self.sections)

    async def test_prefix_available_before_remaining_work_and_survives_failure(self):
        self.provider.gate("section:2:draft")
        self.provider.fail.add("section:2:draft")
        published = asyncio.Event()
        snapshots = []
        def ready(lesson, total):
            snapshots.append((lesson, total))
            published.set()
        self.progress.section_ready = ready
        pending = asyncio.create_task(self.run_lesson())
        self.addAsyncCleanup(self.cancel_task, pending)
        await asyncio.wait_for(published.wait(), 3)
        self.assertFalse(pending.done())
        self.assertEqual(["s1"], [s.id for s in snapshots[0][0].sections])
        self.assertEqual(2, snapshots[0][1])
        self.provider.release["section:2:draft"].set()
        with self.assertRaises(ExceptionGroup):
            await pending
        self.assertTrue((self.output / "section-1.json").exists())
        self.assertEqual(1, len(snapshots))

    async def test_no_out_of_order_prefix_and_audit_does_not_rewrite(self):
        self.provider.gate("section:1:draft")
        snapshots = []
        self.progress.section_ready = lambda lesson, total: snapshots.append(lesson)
        pending = asyncio.create_task(self.run_lesson())
        self.addAsyncCleanup(self.cancel_task, pending)
        await asyncio.wait_for(self.provider.started["section:1:draft"].wait(), 3)
        self.assertTrue((self.output / "section-2.json").exists())
        self.assertEqual([], snapshots)
        self.provider.release["section:1:draft"].set()
        await pending
        self.assertEqual(["s1", "s2"], [s.id for s in snapshots[0].sections])
        self.assertEqual(2, sum(schema is GeneratedLessonSection for _, schema in self.provider.calls))
        self.assertEqual(80, self.progress.updates[-1][1])

    async def test_full_review_fallback_retains_validation(self):
        original = self.provider.generate
        async def generate(schema, *args):
            if schema is SectionAudit:
                return SectionAudit(verdict="full_review", findings="Structural repair needed.", corrections=[])
            return await original(schema, *args)
        self.provider.generate = generate
        await self.run_lesson()
        self.assertEqual(4, sum(schema is GeneratedLessonSection for _, schema in self.provider.calls))
        self.assertEqual(80, self.progress.updates[-1][1])


class AuditTests(unittest.TestCase):
    def setUp(self):
        self.section = GeneratedLessonSection(id="s1", title="Source", source_refs=["a:1"],
            explanation="A grounded explanation with sufficient length. The value is wrong.",
            worked_example="An example with a correctly explained outcome.",
            practice=[], study_prompts=[], unresolved_prerequisites=[],
            study_load=dict(explanation_minutes=1, worked_example_minutes=1,
                practice_minutes=0, rationale="Reading."))

    def audit(self, path="explanation", before="wrong", after="right"):
        return SectionAudit(verdict="correct", findings="Correct the value.", corrections=[
            dict(path=path, before=before, after=after, reason="Supported by source.")])

    def test_exact_patch_preserves_other_content_and_original(self):
        updated = apply_audit(self.section, self.audit())
        self.assertIn("right", updated.explanation)
        self.assertIn("wrong", self.section.explanation)
        self.assertEqual(updated.worked_example, self.section.worked_example)
        self.assertEqual(updated.source_refs, self.section.source_refs)

    def test_invalid_and_ambiguous_patches_cannot_escape_validation(self):
        for audit in (self.audit(path="source_refs.0"), self.audit(before="missing"),
                      self.audit(before=" "), self.audit(path="practice.9.answer"),
                      self.audit(before=self.section.explanation, after="short")):
            with self.subTest(audit=audit), self.assertRaises(ValueError):
                apply_audit(self.section, audit)
        with self.assertRaises(ValueError):
            SectionAudit(verdict="accept", findings="Incorrect combination.",
                         corrections=self.audit().corrections)

    def test_private_partial_survives_failed_job_without_unlocking_artifacts(self):
        from learnmargin.demo import demo_lesson
        with tempfile.TemporaryDirectory() as temp:
            course = SimpleNamespace(ensure_handouts=lambda: Path(temp))
            store = Store(Path(temp))
            job = dict(id="c" * 32, student_id="owner", status="running")
            margin.publish_reading(store, job, demo_lesson(), 4)
            response = margin.reading(job["id"], course_store=course, student_id="owner")
            self.assertTrue(Path(response.path).is_file())
            for wrong in ("other", ""):
                with self.assertRaises(CourseGraphError):
                    margin.reading(job["id"], course_store=course, student_id=wrong)
            with self.assertRaises(CourseGraphError):
                margin.artifact(job["id"], "lesson.html", course_store=course, student_id="owner")
            job["status"] = "failed"
            store.save_job(job)
            self.assertEqual(response.path, margin.reading(job["id"], course_store=course, student_id="owner").path)


class ReasoningTests(unittest.IsolatedAsyncioTestCase):
    async def test_concurrent_depths_and_explicit_override(self):
        async with Provider(APIConfig(), transport=httpx.MockTransport(lambda _: None)) as provider:
            provider.adaptive_reasoning = True
            async def payload(effort):
                with provider.reasoning_scope(effort):
                    await asyncio.sleep(0)
                    return provider._payload("system", "user", [])
            low, high = await asyncio.gather(payload("low"), payload("high"))
            self.assertEqual("low", low["reasoning_effort"])
            self.assertEqual("high", high["reasoning_effort"])
            self.assertIsNone(provider.config.reasoning_effort)
            provider.config.reasoning_effort = "none"
            self.assertEqual({"type": "disabled"}, (await payload("high"))["thinking"])
        async with Provider(APIConfig(base_url="https://unknown.example/v1"),
                            transport=httpx.MockTransport(lambda _: None)) as provider:
            provider.adaptive_reasoning = True
            self.assertNotIn("thinking", provider._payload("s", "u", []))
            self.assertNotIn("reasoning_effort", provider._payload("s", "u", []))


if __name__ == "__main__":
    unittest.main()
