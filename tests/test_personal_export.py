"""Synthetic export fixtures; no live learner data or model call."""
import asyncio
import copy
import io
import threading
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from pypdf import PdfReader

import test_assessment
from learning_agent.course_graph import CourseGraphError
from pliac.main import app
from pliac.notebook import Notebook
from pliac.reports import StageReports
from pliac.personal_export import saved_snapshot, export_body, render_pdf


def sample_material():
    return {"request_id": "export-fixture", "created_at": "2026-10-10T10:00:00Z", "course_version": 2,
        "generation": {"private_metadata": "NOT_FOR_EXPORT"},
        "proposal": {"response": "本页用于核对已保存的教材导出。", "question": "为什么需要独立测试集？",
            "rationale": "先区分模型选择与最终评价。", "uncertainty": "材料不是学习效果证明。",
            "blocks": [{"heading": "泛化误差与数据划分", "text": r"训练损失 $L=\frac{1}{n}\sum_{i=1}^{n}(y_i-\hat y_i)^2$ 不等于泛化误差。" +
                "\n\n- 训练集用于拟合参数。\n- 验证集用于模型选择。\n- 测试集用于最终评价。\n\n" +
                "| 数据 | 用途 |\n|---|---|\n| 训练集 | 拟合参数 |\n| 测试集 | 最终评价 |",
                "citations": [{"source_id": "source-1", "quote": "测试集用于最终评价。"}]}]},
        "source_catalog": [{"id": "source-1", "title": "导出排版测试资料", "page": 3}]}


class ExportTests(unittest.TestCase):
    setUp = test_assessment.AssessmentTests.setUp
    payload = test_assessment.AssessmentTests.payload

    def test_report_is_read_only_snapshot_scoped_to_student(self):
        Notebook(self.store).save(self.payload(node_id="a", text="original export note"))
        report = StageReports(self.store).save(self.payload())["workspace"]["stage_reports"][-1]
        Notebook(self.store).save(self.payload(node_id="a", text="later changed note"))
        before = copy.deepcopy(self.store._read_learner("synthetic"))
        snapshot = saved_snapshot(self.store, "synthetic", "report", report["id"])
        body = export_body("report", snapshot)
        self.assertIn("original export note", body)
        self.assertNotIn("later changed note", body)
        self.assertEqual(before, self.store._read_learner("synthetic"))
        with self.assertRaises(CourseGraphError):
            saved_snapshot(self.store, "different-student", "report", report["id"])
        with self.assertRaises(CourseGraphError):
            saved_snapshot(self.store, "synthetic", "report", "../secret")

    def test_model_metadata_and_active_html_are_not_exported(self):
        sample = sample_material()
        sample["proposal"]["blocks"][0]["text"] += '\n<script>window.hacked=true</script>'
        body = export_body("material", sample)
        self.assertNotIn("NOT_FOR_EXPORT", body)
        self.assertNotIn("<script>", body)
        self.assertIn("&lt;script&gt;", body)

    def test_actual_pdf_renders_chinese_math_and_table(self):
        data = asyncio.run(render_pdf("material", sample_material()))
        reader = PdfReader(io.BytesIO(data))
        self.assertTrue(reader.pages)
        text = "".join(page.extract_text() for page in reader.pages)
        self.assertIn("泛化误差与数据划分", text)
        self.assertIn("测试集用于最终评价", text)
        self.assertNotIn(r"\frac", text)

    def test_invalid_math_fails_instead_of_silently_exporting(self):
        sample = sample_material()
        sample["proposal"]["blocks"][0]["text"] = r"$\undefinedPliacCommand{x}$"
        with self.assertRaises(CourseGraphError) as caught:
            asyncio.run(render_pdf("material", sample))
        self.assertEqual(caught.exception.status_code, 422)

    def test_actual_pdf_keeps_saved_video_segment(self):
        sample = sample_material()
        sample['proposal']['recommended_resources'] = [{'resource_id': 'v1', 'reason': '合成推荐理由'}]
        sample['resource_catalog'] = [{'id': 'v1', 'title': '合成视频', 'applicable_segment': '概念示例',
            'video_segment': {'start_seconds': 12, 'end_seconds': 50}}]
        data = asyncio.run(render_pdf('material', sample))
        text = ''.join(page.extract_text() for page in PdfReader(io.BytesIO(data)).pages)
        self.assertIn('当时推荐片段', text)
        self.assertIn('12', text)
        self.assertIn('50', text)
        self.assertIn('合成推荐理由', text)

    def test_report_download_headers_and_missing_artifact(self):
        Notebook(self.store).save(self.payload(node_id="a", text="saved report evidence"))
        report = StageReports(self.store).save(self.payload())["workspace"]["stage_reports"][-1]
        with patch("learning_agent.api.store", self.store), TestClient(app) as client:
            result = client.get("/api/tutor/export/pdf", params={"student_id": "synthetic", "kind": "report", "artifact_id": report["id"]})
            self.assertEqual(result.status_code, 200, result.text[:100] if result.status_code != 200 else "")
            self.assertEqual(result.headers["cache-control"], "no-store")
            self.assertTrue(result.content.startswith(b"%PDF"))
            self.assertEqual(client.get("/api/tutor/export/pdf", params={"student_id": "nobody", "kind": "report", "artifact_id": report["id"]}).status_code, 404)

    def test_busy_export_returns_retryable_error_without_changing_record(self):
        Notebook(self.store).save(self.payload(node_id='a', text='Keep the saved note'))
        report = StageReports(self.store).save(self.payload())['workspace']['stage_reports'][-1]
        before = self.store._read_learner('synthetic')
        slots = threading.BoundedSemaphore(1)
        slots.acquire()
        with (patch('learning_agent.api.store', self.store), patch('pliac.personal_export._PDF_SLOTS', slots),
              patch('pliac.personal_export._render_pdf') as renderer, TestClient(app) as client):
            result = client.get('/api/tutor/export/pdf', params={
                'student_id': 'synthetic', 'kind': 'report', 'artifact_id': report['id']})
            self.assertEqual(result.status_code, 429)
            self.assertIn('稍后手动重试', result.json()['detail'])
            renderer.assert_not_called()
        slots.release()
        self.assertEqual(self.store._read_learner('synthetic'), before)

    def test_textbook_uses_report_scope_and_saved_notes_without_regeneration(self):
        material = sample_material()
        material['proposal']['target_node_id'] = 'a'
        Notebook(self.store).save(self.payload(node_id='a', text='Original stage note'))
        learner = self.store._read_learner('synthetic')
        learner.setdefault('workspace', {})['tutor_turns'] = [material]
        self.store._commit(learner)
        report = StageReports(self.store).save(self.payload())['workspace']['stage_reports'][-1]
        Notebook(self.store).save(self.payload(node_id='a', text='Later note not in textbook'))
        learner = self.store._read_learner('synthetic')
        later = copy.deepcopy(material)
        later['request_id'] = 'later-material'
        later['proposal']['response'] = 'LATER_MATERIAL_NOT_INCLUDED'
        learner['workspace']['tutor_turns'].append(later)
        self.store._commit(learner)
        before = copy.deepcopy(self.store._read_learner('synthetic'))
        book = saved_snapshot(self.store, 'synthetic', 'textbook', report['id'])
        self.assertEqual([item['request_id'] for item in book['materials']], ['export-fixture'])
        self.assertNotIn('generation', book['materials'][0])
        body = export_body('textbook', book)
        self.assertIn('Original stage note', body)
        self.assertNotIn('Later note not in textbook', body)
        self.assertNotIn('LATER_MATERIAL_NOT_INCLUDED', body)
        self.assertNotIn('NOT_FOR_EXPORT', body)
        self.assertEqual(self.store._read_learner('synthetic'), before)
        with patch('learning_agent.api.store', self.store), TestClient(app) as client:
            response = client.get('/api/tutor/textbook', params={'student_id': 'synthetic', 'report_id': report['id']})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.headers['cache-control'], 'no-store')
            self.assertEqual(response.json(), book)
            self.assertEqual(client.get('/api/tutor/textbook', params={'student_id': 'different', 'report_id': report['id']}).status_code, 404)
        data = asyncio.run(render_pdf('textbook', book))
        content = ''.join(page.extract_text() for page in PdfReader(io.BytesIO(data)).pages)
        self.assertIn('个人教材汇编', content)
        self.assertIn('Original stage note', content)
        self.assertIn('泛化误差与数据划分', content)
        learner['workspace']['tutor_turns'] = [later]
        self.store._commit(learner)
        with self.assertRaises(CourseGraphError) as caught:
            saved_snapshot(self.store, 'synthetic', 'textbook', report['id'])
        self.assertEqual(caught.exception.status_code, 409)


if __name__ == "__main__":
    unittest.main()
