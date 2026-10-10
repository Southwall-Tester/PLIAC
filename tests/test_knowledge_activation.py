"""Automatic activation contracts with synthetic sources, never human approval."""
import copy
import json
import tempfile
import unittest
from pathlib import Path

from test_course_graph import fixture
from learning_agent.course_graph import CourseGraphError, CourseGraphStore
from pliac.knowledge_activation import activation_context, KnowledgeAudit, activate_snapshot, validate_audit


class ActivationTests(unittest.TestCase):
    def test_imported_relationship_and_resource_use_their_own_document_pages(self):
        from unittest.mock import Mock
        graph = copy.deepcopy(self.graph)
        graph['sources'].append({'id': 'uploaded', 'title': '合成上传资料', 'kind': 'uploaded_document', 'url': ''})
        edge, resource = graph['edges'][0], graph['resources'][0]
        edge.update(source_ids=['uploaded'], document_id='synthetic', document_evidence=[{'page': 3}])
        resource.update(source_ids=['uploaded'], document_id='synthetic', document_evidence=[{'page': 4}])
        documents = Mock()
        documents.page.side_effect = lambda ident, page: {'text': f'Synthetic page {page}'}
        context = activation_context(graph, documents)
        records = {item['key']: item for item in context['items']}
        edge_key, resource_key = 'edges:' + edge['id'], 'resources:' + resource['id']
        self.assertEqual(records[edge_key]['allowed_sources'], ['document:synthetic:3'])
        self.assertEqual(records[resource_key]['allowed_sources'], ['document:synthetic:4'])
        texts = {item['id']: item['text'] for item in context['sources']}
        audit = KnowledgeAudit(checks=[{'key': item['key'], 'outcome': 'supported', 'reason': '合成验证',
            'citations': [{'source_id': item['allowed_sources'][0], 'quote': texts[item['allowed_sources'][0]]}]} for item in context['items']])
        validate_audit(audit, context)
        check = next(item for item in audit.checks if item.key == edge_key)
        check.citations[0].source_id = 'document:synthetic:4'
        check.citations[0].quote = texts['document:synthetic:4']
        with self.assertRaises(CourseGraphError):
            validate_audit(audit, context)

    def test_relationship_without_own_evidence_cannot_borrow_endpoint_pages(self):
        from unittest.mock import Mock
        graph = copy.deepcopy(self.graph)
        graph['sources'].append({'id': 'uploaded', 'title': '合成资料', 'kind': 'uploaded_document', 'url': ''})
        for node in graph['nodes']:
            node.update(document_id='synthetic', document_evidence=[{'page': 1}])
        graph['edges'][0].update(source_ids=['uploaded'], document_id='synthetic', document_evidence=[])
        documents = Mock()
        documents.page.return_value = {'text': 'Synthetic endpoint definitions, not relationship evidence'}
        with self.assertRaises(CourseGraphError):
            activation_context(graph, documents)

    def test_node_cannot_borrow_unlinked_pages_from_same_document(self):
        from unittest.mock import Mock
        graph = copy.deepcopy(self.graph)
        graph["nodes"][0].update(document_id="synthetic", document_evidence=[{"page": 1}])
        graph["nodes"][1].update(document_id="synthetic", document_evidence=[{"page": 2}])
        documents = Mock()
        documents.page.side_effect = lambda ident, page: {"text": f"Synthetic page {page}"}
        context = activation_context(graph, documents)
        first = next(item for item in context["items"] if item["key"] == "nodes:" + graph["nodes"][0]["id"])
        self.assertIn("document:synthetic:1", first["allowed_sources"])
        self.assertNotIn("document:synthetic:2", first["allowed_sources"])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)
        self.graph = fixture()
        self.graph["sources"][0]["text"] = "合成来源正文：用于测试引用，不证明学科知识正确。"
        self.graph["resources"][0]["source_ids"] = ["book"]
        seed = self.path / "seed.json"
        seed.write_text(json.dumps(self.graph), encoding="utf-8")
        self.store = CourseGraphStore(seed, self.path / "output")
        self.context = activation_context(self.graph)
        self.audit = KnowledgeAudit(checks=[{"key": item["key"], "outcome": "supported", "reason": "合成模型结果", "citations": [{"source_id": "book", "quote": "合成来源正文"}]} for item in self.context["items"]])

    def test_activate_without_human_review_and_preserve_snapshot(self):
        result = activate_snapshot(self.store, self.graph, self.context, self.audit, {"model": "synthetic"})
        self.assertEqual(result["activation_mode"], "automatic")
        published = self.store.load_graph()
        self.assertEqual(published["nodes"][0]["review_status"], "auto_validated")
        self.assertNotIn("reviewer", published["nodes"][0])
        self.assertEqual(self.store.load_graph("draft"), self.graph)
        before = (self.store.output_dir / "published/v1.json").read_bytes()
        activate_snapshot(self.store, self.graph, self.context, self.audit, {"model": "synthetic"})
        self.assertEqual(before, (self.store.output_dir / "published/v1.json").read_bytes())

    def test_video_segment_changes_invalidate_automatic_content_digest(self):
        from learning_agent.course_graph import validate_graph
        graph = copy.deepcopy(self.graph)
        graph['resources'][0].update(format='video', video_segment={'start_seconds': 10, 'end_seconds': 30})
        saved = self.store.save_graph(graph, graph['version'])['graph']
        context = activation_context(saved)
        resource = next(item for item in context['items'] if item['key'].startswith('resources:'))
        self.assertIn('video_segment', str(resource))
        activate_snapshot(self.store, saved, context, self.audit, {'model': 'synthetic'})
        published = self.store.load_graph()
        self.assertEqual(published['resources'][0]['review_status'], 'auto_validated')
        altered = copy.deepcopy(published)
        altered['resources'][0]['video_segment']['end_seconds'] = 40
        with self.assertRaises(CourseGraphError):
            validate_graph(altered)
        self.assertEqual(self.store.load_graph()['resources'][0]['video_segment']['end_seconds'], 30)

    def test_missing_sources_or_false_citations_block(self):
        graph = copy.deepcopy(self.graph)
        graph["sources"][0].pop("text")
        with self.assertRaises(CourseGraphError):
            activation_context(graph)
        self.audit.checks[0].citations[0].quote = "不存在的证据"
        with self.assertRaises(CourseGraphError):
            activate_snapshot(self.store, self.graph, self.context, self.audit, {})
        self.assertIsNone(self.store.load_graph())

    def test_uncertain_or_incomplete_audit_blocks(self):
        self.audit.checks[0].outcome = "uncertain"
        with self.assertRaises(CourseGraphError):
            validate_audit(self.audit, self.context)
        self.audit.checks.pop(0)
        with self.assertRaises(CourseGraphError):
            validate_audit(self.audit, self.context)

    def test_stale_validation_cannot_activate_changed_draft(self):
        updated = copy.deepcopy(self.graph)
        updated["nodes"][0]["description"] = "修订后的概念"
        self.store.save_graph(updated, 1)
        with self.assertRaises(CourseGraphError):
            activate_snapshot(self.store, self.graph, self.context, self.audit, {})
        self.assertIsNone(self.store.load_graph())

    def test_client_cannot_grant_automatic_status_and_old_version_survives(self):
        activate_snapshot(self.store, self.graph, self.context, self.audit, {})
        graph = self.store.load_graph()
        graph["nodes"][0]["description"] = "新版本解释"
        saved = self.store.save_graph(graph, 1)["graph"]
        self.assertTrue(all(node["review_status"] == "draft" for node in saved["nodes"]))
        self.assertNotIn("automatic_validation", saved["nodes"][0])
        self.assertEqual(self.store.load_graph()["nodes"][0]["description"], "概念说明")


if __name__ == "__main__":
    unittest.main()
