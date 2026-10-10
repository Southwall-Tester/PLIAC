"""Synthetic source retrieval verifies scope/provenance, not teaching quality."""
import unittest
from unittest.mock import Mock
from test_learning_workspace import platform_fixture
from pliac.retrieval import retrieve_sources
from learning_agent.course_graph import CourseGraphError


class RetrievalTests(unittest.TestCase):
    def test_linked_pages_keep_original_location_and_exclude_unlinked_sources(self):
        graph = platform_fixture()
        node = graph["nodes"][0]
        node.update(document_id="synthetic_document", document_evidence=[{"page": 3}])
        documents = Mock()
        documents.status.return_value = {"title": "Synthetic text", "page_kind": "pdf"}
        documents.page.return_value = {"text": "原文限定：编号不一定有泛化意义。"}
        sources = retrieve_sources(graph, [node], "泛化", documents)
        self.assertEqual(len(sources), 1)
        self.assertEqual(sources[0]["text"], documents.page.return_value["text"])
        self.assertEqual(sources[0]["page"], 3)
        self.assertEqual(sources[0]["origin"], "uploaded_document")
        self.assertTrue(sources[0]["url"].endswith("#page=3"))
        self.assertEqual(len(sources[0]["content_digest"]), 64)
        documents.page.assert_called_once_with("synthetic_document", 3)
        self.assertNotIn("TEACHER_ONLY", str(sources))

    def test_empty_linked_page_does_not_silently_substitute_generated_definition(self):
        graph = platform_fixture()
        node = graph["nodes"][0]
        node.update(document_id="synthetic_document", document_evidence=[{"page": 1}])
        documents = Mock()
        documents.status.return_value = {"title": "Synthetic"}
        documents.page.return_value = {"text": " "}
        with self.assertRaises(CourseGraphError):
            retrieve_sources(graph, [node], "question", documents)

    def test_bounded_chunks_preserve_verbatim_offsets(self):
        graph = platform_fixture()
        node = graph["nodes"][0]
        text = "普通内容。" * 2000 + "独立测试 泛化 核心问题" + "普通内容。" * 20000
        graph["sources"][0]["text"] = text
        sources = retrieve_sources(graph, [node], "独立测试 泛化 核心问题")
        self.assertLessEqual(len(sources), 16)
        original = [item for item in sources if item["origin"] == "course_source"]
        self.assertTrue(any("核心问题" in item["text"] for item in original))
        for item in original:
            self.assertEqual(text[item["char_start"]:item["char_end"]], item["text"])
