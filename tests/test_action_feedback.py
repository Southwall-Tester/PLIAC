"""Synthetic action-feedback contracts; all records stay in temporary folders.

Run: python -X utf8 tests/test_action_feedback.py
"""

import copy
import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from learning_agent.course_graph import CourseGraphError, CourseGraphStore
from test_course_graph import fixture


class ActionFeedbackTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.seed = self.base / "seed.json"
        self.seed.write_text(json.dumps(fixture(), ensure_ascii=False), encoding="utf-8")
        self.now = datetime(2026, 10, 8, tzinfo=timezone.utc)
        self.store = CourseGraphStore(self.seed, self.base / "records", clock=lambda: self.now)
        self.publish()

    def publish(self, graph=None):
        graph = copy.deepcopy(graph or self.store.load_graph("draft"))
        for item in [*graph["nodes"], *graph["edges"], *graph["resources"]]:
            item.update(review_status="reviewed", reviewer="Synthetic reviewer",
                        reviewed_at=self.now.isoformat(), review_note=f"Synthetic review {graph['version']}")
        graph = self.store.save_graph(graph, graph["version"])["graph"]
        self.store.publish(graph["version"], "Synthetic publisher", "Synthetic publication")
        return graph

    def action(self, node="a", student="s1"):
        return self.store.recommendations(node, student)["actions"][0]

    def evidence(self, node="a", student="s1", **changes):
        payload = {"student_id": student, "node_id": node,
                   "course_version": self.store.load_graph()["version"],
                   "source_type": "quiz", "origin": "learner_expression", "prompt_level": 0,
                   "text": "Synthetic independent task answer",
                   "context": {"task_id": "task1", "task_version": 1, "turn_id": 1}}
        payload.update(changes)
        return self.store.add_evidence(payload)["evidence"]

    def diagnose(self, evidence, action, status="mastered", **changes):
        payload = {"student_id": evidence["student_id"], "node_id": evidence["node_id"],
                   "course_version": evidence["course_version"], "evidence_ids": [evidence["id"]],
                   "status": status, "basis": "Synthetic reviewed observation",
                   "review_status": "reviewed", "reviewer": "Synthetic reviewer",
                   "follow_up_action_id": action["id"]}
        payload.update(changes)
        return self.store.add_diagnosis(payload)

    def history(self, action, student="s1"):
        history = self.store.recommendations(action["node_id"], student)["action_history"]
        return next(row for row in history if row["action_id"] == action["id"])

    def test_no_follow_up_stays_pending_and_resource_use_is_not_feedback(self):
        action = self.action()
        self.assertEqual(self.history(action)["outcome"], "pending")
        self.store.record_resource_use({"student_id": "s1", "node_id": "a", "resource_id": "r_a",
                                        "course_version": action["course_version"]})
        history = self.history(action)
        self.assertEqual(history["outcome"], "pending")
        self.assertEqual(history["observations"], [])
        self.assertEqual(self.store.load_learner("s1")["states"]["a"]["status"], "unknown")
        self.assertNotIn("reward", history)
        self.assertNotIn("reward", action)
        self.assertIn("不证明", history["notice"])

    def test_new_task_evidence_can_link_to_action_and_preserves_references(self):
        action = self.action()
        self.now += timedelta(seconds=1)
        evidence = self.evidence()
        diagnosis = self.diagnose(evidence, action)["diagnosis"]
        history = self.history(action)
        self.assertEqual(history["outcome"], "observed")
        self.assertEqual(history["observations"][0]["diagnosis_id"], diagnosis["id"])
        self.assertEqual(history["observations"][0]["evidence_ids"], [evidence["id"]])
        self.assertEqual(history["observations"][0]["current_status"], "mastered")
        self.assertEqual(diagnosis["follow_up_action_id"], action["id"])

    def test_same_timestamp_is_ordered_by_observed_evidence_ids(self):
        old = self.evidence()
        action = self.action()
        self.assertEqual(old["created_at"], action["created_at"])
        with self.assertRaises(CourseGraphError):
            self.diagnose(old, action)
        fresh = self.evidence(text="New independently submitted answer at same clock time")
        self.assertEqual(fresh["created_at"], action["created_at"])
        self.diagnose(fresh, action)
        self.assertEqual(self.history(action)["outcome"], "observed")

    def test_mixing_old_and_new_evidence_cannot_relabel_old_evidence_as_follow_up(self):
        old = self.evidence()
        action = self.action()
        self.now += timedelta(seconds=1)
        fresh = self.evidence()
        with self.assertRaises(CourseGraphError):
            self.diagnose(fresh, action, evidence_ids=[old["id"], fresh["id"]])
        self.assertEqual(self.history(action)["outcome"], "pending")

    def test_backward_timestamp_is_rejected_even_for_unseen_evidence(self):
        action = self.action()
        self.now -= timedelta(seconds=1)
        evidence = self.evidence()
        with self.assertRaises(CourseGraphError):
            self.diagnose(evidence, action)

    def test_cross_student_action_or_evidence_is_rejected(self):
        action = self.action(student="s1")
        other = self.evidence(student="s2")
        with self.assertRaises(CourseGraphError):
            self.diagnose(other, action)
        own = self.evidence(student="s1")
        with self.assertRaises(CourseGraphError):
            self.diagnose(own, action, evidence_ids=[other["id"]])

    def test_follow_up_must_match_action_frontier_not_an_unready_requested_target(self):
        action = self.action(node="c")
        self.assertEqual(set(action["target_node_ids"]), {"a", "b"})
        self.now += timedelta(seconds=1)
        target = self.evidence(node="c")
        with self.assertRaises(CourseGraphError):
            self.diagnose(target, action)
        precursor = self.evidence(node="a")
        self.diagnose(precursor, action)
        self.assertEqual(self.history(action)["observations"][0]["node_id"], "a")

    def test_course_version_mismatch_is_rejected_and_old_history_is_marked(self):
        action = self.action()
        graph = self.store.load_graph("draft")
        graph["nodes"][0]["description"] = "Changed synthetic concept definition"
        self.publish(graph)
        evidence = self.evidence()
        with self.assertRaises(CourseGraphError):
            self.diagnose(evidence, action)
        self.assertEqual(self.history(action)["outcome"], "version_changed")

    def test_self_assessment_annotation_technical_or_inferred_evidence_is_not_feedback(self):
        action = self.action()
        self.now += timedelta(seconds=1)
        for changes in ({"source_type": "self_assessment"}, {"source_type": "annotation"},
                        {"source_type": "technical"}, {"origin": "system_completion"},
                        {"origin": "model_inference"}):
            with self.subTest(changes=changes):
                evidence = self.evidence(**changes)
                with self.assertRaises(CourseGraphError):
                    self.diagnose(evidence, action, status="uncertain")
        self.assertEqual(self.history(action)["outcome"], "pending")

    def test_task_version_skeleton_and_human_review_are_required(self):
        action = self.action()
        self.now += timedelta(seconds=1)
        for changes in ({"context": {}},
                        {"source_type": "practice", "context": {"task_id": "t1", "task_version": 1}}):
            with self.subTest(changes=changes):
                evidence = self.evidence(**changes)
                with self.assertRaises(CourseGraphError):
                    self.diagnose(evidence, action, status="uncertain")
        evidence = self.evidence()
        with self.assertRaises(CourseGraphError):
            self.diagnose(evidence, action, status="uncertain", review_status="draft", reviewer="")
        with self.assertRaises(CourseGraphError):
            self.evidence(context={"task_id": "t1"})
        practice = self.evidence(source_type="practice", context={"task_id": "t1", "task_version": 1,
                                                                  "skeleton_id": "s1", "skeleton_version": 1})
        self.diagnose(practice, action)

    def test_conflicting_diagnoses_preserve_uncertain_current_status(self):
        action = self.action()
        self.now += timedelta(seconds=1)
        self.diagnose(self.evidence(), action, status="needs_review")
        self.now += timedelta(seconds=1)
        self.diagnose(self.evidence(), action, status="mastered")
        history = self.history(action)
        self.assertEqual(history["outcome"], "observed")
        self.assertEqual({observation["status"] for observation in history["observations"]},
                         {"needs_review", "mastered"})
        self.assertTrue(all(observation["current_status"] == "uncertain" for observation in history["observations"]))
        self.assertEqual(self.store.load_learner("s1")["states"]["a"]["status"], "uncertain")

    def test_snapshot_stays_immutable_after_feedback_and_service_reload(self):
        action = self.action()
        original_snapshot = copy.deepcopy(action["state_snapshot"])
        self.now += timedelta(seconds=1)
        self.diagnose(self.evidence(), action)
        reloaded = CourseGraphStore(self.seed, self.base / "records", clock=lambda: self.now)
        learner = reloaded.load_learner("s1")
        saved = next(record for record in learner["actions"] if record["id"] == action["id"])
        self.assertEqual(saved["state_snapshot"], original_snapshot)
        self.assertEqual(saved["state_snapshot"]["a"]["status"], "unknown")
        self.assertEqual(learner["states"]["a"]["status"], "mastered")
        self.assertEqual(saved["selection_trace"]["rule_version"], saved["policy_version"])
        self.assertFalse(saved["selection_trace"]["selection_trace"]["model_trained"])

    def test_snapshot_includes_mastered_prerequisite_that_changes_the_frontier(self):
        prerequisite_action = self.action("a")
        self.now += timedelta(seconds=1)
        evidence = self.evidence("a")
        diagnosis = self.diagnose(evidence, prerequisite_action)["diagnosis"]
        target_action = self.action("c")
        self.assertEqual(target_action["target_node_ids"], ["b"])
        self.assertIn("a", target_action["state_snapshot"],
                      "A mastered prerequisite is still an input to the frontier decision.")
        prerequisite_snapshot = target_action["state_snapshot"]["a"]
        self.assertEqual(prerequisite_snapshot["status"], "mastered")
        self.assertIn(evidence["id"], prerequisite_snapshot["evidence_ids"])
        self.assertIn(diagnosis["id"], prerequisite_snapshot["diagnosis_ids"])

    def test_snapshot_includes_resource_prerequisite_used_to_exclude_a_candidate(self):
        graph = self.store.load_graph("draft")
        graph["resources"][0]["prerequisite_ids"] = ["d"]
        self.publish(graph)
        action = self.action("a")
        self.assertEqual(action["resource_ids"], [])
        exclusion = next(row for row in action["selection_trace"]["excluded_resources"]
                         if row["resource_id"] == "r_a")
        self.assertIn("d", exclusion["missing_prerequisite_ids"])
        self.assertIn("d", action["state_snapshot"],
                      "A resource prerequisite is an input to candidate exclusion.")
        self.assertEqual(action["state_snapshot"]["d"]["status"], "unknown")

    def test_interests_do_not_change_selection_or_create_duplicate_actions(self):
        before = self.store.recommendations("c", "s1")
        action = before["actions"][0]
        self.store.save_profile({"student_id": "s1", "interests": ["sports", "music"]})
        after = self.store.recommendations("c", "s1")
        again = self.store.recommendations("c", "s1")
        self.assertEqual(after["actions"][0]["id"], action["id"])
        self.assertEqual(again["actions"][0]["id"], action["id"])
        self.assertEqual(before["selection"], after["selection"])
        self.assertEqual(before["learner"]["states"], after["learner"]["states"])
        self.assertEqual(len(self.store.load_learner("s1")["actions"]), 1)

    def test_new_policy_version_or_new_relevant_evidence_creates_new_decision(self):
        initial = self.action()
        with patch("learning_agent.recommendation.RULE_VERSION", "synthetic-policy-v2"):
            changed_policy = self.action()
            self.assertNotEqual(changed_policy["id"], initial["id"])
            self.assertEqual(changed_policy["policy_version"], "synthetic-policy-v2")
            self.assertEqual(self.action()["id"], changed_policy["id"])
            self.now += timedelta(seconds=1)
            self.evidence()
            changed_state = self.action()
            self.assertNotEqual(changed_state["id"], changed_policy["id"])
            self.assertEqual(changed_state["state_snapshot"]["a"]["status"], "uncertain")


if __name__ == "__main__":
    unittest.main(verbosity=2)
