"""Unknown courses use the same catalog, lesson, activity and handout pipelines."""
import asyncio
import copy
import json
import runpy
from pathlib import Path
import sys
import tempfile
import unittest
import uuid
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from learning_agent import api, course_package
from learning_agent.course_catalog import list_courses, resolve_course
from learning_agent.course_graph import CourseGraphStore, student_graph
from learnmargin.models import APIConfig
from pliac import margin
from pliac.ml_api import lab
from pliac.workspace import LearningWorkspace
from test_learning_workspace import platform_fixture, publish_synthetic


class UnifiedCourseTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.default = CourseGraphStore(output_dir=self.root / "records")

    def test_new_subject_with_authored_content_and_choices_uses_regular_store(self):
        graph = platform_fixture()
        graph.update(id="synthetic_botany", title="Synthetic botany", learning_order=["b", "a", "c", "d"])
        node = graph["nodes"][0]
        node["lesson_content"] = [{"id": "definition", "heading": "Plant cells", "text": "Synthetic authored paragraph."}]
        node["check_task"]["options"] = [{"id": "A", "text": "Leaf"}, {"id": "B", "text": "Root"}]
        graph["study"] = {"mixed_tasks": [{"id": "plant-compare", "nodes": [node["id"]], "question": "Compare organs",
            "options": ["Leaf", "Root"], "key": 1, "explanation": "SERVER_ONLY_KEY"}]}
        seed = self.root / "botany.json"
        seed.write_text(json.dumps(graph), encoding="utf-8")
        store = CourseGraphStore(seed, self.root / "botany")
        publish_synthetic(store)
        workspace = LearningWorkspace(store)
        def payload(**extra):
            return dict(student_id="synthetic", course_version=store.load_graph()["version"],
                        expected_version=store.load_learner("synthetic")["version"], request_id=uuid.uuid4().hex, **extra)
        workspace.onboard(payload())
        lesson = workspace.next_lesson(payload(node_id=node["id"]))["current_lesson"]
        self.assertEqual(lesson["paragraphs"], node["lesson_content"])
        self.assertEqual(lesson["options"], node["check_task"]["options"])
        answered = workspace.answer(payload(lesson_id=lesson["id"], choice_id="B", text="Synthetic reasoning"))
        self.assertIn("B. Root", answered["learner"]["evidence"][-1]["text"])
        self.assertEqual(answered["learner"]["diagnoses"], [])
        self.assertEqual(answered["study_activities"]["mixed_task"]["id"], "plant-compare")
        self.assertNotIn("SERVER_ONLY_KEY", json.dumps(student_graph(store.load_graph())))

    def test_snapshot_importer_uses_the_supplied_subject_and_scope(self):
        importer = runpy.run_path(str(Path(__file__).resolve().parents[1] / "scripts/build_textbook_demo.py"))
        guide = course_package.read(course_package.PACKAGES / "computer_organization_demo/guide.json")
        guide.update(id="synthetic_history", title="Synthetic history", source_title="History source",
                     subtitle="History guide", scope_note="Two source units", prerequisites=["Reading"],
                     review_plan=["Compare evidence"])
        guide["sections"] = list(reversed(guide["sections"][:2]))
        graph = importer["course_graph"](guide, "a" * 32)
        lesson = importer["lesson_for"](guide, guide["sections"], "a" * 32, guide["title"])
        self.assertEqual(graph["sources"][0]["title"], "History source")
        self.assertEqual(len(graph["chapters"]), 2)
        self.assertEqual(lesson.scope_note, "Two source units")
        self.assertEqual(lesson.overview.prerequisites, ["Reading"])
        self.assertTrue(all(s.document == "History source" for s in lesson.sources))

    def test_new_package_id_is_discovered_and_lab_preserves_its_course_context(self):
        # Rename every course node too: no implicit links to acceptance node IDs.
        source = course_package.PACKAGES / "ml_acceptance_demo"
        config = course_package.read(source / "package.json")
        graph = course_package.read(source / "course.json")
        ident = "synthetic_independent_course"
        graph["id"] = ident
        rename = {node["id"]: "new_" + node["id"] for node in graph["nodes"]}
        for node in graph["nodes"]:
            node["id"] = rename[node["id"]]
        for edge in graph["edges"]:
            edge["source"], edge["target"] = rename[edge["source"]], rename[edge["target"]]
        for chapter in graph["chapters"]:
            chapter["completion_policy"]["required_node_ids"] = [rename[i] for i in chapter["completion_policy"]["required_node_ids"]]
        graph["learning_order"] = [rename[i] for i in graph["learning_order"]]
        config.update(id=ident, runtime_path="independent/v1", study={})
        config.pop("concept_map")
        activity = config["activities"][0]
        activity["node_bindings"] = {key: rename[value] for key, value in activity["node_bindings"].items()}
        activity["knowledge_node_ids"] = [rename[i] for i in activity["knowledge_node_ids"]]
        activity["node_prompts"] = {rename[k]: v for k, v in activity["node_prompts"].items()}
        folder = self.root / "packages" / ident
        folder.mkdir(parents=True)
        (folder / "course.json").write_text(json.dumps(graph), encoding="utf-8")
        (folder / "package.json").write_text(json.dumps(config), encoding="utf-8")
        with patch.object(course_package, "PACKAGES", folder.parent), patch.object(api, "store", self.default):
            card = next(c for c in list_courses(self.default) if c["id"] == ident)
            self.assertTrue(card["capabilities"]["learn"])
            store = resolve_course(self.default, ident)
            self.assertIs(type(store), course_package.PackagedCourseStore)
            service = lab(ident)
            def payload(**extra):
                return dict(student_id="synthetic", course_version=1, expected_version=store.load_learner("synthetic")["version"],
                            request_id=uuid.uuid4().hex, **extra)
            started = service.act("start", payload(scene="space"))
            result = service.act("check", payload(session_id=started["active"]["id"],
                answer={"target": "target", "features": "sensors", "timing": "after"}))
            self.assertEqual(result["course_id"], ident)
            self.assertEqual(result["active"]["step"], 1)
            evidence = store.load_learner("synthetic")["evidence"]
            self.assertEqual({e["node_id"] for e in evidence}, {"new_sample", "new_leakage"})
            self.assertFalse((self.default.output_dir / "acceptance_demo").exists())

    async def test_handout_generation_dispatch_is_shared_and_keeps_preinstalled_jobs(self):
        seed = self.root / "regular.json"
        seed.write_text(json.dumps(platform_fixture()), encoding="utf-8")
        ordinary = CourseGraphStore(seed, self.root / "regular")
        stores = [ordinary, resolve_course(self.default, "ml_acceptance_demo"),
                  resolve_course(self.default, "computer_organization_demo")]
        calls = []
        async def run(store, job, request, documents, origins):
            calls.append((job["course_id"], documents))
            job.update(status="completed", progress=100, page_count=1)
            store.save_job(job)
        with patch.object(margin, "configured_api", return_value=APIConfig(base_url="http://127.0.0.1", model="synthetic")), \
             patch.object(margin, "run_job", side_effect=run):
            for course in stores:
                before = {j["id"] for j in margin.storage(course).jobs()}
                chapter = course.load_graph("draft")["chapters"][0]["id"]
                with patch.object(margin, "_body", new=AsyncMock(return_value={"chapter_id": chapter})):
                    job = await margin.generate(None, course)
                await margin.TASKS[job["id"]]
                await asyncio.sleep(0)
                after = {j["id"] for j in margin.storage(course).jobs()}
                self.assertEqual(after, before | {job["id"]})
                self.assertNotIn(job["id"], before)
                self.assertTrue(margin.listing(course)["capabilities"]["generate_handouts"])
        self.assertEqual(len(calls), 3)
        # Archived full pages feed the same generator without the original PDF/library.
        self.assertTrue(all(len(unit.text) > 100 for unit in calls[-1][1][0].units))


if __name__ == "__main__":
    unittest.main()
