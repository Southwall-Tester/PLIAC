"""Real course isolation and API routing contracts in temporary workspaces."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from learning_agent import api, document_api
from learning_agent.course_catalog import resolve_course
from learning_agent.course_graph import CourseGraphError, CourseGraphStore, validate_graph
from learning_agent.documents import DocumentStore


class CourseCatalogTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        original = CourseGraphStore().seed_path
        self.seed = self.base / "seed.json"
        self.seed.write_bytes(original.read_bytes())
        self.seed_bytes = self.seed.read_bytes()
        self.store = CourseGraphStore(self.seed, self.base / "courses-output")
        self.documents = DocumentStore(self.base / "documents")
        self.addCleanup(self.documents.executor.shutdown, wait=True)
        self.enterContext(patch.object(api, "store", self.store))
        self.enterContext(patch.object(document_api, "document_store", self.documents))
        app = FastAPI()
        app.include_router(api.router)
        app.include_router(api.courses_router)
        app.include_router(document_api.router)
        self.client = self.enterContext(TestClient(app))

    def create(self, title="测试课程", **extra):
        result = self.client.post("/api/courses", json={"title": title, **extra})
        self.assertEqual(result.status_code, 200, result.text)
        return result.json()

    def graph(self, course_id="", view="draft"):
        result = self.client.get("/api/course-graph", params={"course_id": course_id, "view": view})
        self.assertEqual(result.status_code, 200, result.text)
        return result.json()["graph"]

    def populate(self, course_id):
        graph = self.graph(course_id)
        graph["nodes"] = [{
            "id": "same_concept", "title": "合成测试概念", "chapter_id": graph["chapters"][0]["id"],
            "description": "合成测试定义", "objectives": [], "misconception": "", "aliases": [],
            "source_ids": [], "review_status": "reviewed", "reviewer": "Synthetic reviewer",
            "reviewed_at": "2026-10-08T00:00:00Z", "review_note": "Synthetic test review",
        }]
        result = self.client.put("/api/course-graph", params={"course_id": course_id},
                                 json={"graph": graph, "expected_version": graph["version"]})
        self.assertEqual(result.status_code, 200, result.text)
        version = result.json()["graph"]["version"]
        result = self.client.post("/api/course-graph/publish", params={"course_id": course_id},
                                  json={"expected_version": version, "published_by": "Synthetic publisher", "note": "Synthetic test"})
        self.assertEqual(result.status_code, 200, result.text)
        return version

    def test_listing_and_default_alias_are_read_only(self):
        result = self.client.get("/api/courses")
        self.assertEqual(result.status_code, 200, result.text)
        course, = result.json()["courses"]
        self.assertTrue(course["is_default"])
        self.assertEqual(course["node_count"], 40)
        self.assertEqual(self.graph(), self.graph(course["id"]))
        self.assertIsNone(course["published_version"])
        self.assertFalse(self.store.output_dir.exists())
        self.assertEqual(self.seed.read_bytes(), self.seed_bytes)

    def test_creation_has_only_real_empty_structure_and_persists(self):
        created = self.create("  新课程  ", chapter_title="课程概览")
        course, graph = created["course"], created["graph"]
        self.assertRegex(course["id"], r"^[0-9a-f]{32}$")
        self.assertEqual(graph["title"], "新课程")
        self.assertEqual(graph["chapters"], [{"id": "chapter_1", "title": "课程概览", "description": ""}])
        for key in ("nodes", "edges", "resources", "sources"):
            self.assertEqual(graph[key], [])
        self.assertEqual(self.graph(course["id"]), graph)
        self.assertIsNone(self.graph(course["id"], "published"))
        files = list((self.store.output_dir / "courses" / course["id"]).rglob("*"))
        self.assertEqual([p.name for p in files], ["draft.json"])
        self.assertFalse(self.store.graph_path.exists())
        self.assertEqual(self.seed.read_bytes(), self.seed_bytes)

    def test_invalid_creation_and_course_paths_do_not_write(self):
        for title in (None, "", " " * 10, "a" * 201, ["bad"]):
            self.assertEqual(self.client.post("/api/courses", json={"title": title}).status_code, 400)
        for course_id in ("../other", "..\\other", "CON", "a/b", "a" * 65):
            result = self.client.get("/api/course-graph", params={"course_id": course_id, "view": "draft"})
            self.assertEqual(result.status_code, 400, result.text)
        for course_id in ("a" * 32, "missing_course"):
            self.assertEqual(self.client.get("/api/course-graph", params={"course_id": course_id}).status_code, 404)
        self.assertFalse(self.store.output_dir.exists())

    def test_empty_draft_can_save_and_validate_but_never_publish(self):
        created = self.create()
        ident, graph = created["course"]["id"], created["graph"]
        with self.assertRaises(CourseGraphError):
            validate_graph(graph)
        self.assertEqual(validate_graph(graph, allow_empty=True)["node_count"], 0)
        self.assertEqual(self.client.post("/api/course-graph/validate", params={"course_id": ident}, json={"graph": graph}).status_code, 200)
        saved = self.client.put("/api/course-graph", params={"course_id": ident}, json={"graph": graph, "expected_version": 1})
        self.assertEqual(saved.status_code, 200, saved.text)
        result = self.client.post("/api/course-graph/publish", params={"course_id": ident},
                                  json={"expected_version": 2, "published_by": "Synthetic publisher", "note": "Synthetic test"})
        self.assertEqual(result.status_code, 400, result.text)
        self.assertFalse((self.store.output_dir / "courses" / ident / "publication.json").exists())
        self.assertIsNone(self.graph(ident, "published"))

    def test_two_course_edits_are_isolated_and_conflicts_stay_local(self):
        first, second = self.create("课程一"), self.create("课程二")
        aid, bid = first["course"]["id"], second["course"]["id"]
        first["graph"]["chapters"][0]["title"] = "改过的章节"
        result = self.client.put("/api/course-graph", params={"course_id": aid},
                                 json={"graph": first["graph"], "expected_version": 1})
        self.assertEqual(result.status_code, 200, result.text)
        stale = self.client.put("/api/course-graph", params={"course_id": aid},
                                json={"graph": first["graph"], "expected_version": 1})
        self.assertEqual(stale.status_code, 409)
        self.assertEqual(self.graph(bid), second["graph"])
        self.assertEqual(self.graph()["version"], 1)
        self.assertFalse(self.store.graph_path.exists())
        self.assertEqual(self.seed.read_bytes(), self.seed_bytes)
        catalog = {c["id"]: c for c in self.client.get("/api/courses").json()["courses"]}
        self.assertEqual(catalog[aid]["draft_version"], 2)
        self.assertEqual(catalog[bid]["draft_version"], 1)
        wrong = copy.deepcopy(self.graph(aid))
        wrong["id"] = bid
        self.assertEqual(self.client.put("/api/course-graph", params={"course_id": aid},
                                        json={"graph": wrong, "expected_version": 2}).status_code, 400)

    def test_same_learner_and_node_ids_do_not_mix_across_courses(self):
        aid, bid = self.create("课程一")["course"]["id"], self.create("课程二")["course"]["id"]
        av, bv = self.populate(aid), self.populate(bid)
        for ident, version, text in ((aid, av, "课程一的作答"), (bid, bv, "课程二的作答")):
            result = self.client.post("/api/course-graph/evidence", params={"course_id": ident}, json={
                "student_id": "same_learner", "node_id": "same_concept", "course_version": version,
                "source_type": "manual", "origin": "learner_expression", "prompt_level": 0,
                "text": text, "context": {}, "expected_version": 0,
            })
            self.assertEqual(result.status_code, 200, result.text)
            self.assertEqual(result.json()["evidence"]["course_id"], ident)
        a = self.client.get("/api/course-graph/learner/export", params={"course_id": aid, "student_id": "same_learner"}).json()
        b = self.client.get("/api/course-graph/learner/export", params={"course_id": bid, "student_id": "same_learner"}).json()
        self.assertEqual([e["text"] for e in a["evidence"]], ["课程一的作答"])
        self.assertEqual([e["text"] for e in b["evidence"]], ["课程二的作答"])
        self.assertEqual(self.store.load_learner("same_learner")["evidence"], [])
        self.assertFalse((self.store.output_dir / "learners").exists())

    def test_all_course_routes_validate_course_id(self):
        unknown = {"course_id": "f" * 32, "student_id": "s", "target_id": "n", "node_id": "n"}
        for method, path in (("get", ""), ("put", ""), ("post", "/publish"), ("get", "/export"),
                             ("get", "/teacher/export"), ("post", "/validate"), ("get", "/teacher/audit"),
                             ("get", "/learner/export"), ("post", "/evidence"), ("post", "/diagnoses"),
                             ("put", "/profile"), ("get", "/path"), ("get", "/recommendations"),
                             ("post", "/resource-use"), ("post", "/extract")):
            result = self.client.request(method, "/api/course-graph" + path, params=unknown)
            self.assertEqual(result.status_code, 404, f"{method} {path}: {result.text}")
        self.assertFalse(self.store.output_dir.exists())

    def test_document_import_targets_chosen_course_and_preserves_conflicts(self):
        aid, bid = self.create("目标课程")["course"]["id"], self.create("其他课程")["course"]["id"]
        job = self.documents.create("合成教材.txt")
        self.documents.source(job["id"]).write_text("知识图谱包括实体和关系。实体对齐用于知识融合。", encoding="utf-8")
        self.documents.run(job["id"])
        endpoint = f"/api/documents/{job['id']}/import"
        result = self.client.post(endpoint, json={"course_id": aid, "expected_version": 1})
        self.assertEqual(result.status_code, 200, result.text)
        graph = result.json()["graph"]
        self.assertEqual(graph["id"], aid)
        self.assertTrue(graph["nodes"])
        self.assertTrue(all(n["review_status"] == "draft" for n in graph["nodes"]))
        self.assertEqual(self.graph(bid)["nodes"], [])
        self.assertFalse(self.store.graph_path.exists())
        self.assertEqual(self.seed.read_bytes(), self.seed_bytes)
        self.assertEqual(self.client.post(endpoint, json={"course_id": aid, "expected_version": 1}).status_code, 409)
        self.assertEqual(self.client.post(endpoint, json={"course_id": "e" * 32, "expected_version": 1}).status_code, 404)
        for bad in ("../outside", None, False, 0):
            self.assertEqual(self.client.post(endpoint, json={"course_id": bad, "expected_version": 1}).status_code, 400)
        self.assertEqual(self.graph(aid)["version"], 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
