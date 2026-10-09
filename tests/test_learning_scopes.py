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
from learnmargin.models import APIConfig, Document, SourceUnit
from learnmargin.storage import atomic_json
from pliac import margin, learning_scope, handout_practice
from pliac.margin_graph import overview_map
from pliac.workspace import LearningWorkspace


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
