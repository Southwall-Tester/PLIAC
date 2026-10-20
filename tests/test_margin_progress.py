"""Progress follows real milestones, including concurrent and failed model work."""
import asyncio
import json
import sys
import tempfile
import unittest
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from learnmargin.demo import demo_lesson
from learnmargin.models import APIConfig, Document, GenerateRequest, GeneratedLessonSection, LessonPlan, SourceUnit
from learnmargin.pipeline import SectionSourceReview, generate_lesson
from learnmargin.provider import ProviderError
from learnmargin.storage import Store
from pliac.margin_graph import Relations, Vocabulary, VocabularyAudit, generate_map


class Recorder:
    def __init__(self):
        self.updates = []
        self.events = []

    def __call__(self, label, percent):
        self.updates.append((label, percent))

    def detail(self, event):
        self.events.append({**event, "percent": self.updates[-1][1]})

    def task_events(self, task_id):
        return [event for event in self.events if event["task_id"] == task_id]


class LessonProvider:
    """Deterministic author with independently controllable concurrent requests."""

    def __init__(self, plan, sections):
        self.plan = plan
        self.sections = sections
        self.current_task = ContextVar("progress_test_task", default="")
        self.calls = []
        self.release = {}
        self.started = {}
        self.finished = {}
        self.fail = set()
        self.invalid_plan = False
        self.plan_calls = 0

    @contextmanager
    def observe_task(self, task_id):
        token = self.current_task.set(task_id)
        try:
            yield
        finally:
            self.current_task.reset(token)

    def gate(self, task_id):
        self.release[task_id] = asyncio.Event()
        self.started[task_id] = asyncio.Event()
        self.finished[task_id] = asyncio.Event()

    async def generate(self, schema, system, prompt, images=()):
        task_id = self.current_task.get()
        self.calls.append((task_id, schema))
        if task_id in self.release:
            self.started[task_id].set()
            await self.release[task_id].wait()
            # This assertion also checks that another section never replaced this context.
            assert self.current_task.get() == task_id
            if task_id in self.fail:
                raise ProviderError("synthetic request failed")
            self.finished[task_id].set()
        if schema is LessonPlan:
            self.plan_calls += 1
            plan = self.plan.model_copy(deep=True)
            if self.invalid_plan and self.plan_calls == 1:
                plan.sections[1].source_refs = plan.sections[0].source_refs.copy()
            return plan
        if schema is SectionSourceReview:
            return SectionSourceReview(additions=[])
        assert schema is GeneratedLessonSection, schema
        return self.sections[int(task_id.split(":")[1]) - 1].model_copy(deep=True)


class LessonProgressTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.store = Store(self.root / "store")
        self.output = self.store.directory("jobs", "b" * 32)
        references = self.root / "skill" / "references"
        references.mkdir(parents=True)
        for name in ("book-map.md", "learning-design.md"):
            (references / name).write_text("Synthetic design reference.", encoding="utf-8")
        self.enterContext(patch("learnmargin.pipeline.skill_directory", return_value=references.parent))
        self.enterContext(patch("learnmargin.pipeline.load_methods", return_value="Synthetic methods."))
        document = Document(id="a" * 32, name="Synthetic material", kind="text", unit_label="section",
                            units=[SourceUnit(index=i, label=f"Section {i}", text="Grounded source material. " * 4)
                                   for i in (1, 2)])
        self.documents = [document]
        self.request = GenerateRequest(document_ids=[document.id],
                                       api=APIConfig(base_url="http://synthetic.invalid", model="synthetic", vision=False))
        demo = demo_lesson()
        self.plan = LessonPlan(
            title=demo.title, subtitle=demo.subtitle, text=demo.text, overview=demo.overview,
            review_plan=demo.review_plan, method_chapters=demo.method_chapters,
            sections=[dict(id=f"s{i}", title=f"Section {i}", objective="Explain the grounded source.",
                           source_refs=[f"{document.id}:{i}"]) for i in (1, 2)],
        )
        self.sections = [GeneratedLessonSection(
            id=planned.id, title=planned.title, source_refs=planned.source_refs,
            explanation="This explanation stays within the supplied source and explains its meaning.",
            worked_example="A worked example explains the source conditions and the resulting conclusion.",
            practice=[], study_prompts=[], unresolved_prerequisites=[],
            study_load=dict(explanation_minutes=1, worked_example_minutes=1, practice_minutes=0,
                            rationale="Synthetic reading and example."),
        ) for planned in self.plan.sections]
        self.provider = LessonProvider(self.plan, self.sections)
        self.progress = Recorder()

    def run_lesson(self, progress=None):
        return generate_lesson(self.request, self.documents, self.store, self.output,
                               self.provider, self.progress if progress is None else progress)

    async def test_concurrent_writers_leave_24_before_first_response_and_count_actual_work(self):
        for section in (1, 2):
            for stage in ("draft", "review"):
                self.provider.gate(f"section:{section}:{stage}")
        pending = asyncio.create_task(self.run_lesson())
        self.addAsyncCleanup(self.cancel_task, pending)
        await asyncio.wait_for(asyncio.gather(
            *(self.provider.started[f"section:{i}:draft"].wait() for i in (1, 2))), 2)
        self.assertEqual(35, self.progress.updates[-1][1])
        self.assertEqual({"section:1:draft", "section:2:draft"},
                         {event["task_id"] for event in self.progress.events
                          if event["phase"] == "writing" and event["status"] == "running"})
        self.assertFalse(any(event["status"] == "completed" for event in self.progress.events
                             if event["phase"] == "writing"))
        self.provider.release["section:2:draft"].set()
        await asyncio.wait_for(self.provider.started["section:2:review"].wait(), 2)
        self.assertEqual(42, self.progress.updates[-1][1])
        self.assertEqual("running", self.progress.task_events("section:1:draft")[-1]["status"])
        self.assertEqual("completed", self.progress.task_events("section:2:draft")[-1]["status"])
        for gate in self.provider.release.values():
            gate.set()
        lesson = await asyncio.wait_for(pending, 2)
        self.assertEqual(2, len(lesson.sections))
        self.assertEqual(80, self.progress.updates[-1][1])
        self.assertEqual(sorted(percent for _, percent in self.progress.updates),
                         [percent for _, percent in self.progress.updates])
        completed = [event for event in self.progress.events
                     if event["task_id"].startswith("section:") and event["status"] == "completed"]
        self.assertEqual(6, len(completed))
        self.assertTrue(all(event["section_total"] == 2 for event in completed))
        for i in (1, 2):
            self.assertTrue((self.output / f"section-{i}.json").is_file())

    async def test_failed_request_cancels_sibling_without_completed_credit(self):
        for section in (1, 2):
            self.provider.gate(f"section:{section}:draft")
        self.provider.fail.add("section:1:draft")
        pending = asyncio.create_task(self.run_lesson())
        self.addAsyncCleanup(self.cancel_task, pending)
        await asyncio.wait_for(asyncio.gather(
            *(self.provider.started[f"section:{i}:draft"].wait() for i in (1, 2))), 2)
        self.provider.release["section:1:draft"].set()
        with self.assertRaises(ExceptionGroup):
            await asyncio.wait_for(pending, 2)
        self.assertEqual("failed", self.progress.task_events("section:1:draft")[-1]["status"])
        self.assertEqual("cancelled", self.progress.task_events("section:2:draft")[-1]["status"])
        self.assertEqual(35, max(percent for _, percent in self.progress.updates))
        self.assertFalse(any(event["status"] == "completed" for event in self.progress.events
                             if event["phase"] == "writing"))

    async def test_coverage_repair_has_own_task_and_no_early_progress_credit(self):
        self.provider.invalid_plan = True
        await self.run_lesson()
        coverage = self.progress.task_events("plan:coverage")
        repairs = [event for event in coverage if event.get("attempt")]
        self.assertEqual(1, len(repairs))
        self.assertEqual(26, repairs[0]["percent"])
        self.assertEqual("running", repairs[0]["status"])
        self.assertEqual(28, coverage[-1]["percent"])
        self.assertIn(("plan:coverage", LessonPlan), self.provider.calls)
        self.assertIn(("plan:sources", SectionSourceReview), self.provider.calls)
        self.assertEqual("completed", self.progress.task_events("plan:sources")[-1]["status"])

    async def test_section_validation_failure_never_marks_section_validated(self):
        self.sections[1].source_refs = ["unknown:1"]
        with self.assertRaises(ExceptionGroup):
            await self.run_lesson()
        self.assertEqual("failed", self.progress.task_events("section:2:validate")[-1]["status"])
        self.assertLess(max(percent for _, percent in self.progress.updates), 80)
        self.assertFalse((self.output / "section-2.json").exists())

    async def test_ordinary_two_argument_callback_remains_usable(self):
        updates = []
        await self.run_lesson(lambda label, percent: updates.append((label, percent)))
        self.assertEqual(80, updates[-1][1])
        self.assertTrue(any("审校" in label for label, _ in updates))

    @staticmethod
    async def cancel_task(task):
        if not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass


class GraphProgressTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.lesson = demo_lesson()
        self.vocabulary = Vocabulary(nodes=[dict(id="term", title="条件概率", definition="在已知条件下计算概率",
                                                section_ids=["s1"], evidence_id="p1")])
        self.audit = VocabularyAudit(decisions=[dict(id="term", atomic=True, domain_term=True,
                                                    reason="可以独立定义的学科术语")])
        self.progress = Recorder()

    def provider(self, values):
        return SimpleNamespace(generate=AsyncMock(side_effect=values))

    async def test_graph_steps_report_validated_milestones(self):
        provider = self.provider([self.vocabulary, self.audit, Relations(edges=[])])
        graph = await generate_map(self.lesson, provider, self.progress)
        self.assertEqual(1, len(graph["nodes"]))
        completed = [event for event in self.progress.events if event["status"] == "completed"]
        self.assertEqual(["graph:passages", "graph:vocabulary", "graph:audit",
                          "graph:relations", "graph:validate"], [event["task_id"] for event in completed])
        self.assertEqual([82, 83, 85, 87, 88], [event["percent"] for event in completed])
        self.assertEqual(88, max(percent for _, percent in self.progress.updates))

    async def test_retry_does_not_credit_invalid_vocabulary(self):
        invalid = self.vocabulary.model_copy(deep=True)
        invalid.nodes[0].evidence_id = "missing"
        provider = self.provider([invalid, self.vocabulary, self.audit, Relations(edges=[])])
        await generate_map(self.lesson, provider, self.progress)
        events = self.progress.task_events("graph:vocabulary")
        self.assertEqual(["running", "running", "completed"], [event["status"] for event in events])
        self.assertEqual([82, 82, 83], [event["percent"] for event in events])
        self.assertEqual(1, events[1]["attempt"])

    async def test_failed_graph_keeps_last_real_milestone(self):
        invalid = Relations(edges=[dict(source="term", target="missing", predicate="depends on", evidence_id="p1")])
        provider = self.provider([self.vocabulary, self.audit, invalid])
        with self.assertRaises(ValueError):
            await generate_map(self.lesson, provider, self.progress)
        self.assertEqual("failed", self.progress.task_events("graph:validate")[-1]["status"])
        self.assertEqual(87, max(percent for _, percent in self.progress.updates))
        self.assertFalse(any(event["task_id"] == "graph:validate" and event["status"] == "completed"
                             for event in self.progress.events))

    async def test_plain_callback_and_legacy_two_argument_call(self):
        for progress in (None, lambda label, percent: self.progress(label, percent)):
            provider = self.provider([self.vocabulary, self.audit, Relations(edges=[])])
            if progress is None:
                result = await generate_map(self.lesson, provider)
            else:
                result = await generate_map(self.lesson, provider, progress)
            self.assertEqual("concept-first-v2", result["policy_version"])
        self.assertEqual(88, self.progress.updates[-1][1])


if __name__ == "__main__":
    unittest.main()
