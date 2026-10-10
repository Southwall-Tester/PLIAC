"""Immutable reports describe evidence, not fabricated learning outcomes."""
import unittest
import copy
import test_assessment
from pliac.reports import StageReports
from pliac.notebook import Notebook
from pliac.assessment import AssessmentService
from pliac.archive import learning_archive
from learning_agent.course_graph import CourseGraphError


class ReportTests(unittest.TestCase):
    setUp = test_assessment.AssessmentTests.setUp
    payload = test_assessment.AssessmentTests.payload

    def test_empty_report_rejected(self):
        with self.assertRaises(CourseGraphError):
            StageReports(self.store).save(self.payload())

    def test_snapshot_is_idempotent_and_does_not_follow_later_note_edits(self):
        Notebook(self.store).save(self.payload(node_id="a", text="original synthetic note"))
        service = StageReports(self.store)
        request = self.payload()
        first = service.save(request)
        service.save(request)
        report = first["workspace"]["stage_reports"][0]
        self.assertEqual(report["counts"], {"unknown": 1})
        Notebook(self.store).save(self.payload(node_id="a", text="updated synthetic note"))
        current = service.view("synthetic")
        self.assertEqual(current["workspace"]["stage_reports"], [report])
        self.assertEqual(report["notes"][0]["text"], "original synthetic note")
        self.assertTrue(any(item["kind"] == "report" for item in learning_archive(self.store, "synthetic")["courses"][0]["items"]))
        self.assertEqual(current["learner"]["diagnoses"], [])

    def test_report_cites_raw_evidence_without_private_task_fields(self):
        service = AssessmentService(self.store)
        state = service.start(self.payload(node_id="a"))
        ident = state["workspace"]["assessments"][-1]["id"]
        service.submit(self.payload(assessment_id=ident, answer="synthetic answer"))
        service.save_result(self.payload(assessment_id=ident), self.proposal, {"model": "synthetic"})
        report = StageReports(self.store).save(self.payload())["workspace"]["stage_reports"][-1]
        self.assertEqual(report["diagnoses"][0]["evidence_ids"], [report["evidence"][0]["id"]])
        self.assertNotIn("TEACHER_ONLY", str(report))
        self.assertEqual(report["nodes"]["a"]["status"], "mastered")

    def test_manual_report_beyond_hundred_preserves_archive(self):
        Notebook(self.store).save(self.payload(node_id='a', text='Synthetic retained note'))
        service = StageReports(self.store)
        initial = service.save(self.payload())['workspace']['stage_reports'][0]
        learner = self.store._read_learner('synthetic')
        historical = [copy.deepcopy(initial) | {'id': f'synthetic-history-{index}'} for index in range(100)]
        learner['workspace']['stage_reports'] = copy.deepcopy(historical)
        self.store._commit(learner)
        request = self.payload()
        state = service.save(request)
        self.assertEqual(len(state['workspace']['stage_reports']), 101)
        self.assertEqual(state['workspace']['stage_reports'][:100], historical)
        self.assertEqual(service.save(request)['workspace']['stage_reports'], state['workspace']['stage_reports'])
        archived = learning_archive(self.store, 'synthetic')['courses'][0]['items']
        self.assertEqual(sum(item['kind'] == 'report' for item in archived), 101)
