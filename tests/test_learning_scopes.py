"""Bounded sources and raw exercise evidence; synthetic data, no model calls."""
import asyncio
import json
from pathlib import Path
import tempfile
import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from test_learning_workspace import platform_fixture, publish_synthetic
from learning_agent.course_graph import CourseGraphStore, CourseGraphError
from learnmargin.demo import demo_lesson
from learnmargin.models import APIConfig, Document, SourceUnit, Practice, GeneratedPractice, GeneratedStudyPrompt
from learnmargin.storage import atomic_json
from learnmargin.rendering import render_lesson
from pliac import margin, learning_scope, handout_practice
from pliac.margin_graph import overview_map
from pliac.workspace import LearningWorkspace
from pliac.answer_options import build_choice_bundle, register_generated


class ScopeTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        seed = root / "course.json"
        seed.write_text(json.dumps(platform_fixture()), encoding="utf-8")
        self.course = CourseGraphStore(seed, root / "records")
        self.graph = publish_synthetic(self.course)
        self.store = margin.storage(self.course)

    def seed_job(self, selection=None):
        scope = learning_scope.resolve(self.graph, selection or {}, self.store)
        job = dict(id=uuid.uuid4().hex, course_id=self.graph["id"], course_version=self.graph["version"],
                   chapter_id=scope["chapter_id"], scope=scope, status="completed", created_at="2026-10-09", page_count=1)
        lesson = demo_lesson()
        ident = "a" * 32
        for i, section in enumerate(lesson.sections, 1):
            section.source_refs = [f"{ident}:{i}"]
        folder = self.store.directory("jobs", job["id"])
        atomic_json(folder / "lesson.json", lesson.model_dump())
        atomic_json(folder / "knowledge-map.json", overview_map(lesson))
        doc = Document(id=ident, name="Synthetic source", kind="course_material", unit_label="page",
                       units=[SourceUnit(index=i, label=s.title, text=s.explanation) for i, s in enumerate(lesson.sections, 1)])
        atomic_json(folder / "materials.json", {"documents": [doc.model_dump()], "origins": {}})
        self.store.save_job(job)
        return job

    def test_chapter_range_and_node_material_do_not_leak(self):
        graph = self.graph
        chapter = graph["chapters"][0]
        doc = "a" * 32
        chapter["source_ranges"] = [{"document_id": doc, "start_page": 2, "end_page": 4}]
        graph["nodes"] = [dict(graph["nodes"][0], document_id=doc, document_evidence=[{"page": 3}, {"page": 99}])]
        documents = SimpleNamespace(status=lambda _: {"title": "Synthetic source", "page_kind": "pdf"},
                                    page=lambda _, index: {"text": f"Synthetic page {index}"})
        chapter_scope = learning_scope.resolve(graph, {"chapter_id": chapter["id"]}, self.store)
        docs, _ = margin.materials(graph, chapter["id"], documents, chapter_scope)
        self.assertEqual([2, 3, 4], [u.index for u in docs[0].units])
        node_scope = learning_scope.resolve(graph, {"node_id": graph["nodes"][0]["id"]}, self.store)
        docs, _ = margin.materials(graph, node_scope["chapter_id"], documents, node_scope)
        self.assertEqual([3, 99], [u.index for u in docs[0].units])
        self.assertNotEqual(chapter_scope["key"], node_scope["key"])

    def test_directory_membership_and_prerequisites_are_separate(self):
        chapter = self.graph["chapters"][0]
        selected = self.graph["nodes"][1]
        chapter["document_hierarchy"] = {"nodes": [
            {"id": "part", "title": "Part", "kind": "chapter", "parent_id": None},
            {"id": "sub", "title": "Sub", "kind": "chapter", "parent_id": "part"}],
            "memberships": [{"source": "sub", "target": selected["id"]}]}
        scope = learning_scope.resolve(self.graph, {"chapter_id": chapter["id"], "section_id": "part"}, self.store)
        self.assertEqual([selected["id"]], scope["node_ids"])
        self.assertEqual("section", scope["kind"])
        self.assertFalse(set(scope["node_ids"]) & {n["id"] for n in scope["prerequisites"]})
        with self.assertRaises(CourseGraphError):
            learning_scope.resolve(self.graph, {"section_id": "part"}, self.store)

    def test_concept_reads_only_server_saved_references(self):
        job = self.seed_job()
        graph = learning_scope.saved(self.store, job["id"], "knowledge-map.json")
        node = graph["nodes"][0]
        scope = learning_scope.resolve(self.graph, {"source_job_id": job["id"], "concept_id": node["id"],
                                                    "source_refs": ["forged:999"]}, self.store)
        docs, _ = learning_scope.concept_materials(scope, self.store)
        self.assertEqual(set(node["source_refs"]), {f"{d.id}:{u.index}" for d in docs for u in d.units})
        self.assertEqual([], scope["node_ids"])
        job["course_id"] = "another_course"
        self.store.save_job(job)
        with self.assertRaises(CourseGraphError):
            learning_scope.resolve(self.graph, scope, self.store)
        with self.assertRaises(CourseGraphError):
            learning_scope.saved(self.store, "../outside", "lesson.json")

    def test_practice_drafts_retries_exposure_and_no_mastery(self):
        job = self.seed_job()
        second = self.seed_job({"node_id": self.graph["nodes"][0]["id"]})
        state = handout_practice.view(self.course, self.store, job["id"], "synthetic")
        question = state["questions"][0]
        self.assertIsNone(question["hint"])
        self.assertIsNone(question["answer"])
        def act(operation, **extra):
            return dict(student_id="synthetic", expected_version=state["version"], request_id=uuid.uuid4().hex,
                        operation=operation, question_id=question["id"], **extra)
        state = handout_practice.mutate(self.course, self.store, job["id"], act("draft", text="draft evidence"))
        self.assertEqual("draft evidence", state["drafts"][question["id"]])
        stale = act("answer", text="stale answer")
        state = handout_practice.mutate(self.course, self.store, job["id"], act("solution"))
        self.assertEqual(2, state["questions"][0]["exposure"])
        with self.assertRaises(CourseGraphError):
            handout_practice.mutate(self.course, self.store, job["id"], stale)
        payload = act("answer", text="Synthetic reasoning after reading solution")
        state = handout_practice.mutate(self.course, self.store, job["id"], payload)
        replay = handout_practice.mutate(self.course, self.store, job["id"], payload)
        self.assertEqual(state, replay)
        self.assertEqual({}, state["drafts"])
        self.assertEqual(1, state["answered"])
        self.assertEqual(0, handout_practice.view(self.course, self.store, second["id"], "synthetic")["answered"])
        self.assertEqual(0, handout_practice.view(self.course, self.store, job["id"], "someone_else")["answered"])
        learner = LearningWorkspace(self.course).view("synthetic")["learner"]
        self.assertEqual([], learner["diagnoses"])
        self.assertEqual(1, len(learner["evidence"]))
        self.assertEqual(2, learner["evidence"][0]["prompt_level"])
        self.assertEqual(job["scope"], learner["evidence"][0]["context"]["scope"])
        self.assertTrue(all(s["status"] != "mastered" for s in learner["states"].values()))

    def test_generated_practice_requires_actual_distinct_answer_options(self):
        data = dict(id="q", prompt="求 P(R|S) 并判断独立性", hint="检查分母", answer="2/5，独立")
        self.assertFalse(Practice(**data).options)  # Old artifacts remain loadable.
        with self.assertRaises(ValueError):
            GeneratedPractice(**data)
        options = [{"id": "A", "text": "2/5，独立"}, {"id": "B", "text": "1/10，不独立"},
                   {"id": "C", "text": "1/4，独立"}]
        generated = GeneratedPractice(**data, options=options, answer_key="A")
        self.assertEqual(generated.options[0].text, "2/5，独立")
        with self.assertRaises(ValueError):
            GeneratedPractice(**data, options=options, answer_key="D")
        with self.assertRaises(ValueError):
            GeneratedPractice(**data, options=[options[0], options[0], options[2]], answer_key="A")
        sidebar = dict(id="s", kind="question", placement="after_example", when="看完例题后",
                       task=data["prompt"], check="核对条件", answer=data["answer"])
        with self.assertRaises(ValueError):
            GeneratedStudyPrompt(**sidebar)
        self.assertEqual(len(GeneratedStudyPrompt(**sidebar, options=options, answer_key="A").options), 3)

    def test_choices_validate_scope_and_keep_supplement_and_exposure_separate(self):
        job = self.seed_job()
        folder = self.store.directory("jobs", job["id"])
        lesson = learning_scope.saved(self.store, job["id"], "lesson.json")
        question = next(item for section in lesson["sections"] for item in section.get("practice", []))
        question.update(options=[{"id": "A", "text": "2/5，独立"}, {"id": "B", "text": "1/10，不独立"},
                                 {"id": "C", "text": "1/4，独立"}], answer_key="A")
        atomic_json(folder / "lesson.json", lesson)
        state = handout_practice.view(self.course, self.store, job["id"], "choices")
        original = next(item for item in state["questions"] if item["kind"] == "practice")
        self.assertEqual(original["options"], question["options"])
        self.assertNotIn("answer_key", original)
        self.assertIsNone(original["answer"])
        legacy = next(item for item in state["questions"] if item["kind"] == "study_question")
        legacy_bundle = build_choice_bundle(legacy["original_prompt"], existing_options=[
            {"id": "A", "text": "P(A|B) 的分母为戴眼镜的10人，P(B|A) 的分母为社团成员12人。"},
            {"id": "B", "text": "两个条件概率都以全班30人为分母。"},
            {"id": "C", "text": "两个条件概率都以同时满足条件的6人为分母。"}], answer_key="A",
            scope=f"handout:{job['id']}:{legacy['id']}")
        legacy_bundle["origin"] = "model_generated"
        register_generated(f"handout:{job['id']}:{legacy['id']}", legacy_bundle)
        state = handout_practice.view(self.course, self.store, job["id"], "choices")
        upgraded = next(item for item in state["questions"] if item["id"] == legacy["id"])
        self.assertNotIn("check", upgraded)
        self.assertIsNone(upgraded["hint"])
        self.assertEqual(upgraded["prompt"], legacy["original_prompt"])
        self.assertEqual(len(upgraded["options"]), 3)
        self.assertEqual(upgraded["origin"], "model_generated")
        def payload(operation="answer", **values):
            return dict(student_id="choices", expected_version=state["version"], request_id=uuid.uuid4().hex,
                        question_id=original["id"], operation=operation, **values)
        for fields in ({"choice_id": "outside"}, {"choice_id": "A", "option_set_id": "forged"}):
            with self.assertRaises(CourseGraphError):
                handout_practice.mutate(self.course, self.store, job["id"], payload(**fields))
        state = handout_practice.mutate(self.course, self.store, job["id"], payload(
            "draft", choice_id="B", option_set_id=original["option_set_id"], text="optional draft"))
        self.assertEqual(state["choice_drafts"][original["id"]], "B")
        state = handout_practice.mutate(self.course, self.store, job["id"], payload("hint"))
        submission = payload(choice_id="B", option_set_id=original["option_set_id"], text="", choice_text="forged text")
        state = handout_practice.mutate(self.course, self.store, job["id"], submission)
        self.assertEqual(handout_practice.mutate(self.course, self.store, job["id"], submission), state)
        record = self.course._read_learner("choices")
        evidence = record["evidence"][0]
        self.assertIn("1/10，不独立", evidence["text"])
        self.assertNotIn("forged text", evidence["text"])
        self.assertEqual(evidence["context"]["supplement"], "")
        self.assertEqual(evidence["context"]["answer_mode"], "recognition")
        self.assertEqual(evidence["prompt_level"], 1)
        self.assertEqual(record["diagnoses"], [])
        self.assertEqual(state["drafts"], {})
        self.assertEqual(state["choice_drafts"], {})

    async def test_new_options_preserve_a4_and_wide_pagination_and_navigation(self):
        lesson = demo_lesson()
        options = [{"id": "A", "text": "条件概率以已知事件中的人数为分母，并保留交集中同时满足两个条件的人数。"},
                   {"id": "B", "text": "条件概率总以全部样本为分母，无论已经给定了什么条件，抽取范围都不变化。"},
                   {"id": "C", "text": "条件概率以交集人数为分母，并用全部样本的人数作为分子，得到比较的比例。"}]
        sidebar = lesson.sections[0].study_prompts[0]
        sidebar.options = Practice(id="q", prompt="q", hint="h", answer="a",
                                   options=options, answer_key="A").options
        sidebar.answer_key = "A"
        practice = lesson.sections[1].practice[0]
        practice.options = sidebar.options
        practice.answer_key = "A"
        for layout in ("a4", "wide"):
            result = await render_lesson(lesson, Path(self.tmp.name) / ("render-" + layout), layout=layout)
            self.assertTrue(result["content_preserved"])
            self.assertEqual(result["overflow"], [])
            self.assertEqual(result["browser_errors"], [])
            self.assertTrue(result["sidebar_navigation"])

    async def test_generation_scopes_and_versions_keep_jobs_separate(self):
        calls = []
        async def run(store, job, request, docs, origins):
            calls.append((job, request, docs))
            job.update(status="completed", page_count=1)
            store.save_job(job)
        with patch.object(margin, "configured_api", return_value=APIConfig(base_url="http://localhost", model="synthetic")), \
             patch.object(margin, "run_job", side_effect=run):
            for selection in [{"chapter_id": self.graph["chapters"][0]["id"]}, {"node_id": self.graph["nodes"][0]["id"]}]:
                with patch.object(margin, "_body", new=AsyncMock(return_value={"scope": selection})):
                    job = await margin.generate(None, self.course)
                await margin.TASKS[job["id"]]
                await asyncio.sleep(0)
        self.assertEqual(2, len({job["id"] for job, _, _ in calls}))
        self.assertEqual(["all", "topics"], [request.scope.mode for _, request, _ in calls])
        self.assertEqual(1, sum(len(d.units) for d in calls[1][2]))
        listing = margin.listing(self.course, node_id=self.graph["nodes"][0]["id"])
        self.assertEqual([calls[1][0]["id"]], [j["id"] for j in listing["scope_jobs"]])


if __name__ == "__main__":
    unittest.main()
