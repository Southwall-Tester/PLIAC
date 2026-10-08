"""Read-only graph audit tests with synthetic course assets."""
import copy
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from learning_agent.graph_audit import audit_graph, normalize_name


def graph():
    return {
        "nodes": [
            {"id": "a", "title": "训练集", "aliases": ["Training Set"], "source_ids": ["s"], "review_status": "draft"},
            {"id": "b", "title": "验证集", "aliases": ["Validation Set"], "source_ids": ["s"], "review_status": "draft"},
            {"id": "c", "title": "测试集", "aliases": ["Test Set"], "source_ids": ["s"], "review_status": "draft"},
        ],
        "edges": [
            {"id": "ab", "source": "a", "target": "b", "type": "prerequisite", "reason": "合成编排", "source_ids": ["s"]},
            {"id": "bc", "source": "b", "target": "c", "type": "prerequisite", "reason": "合成编排", "source_ids": ["s"]},
        ],
        "sources": [{"id": "s", "title": "合成来源", "url": "https://example.test", "locator": "第 1 节"}],
        "resources": [],
    }


class GraphAuditTests(unittest.TestCase):
    def findings(self, data, code):
        return [i for i in audit_graph(data)["issues"] if i["code"] == code]

    def test_typographic_normalization_preserves_semantic_distinctions(self):
        self.assertEqual(normalize_name("  Ｆ１\t Score\n"), "f1 score")
        self.assertNotEqual(normalize_name("F-1"), normalize_name("F1"))
        self.assertNotEqual(normalize_name("precision"), normalize_name("recall"))

    def test_cross_node_collision_retains_both_candidates(self):
        data = graph(); data["nodes"][1]["aliases"].append(" training　set ")
        result = self.findings(data, "name_collision")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["node_ids"], ["a", "b"])
        self.assertEqual(result[0]["details"]["normalized_name"], "training set")

    def test_same_node_duplicate_is_not_cross_node_collision(self):
        data = graph(); data["nodes"][0]["aliases"].extend(["训练集", "TRAINING SET"])
        self.assertEqual(len(self.findings(data, "duplicate_name_within_node")), 2)
        self.assertFalse(self.findings(data, "name_collision"))

    def test_no_fuzzy_merge_for_similar_concepts(self):
        data = graph(); data["nodes"][1].update(title="训练误差", aliases=["Training Error"])
        self.assertFalse(self.findings(data, "name_collision"))
        self.assertEqual(audit_graph(data)["summary"]["automatic_changes"], 0)

    def test_missing_and_unknown_sources_produce_review_prompts(self):
        data = graph(); data["nodes"][0]["source_ids"] = []; data["edges"][0]["source_ids"] = ["missing"]
        found = self.findings(data, "missing_source")
        self.assertEqual(len(found), 2)
        self.assertEqual(found[0]["node_ids"], ["a"])
        self.assertEqual(found[1]["source_ids"], ["missing"])
        self.assertTrue(all(f["severity"] == "notice" for f in found))

    def test_source_locators_accept_text_or_structured_locations(self):
        data = graph(); data["sources"][0]["locator"] = {"chapter": "", "pdf_pages": [18]}
        self.assertFalse(self.findings(data, "source_locator_missing"))
        data["sources"][0]["locator"] = {"chapter": "  ", "pdf_pages": []}
        self.assertEqual(len(self.findings(data, "source_locator_missing")), 1)
        del data["sources"][0]["locator"]
        self.assertEqual(audit_graph(data)["summary"]["sources_without_locator_count"], 1)

    def test_transitive_prerequisite_keeps_direct_edge_and_reports_route(self):
        data = graph(); data["edges"].append({"id": "ac", "source": "a", "target": "c", "type": "prerequisite", "reason": "直接依赖", "source_ids": ["s"]})
        found = self.findings(data, "transitive_prerequisite")
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["edge_ids"], ["ac", "ab", "bc"])
        self.assertEqual(found[0]["details"]["alternative_path"], ["a", "b", "c"])
        self.assertEqual(len(data["edges"]), 3)

    def test_non_prerequisite_edges_cannot_create_transitive_order(self):
        data = graph(); data["edges"][1]["type"] = "related"
        data["edges"].append({"id": "ac", "source": "a", "target": "c", "type": "prerequisite", "reason": "合成", "source_ids": ["s"]})
        self.assertFalse(self.findings(data, "transitive_prerequisite"))

    def test_isolated_is_optional_advice_and_missing_reason_is_visible(self):
        data = graph(); data["edges"] = data["edges"][:1]; data["edges"][0]["reason"] = " "
        self.assertEqual(self.findings(data, "isolated_node")[0]["node_ids"], ["c"])
        self.assertEqual(self.findings(data, "relation_reason_missing")[0]["edge_ids"], ["ab"])

    def test_relation_schema_only_prerequisite_constrains_order(self):
        schema = {r["type"]: r for r in audit_graph(graph())["relation_schema"]}
        self.assertEqual({k for k, v in schema.items() if v["constrains_learning_order"]}, {"prerequisite"})
        self.assertEqual({k for k, v in schema.items() if v["directed"]}, {"prerequisite", "contains"})

    def test_input_and_followup_audits_cannot_be_mutated_via_result(self):
        data = graph(); original = copy.deepcopy(data)
        result = audit_graph(data)
        self.assertEqual(data, original)
        result["sources"][0]["locator"] = "changed"
        result["book_references"][0]["pdf_pages"].append(999)
        result["relation_schema"][0]["meaning"] = "changed"
        later = audit_graph(data)
        self.assertEqual(data, original)
        self.assertNotIn(999, later["book_references"][0]["pdf_pages"])
        self.assertNotEqual(later["relation_schema"][0]["meaning"], "changed")

    def test_current_seed_summary_without_runtime_writes(self):
        seed = ROOT / "data" / "courses" / "ml_classification.json"
        before = seed.read_bytes(); data = json.loads(before)
        result = audit_graph(data)
        self.assertEqual(result["summary"]["node_count"], 40)
        self.assertEqual(result["summary"]["edge_count"], 68)
        self.assertEqual(result["summary"]["missing_source_count"], 0)
        self.assertEqual(sum(result["summary"]["relation_counts"].values()), 68)
        self.assertEqual(seed.read_bytes(), before)
        self.assertTrue(result["summary"]["read_only"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
