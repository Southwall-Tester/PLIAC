"""Behavioral contracts for the v7 resource recommender, using synthetic assets."""

import copy
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from learning_agent.recommendation import RULE_VERSION, recommend_resources


def resource(ident, node_ids, *, prereqs=(), review="reviewed", kind="lesson", segment=None, url=None):
    return {"id": ident, "title": ident, "node_ids": list(node_ids),
            "prerequisite_ids": list(prereqs), "review_status": review, "format": kind,
            "applicable_segment": segment or ident, "url": url or "https://example.test/" + ident}


def fixture():
    return {"nodes": [{"id": ident, "title": ident.upper()} for ident in "abcdx"],
            "edges": [{"source": "a", "target": "c", "type": "prerequisite"},
                      {"source": "b", "target": "c", "type": "prerequisite"},
                      {"source": "c", "target": "d", "type": "prerequisite"},
                      {"source": "x", "target": "a", "type": "confusable"},
                      {"source": "x", "target": "d", "type": "related"},
                      {"source": "x", "target": "d", "type": "contains"}],
            "resources": [resource("ra", "a"), resource("rb", "b"), resource("rc", "c"), resource("rd", "d")]}


class RecommendationTests(unittest.TestCase):
    def test_only_actionable_frontier_not_all_ancestors(self):
        result = recommend_resources(fixture(), {}, "d")
        self.assertEqual(result["frontier_node_ids"], ["a", "b"])
        self.assertEqual(result["pending_node_ids"], list("abcd"))
        self.assertEqual([r["id"] for r in result["resources"]], ["ra", "rb"])
        self.assertNotIn("x", result["pending_node_ids"])

    def test_frontier_moves_when_prerequisites_are_mastered(self):
        result = recommend_resources(fixture(), {n: {"status": "mastered"} for n in "ab"}, "d")
        self.assertEqual(result["frontier_node_ids"], ["c"])
        self.assertEqual([r["id"] for r in result["resources"]], ["rc"])

    def test_mastered_target_does_not_need_more_remediation(self):
        result = recommend_resources(fixture(), {"d": {"status": "mastered"}}, "d")
        self.assertEqual(result["pending_node_ids"], [])
        self.assertEqual(result["resources"], [])

    def test_due_and_missing_states_cannot_satisfy_prerequisites(self):
        result = recommend_resources(fixture(), {"a": {"status": "mastered", "due": True},
                                                "b": {"status": "mastered"}}, "c")
        self.assertEqual(result["frontier_node_ids"], ["a"])
        self.assertEqual([r["id"] for r in result["resources"]], ["ra"])

    def test_review_and_resource_prerequisites_are_hard_filters(self):
        graph = fixture()
        graph["resources"] = [resource("draft", "a", review="draft"),
                              resource("blocked", "a", prereqs="x"), resource("ok", "a")]
        result = recommend_resources(graph, {}, "d")
        self.assertEqual([r["id"] for r in result["resources"]], ["ok"])
        exclusions = {r["resource_id"]: r for r in result["excluded_resources"]}
        self.assertIn("not_reviewed", exclusions["draft"]["reason_codes"])
        self.assertIn("unmet_resource_prerequisites", exclusions["blocked"]["reason_codes"])

    def test_new_node_coverage_then_format_diversity(self):
        graph = fixture()
        graph["resources"] = [resource("z-both", "ab"), resource("a-repeat", "a"),
                              resource("b-video", "b", kind="video")]
        result = recommend_resources(graph, {}, "d")
        self.assertEqual([r["id"] for r in result["resources"]], ["z-both", "b-video", "a-repeat"])
        self.assertEqual(result["resources"][0]["matched_node_ids"], ["a", "b"])
        self.assertEqual(result["resources"][0]["recommendation_node_id"], "a")

    def test_duplicate_url_and_segment_removed_but_distinct_segments_preserved(self):
        graph = fixture()
        graph["resources"] = [resource("a", "a", url="https://example.test/course", segment="part 1"),
                              resource("b", "a", url="https://example.test/course", segment=" part  1 "),
                              resource("c", "a", url="https://example.test/course", segment="part 2")]
        result = recommend_resources(graph, {}, "a")
        self.assertEqual([r["id"] for r in result["resources"]], ["a", "c"])
        self.assertEqual(result["excluded_resources"][0]["duplicate_of"], "a")

    def test_deterministic_capped_and_trace_is_explanatory(self):
        graph = fixture()
        graph["resources"] = [resource("r" + str(i), "a") for i in range(7)]
        original = recommend_resources(graph, {}, "a")
        graph["resources"].reverse()
        again = recommend_resources(graph, {}, "a")
        self.assertEqual(original, again)
        self.assertEqual(len(original["resources"]), 4)
        self.assertEqual(original["rule_version"], RULE_VERSION)
        self.assertFalse(original["selection_trace"]["model_trained"])
        self.assertEqual(original["selection_trace"]["mastery_effect"], "none")
        self.assertTrue(all(item["reason"] for item in original["resources"]))

    def test_empty_urls_keep_distinct_local_assets(self):
        graph = fixture()
        graph["resources"] = [resource("local-a", "a", segment="part 1"),
                              resource("local-b", "a", segment="part 1")]
        for asset in graph["resources"]:
            asset["url"] = ""
        result = recommend_resources(graph, {}, "a")
        self.assertEqual([r["id"] for r in result["resources"]], ["local-a", "local-b"])
        limited = recommend_resources(graph, {}, "a", limit=1)
        self.assertIn("最多 1 项", limited["excluded_resources"][0]["reason"])

    def test_no_assets_or_state_mutation_and_no_feedback_scoring(self):
        graph, states = fixture(), {"a": {"status": "unseen", "clicks": 10000, "interest": "ML"}}
        graph_before, states_before = copy.deepcopy(graph), copy.deepcopy(states)
        result = recommend_resources(graph, states, "d")
        self.assertEqual(result, recommend_resources(graph, {}, "d"))
        result["resources"][0]["node_ids"].append("x")
        self.assertEqual(graph, graph_before)
        self.assertEqual(states, states_before)

    def test_empty_eligible_set_does_not_fabricate_resources(self):
        graph = fixture()
        for asset in graph["resources"]:
            asset["review_status"] = "draft"
        result = recommend_resources(graph, {}, "d")
        self.assertEqual(result["resources"], [])
        self.assertEqual(result["selection_trace"]["eligible_count"], 0)

    def test_invalid_target_and_limit(self):
        with self.assertRaises(ValueError):
            recommend_resources(fixture(), {}, "missing")
        for limit in [0, 5, True, 1.5]:
            with self.subTest(limit=limit), self.assertRaises(ValueError):
                recommend_resources(fixture(), {}, "d", limit=limit)


if __name__ == "__main__":
    unittest.main(verbosity=2)
