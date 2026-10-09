"""Planning regression cases: variable workloads, intact boundaries and no timer."""
import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from pliac.rhythm import estimate, plan_pauses, lab_rhythm, profiles, fingerprint
from pliac.ml_contract import TASKS


def blocks(*minutes):
    return [{"id": str(i), "after": {"boundary": str(i)}, "resume": "接着学习。",
             "load": {"minutes": m, "rationale": "完整概念、例题或练习组。"}} for i, m in enumerate(minutes)]


class RhythmTests(unittest.TestCase):
    def test_short_sections_accumulate_and_tail_is_not_forced(self):
        result = plan_pauses(blocks(5, 5, 5, 5, 5, 5))
        self.assertEqual([(p["id"], p["estimated_minutes"]) for p in result], [("4", 25)])
        self.assertEqual(plan_pauses(blocks(10, 8)), [])

    def test_nearest_boundary_on_either_side_and_indivisible_work(self):
        self.assertEqual(plan_pauses(blocks(19, 16))[0]["id"], "0")
        self.assertEqual(plan_pauses(blocks(20, 6))[0]["id"], "1")
        self.assertEqual(plan_pauses(blocks(20, 10))[0]["id"], "0")
        self.assertEqual(plan_pauses(blocks(3, 45))[0]["estimated_minutes"], 48)

    def test_unknown_or_invalid_load_is_not_counted_as_learning_time(self):
        for value in [float("nan"), float("inf"), -2, True]:
            self.assertIsNone(estimate({"minutes": value, "rationale": "estimate"}))
        items = blocks(12, 12, 12)
        items[1]["load"] = None
        self.assertEqual(plan_pauses(items), [])
        self.assertIsNone(estimate({"units": {"pages": 25}, "rationale": "length"}))

    def test_task_changes_move_breaks_instead_of_binding_to_step_number(self):
        def rhythm(loads):
            tasks = [{"id": f"t{i}", "title": f"Task {i}", "study_load": {"minutes": n, "rationale": "semantic work"}}
                     for i, n in enumerate(loads)]
            session = {"id": "same-session", "step": 0, "checks": []}
            return lab_rhythm(tasks, session, {}, {})
        first = rhythm([6, 5, 10, 11, 8])
        second = rhythm([12, 13, 5, 5, 3])
        self.assertEqual(first["plan"][0]["after"]["step"], 3)
        self.assertEqual(second["plan"][0]["after"]["step"], 2)
        self.assertEqual(rhythm([1, 2, 2, 1, 2])["plan"], [])

    def test_dismissal_resets_accumulation_and_survives_reload(self):
        session = {"id": "lab", "step": 3, "checks": []}
        initial = lab_rhythm(TASKS, session, {})
        self.assertIsNotNone(initial["current"])
        point = initial["current"]
        workspace = {"rhythm_marks": {point["id"]: {"choice": "continue", "plan": point}}}
        again = lab_rhythm(TASKS, session, workspace)
        self.assertIsNone(again["current"])
        self.assertNotIn(point["id"], {p["id"] for p in again["plan"]})

    def test_checks_adjust_load_but_not_mastery_or_clock(self):
        session = {"id": "lab", "step": 2, "checks": []}
        before = lab_rhythm(TASKS, session, {})
        session["checks"] = [{"task_id": "inspect", "passed": False}] * 9
        after = lab_rhythm(TASKS, session, {})
        self.assertEqual(after["blocks"][0]["minutes"] - before["blocks"][0]["minutes"], 3)
        self.assertEqual(session["step"], 2)
        changed = copy.deepcopy(TASKS)
        changed[0]["goal"] = "New work requiring refreshed estimates"
        self.assertIsNone(lab_rhythm(changed, session, {})["blocks"][0]["minutes"])

    def test_current_task_contracts_have_matching_load_provenance(self):
        data = profiles()["lab"]
        for task in TASKS:
            self.assertEqual(data[task["id"]]["content_fingerprint"], fingerprint(task))
            self.assertGreater(estimate(data[task["id"]]["load"]), 0)


if __name__ == "__main__":
    unittest.main()
