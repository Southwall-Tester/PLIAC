"""Course content, non-publishing installation and shared material boundaries."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "scripts")]
from build_linux_course import build, COURSE_ID, DEST
from install_course_draft import install
from learning_agent.course_catalog import list_courses, resolve_course
from learning_agent.course_graph import CourseGraphError, CourseGraphStore, student_graph, validate_graph
from learning_agent.graph_audit import audit_graph
from pliac import margin, learning_scope


class LinuxCourseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.store = CourseGraphStore(output_dir=self.base / "runtime")
        self.seed = DEST / "course.json"
        self.graph = json.loads(self.seed.read_text(encoding="utf-8"))

    def test_authored_release_reproduces_and_covers_evidence(self):
        authored, audit = build()
        self.assertEqual(self.graph, authored)
        self.assertEqual(json.loads((DEST / "term-audit.json").read_text(encoding="utf-8")), audit)
        self.assertEqual(validate_graph(self.graph)["node_count"], 46)
        self.assertEqual(len(self.graph["chapters"]), 8)
        self.assertEqual(len(self.graph["edges"]), 69)
        self.assertEqual({n["id"] for n in self.graph["nodes"]}, {d["node_id"] for d in audit["decisions"] if d["admitted"]})
        nodes = {n["id"]: n for n in self.graph["nodes"]}
        for node in nodes.values():
            self.assertEqual(node["review_status"], "draft")
            self.assertNotIn("reviewer", node)
            self.assertTrue(node["check_question"] and node["expected_answer"])
            self.assertEqual(len(node["check_task"]["hint_levels"]), 4)
            for ref in node["evidence_refs"]:
                self.assertIn(ref["source_id"], node["source_ids"])
                self.assertIn(ref["lesson_section_id"], {s["id"] for s in node["lesson_content"]})
        for edge in self.graph["edges"]:
            self.assertTrue(edge["reason"] and edge["source_ids"])
            for ref in edge["evidence_refs"]:
                self.assertIn(ref["lesson_section_id"], {s["id"] for s in nodes[ref["node_id"]]["lesson_content"]})
        issues = audit_graph(self.graph)["summary"]["issue_counts"]
        self.assertEqual(issues.get("missing_source", 0), 0)
        self.assertEqual(issues.get("name_collision", 0), 0)
        self.assertEqual(issues.get("source_locator_missing", 0), 0)

    def test_install_is_idempotent_and_keeps_changed_drafts_and_records(self):
        first = install(self.seed, self.store)
        self.assertTrue(first["installed"])
        self.assertFalse(install(self.seed, self.store)["installed"])
        course = resolve_course(self.store, COURSE_ID)
        marker = course.output_dir / "learners" / "preserve-sentinel.txt"
        marker.parent.mkdir()
        marker.write_text("existing evidence must survive", encoding="utf-8")
        modified = copy.deepcopy(self.graph)
        modified["nodes"][0]["description"] += " 教师尚未审核的本地补充。"
        course.save_graph(modified, 1)
        before = course.graph_path.read_bytes()
        with self.assertRaisesRegex(CourseGraphError, "不会覆盖"):
            install(self.seed, self.store)
        self.assertEqual(course.graph_path.read_bytes(), before)
        self.assertEqual(marker.read_text(encoding="utf-8"), "existing evidence must survive")
        self.assertFalse(self.store.graph_path.exists())

    def test_course_stays_editable_unpublished_and_has_no_learner_inference(self):
        result = install(self.seed, self.store)
        course = resolve_course(self.store, COURSE_ID)
        self.assertTrue(result["course"]["capabilities"]["edit"])
        self.assertFalse(result["course"]["capabilities"]["learn"])
        self.assertFalse(result["course"]["capabilities"]["objective_assessment"])
        self.assertEqual(len([c for c in list_courses(self.store) if c["id"] == COURSE_ID]), 1)
        self.assertIsNone(course.load_graph("published"))
        with self.assertRaisesRegex(CourseGraphError, "未人工审核"):
            course.publish(1, "synthetic-test", "must fail")
        self.assertFalse((course.output_dir / "publication.json").exists())
        self.assertFalse((course.output_dir / "learners").exists())
        public = json.dumps(student_graph(self.graph), ensure_ascii=False)
        for key in ("expected_answer", "rubric", "hint_levels"):
            self.assertNotIn('"' + key + '"', public)

    def test_related_and_confusable_edges_do_not_become_prerequisites(self):
        install(self.seed, self.store)
        course = resolve_course(self.store, COURSE_ID)
        path = course.learning_path("grep", view="draft")
        ids = {s["node_id"] for s in path["steps"]}
        self.assertIn("quoting", ids)
        self.assertNotIn("find", ids)
        self.assertNotIn("pipe", ids)

    def test_linked_teaching_materials_are_scoped_without_fake_uploaded_sources(self):
        install(self.seed, self.store)
        course = resolve_course(self.store, COURSE_ID)
        scope = learning_scope.resolve(self.graph, {"node_id": "grep"}, margin.storage(course))
        docs, origins = margin.materials(self.graph, scope=scope)
        self.assertEqual(len(docs), 1)
        self.assertEqual(len(docs[0].units), 1)
        self.assertIn("grep 文本筛选", docs[0].units[0].text)
        self.assertNotIn("chmod 640", docs[0].units[0].text)
        self.assertFalse(origins)
        self.assertEqual(scope["node_ids"], ["grep"])


if __name__ == "__main__":
    unittest.main()
