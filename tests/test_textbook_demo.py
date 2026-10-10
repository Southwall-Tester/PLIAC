"""Portable real-source fixture; all learner mutations use temporary stores."""
import gzip
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
import uuid
import zipfile

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"src"))
from learning_agent.course_catalog import list_courses, resolve_course
from learning_agent.course_graph import CourseGraphStore, CourseGraphError, validate_graph
from learning_agent.textbook_demo import ASSETS, DEMO_ID, manifest
from pliac.workspace import LearningWorkspace


class TextbookDemoTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.default=CourseGraphStore(output_dir=Path(self.tmp.name)/"records")
        self.store=resolve_course(self.default,DEMO_ID)

    def test_snapshot_and_evidence_are_lossless_and_explicit(self):
        info=manifest()
        packed=(ASSETS/"source-snapshot.json.gz").read_bytes()
        self.assertEqual(hashlib.sha256(packed).hexdigest(),info["snapshot_sha256"])
        snapshot=json.loads(gzip.decompress(packed))
        raw=snapshot["graph"]
        self.assertEqual((len(raw["nodes"]),len(raw["edges"])),(500,2000))
        self.assertEqual(sum(e["type"]=="cooccurs" for e in raw["edges"]),1998)
        pages={p["page"]:p["text"] for p in snapshot["pages"]}
        self.assertEqual(len(pages),513)
        for item in raw["nodes"]+raw["edges"]:
            for evidence in item["evidence"]:
                self.assertIn(evidence["quote"],pages[evidence["page"]])

    def test_course_is_not_a_reviewed_publication(self):
        graph=self.store.load_graph()
        validate_graph(graph)
        self.assertEqual(graph["delivery_mode"],"source_demo")
        self.assertEqual(graph["edges"],[])
        self.assertTrue(all(n["review_status"]=="draft" for n in graph["nodes"]))
        self.assertIsNone(self.store.publication()["published_version"])
        self.assertIsNone(self.store.assessment)
        with self.assertRaises(CourseGraphError): self.store.publish()
        with self.assertRaises(CourseGraphError): self.store.save_graph(graph,1)
        course=next(c for c in list_courses(self.default) if c["id"]==DEMO_ID)
        self.assertEqual(course["source_summary"]["candidate_nodes"],500)

    def test_portable_install_is_idempotent_and_does_not_replace_records(self):
        folder=self.store.ensure_handouts()
        sentinel=self.store.output_dir/"learner-sentinel.json"
        sentinel.write_text('{"preserve":true}',encoding="utf-8")
        before=sentinel.read_bytes()
        self.assertEqual(self.store.ensure_handouts(),folder)
        self.assertEqual(sentinel.read_bytes(),before)
        for job in manifest()["jobs"]:
            directory=folder/"jobs"/job["id"]
            graph=json.loads((directory/"knowledge-map.json").read_text(encoding="utf-8"))
            lesson=json.loads((directory/"lesson.json").read_text(encoding="utf-8"))
            self.assertEqual(len(graph["nodes"]),job["candidate_nodes"])
            self.assertTrue(all(e["directed"] is False for e in graph["edges"] if e["relation_type"]=="cooccurs"))
            self.assertTrue((directory/"lesson.pdf").is_file())
            if job["chapter_id"]:
                self.assertEqual([s["id"] for s in lesson["sections"]],[job["chapter_id"]])

    def test_answers_are_raw_evidence_not_auto_mastery(self):
        workspace=LearningWorkspace(self.store)
        def payload(**extra):
            return dict(student_id="synthetic-source-demo",course_version=1,
                expected_version=self.store.load_learner("synthetic-source-demo")["version"],
                request_id=uuid.uuid4().hex,**extra)
        workspace.onboard(payload(goals="Synthetic test",self_assessments={"chapter_1":"new"}))
        started=workspace.next_lesson(payload(node_id="chapter_1"))
        lesson=started["current_lesson"]
        self.assertIn("CPU",lesson["paragraphs"][0]["text"])
        answered=workspace.answer(payload(lesson_id=lesson["id"],text="Synthetic answer: 1.5 times, multiple factors."))
        self.assertEqual(answered["learner"]["diagnoses"],[])
        self.assertNotEqual(answered["learner"]["states"]["chapter_1"]["status"],"mastered")
        self.assertTrue(any(e["text"].startswith("Synthetic answer") for e in answered["learner"]["evidence"]))


if __name__=="__main__":unittest.main()
