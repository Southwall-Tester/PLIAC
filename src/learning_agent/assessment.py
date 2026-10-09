"""Objective assessment contract, independent of course identity and UI."""
import uuid
from .course_graph import _fingerprint

class ObjectiveChoiceAssessment:
    def __init__(self, store, rule_id):
        self.store = store
        self.rule_id = rule_id

    def confirms(self, diagnosis):
        return (diagnosis.get("review_status") == "rule_verified"
                and diagnosis.get("assessment_origin") == "objective_rule"
                and diagnosis.get("rule_id") == self.rule_id)

    def grade(self, graph, learner, workspace, lesson, node, record, choice):
        task = self.store.lesson_task(node, lesson)
        passed = choice == task["answer_key"]
        independent = self.store._independent(record)
        status = "mastered" if passed and independent else "uncertain" if passed else "needs_review"
        basis = ("本题独立作答通过。" if status == "mastered" else
                 "参考材料、提示或解析后答对，请换题收起讲义后复测；题目用尽时请教师补题。" if passed else
                 "先看方向提示，修改判断后再提交。")
        previous = [d for d in learner["diagnoses"] if d["node_id"] == node["id"]
                    and d.get("assessment_origin") == "objective_rule"]
        refs = [record["id"], *[e["id"] for e in learner["evidence"] if e["node_id"] == node["id"]
                               and e["source_type"] == "self_assessment"]]
        diagnosis = {"id": uuid.uuid4().hex, "student_id": learner["student_id"], "course_id": graph["id"],
            "course_version": graph["version"], "node_id": node["id"], "node_fingerprint": _fingerprint(node),
            "status": status, "basis": basis, "review_status": "rule_verified", "reviewer": "",
            "assessment_origin": "objective_rule", "rule_id": self.rule_id, "evidence_ids": refs,
            "resolves_diagnosis_ids": [d["id"] for d in previous], "created_at": self.store._stamp(), "review_stage": 0}
        if status == "mastered":
            prior = [d for d in previous if d["status"] == "mastered"]
            if lesson.get("mode") == "retest" and prior:
                diagnosis["review_stage"] = min(prior[-1].get("review_stage", 0) + 1,
                                                len(graph["review_policy"]["intervals_days"]) - 1)
            diagnosis["mastered_at"] = record["created_at"]
        learner["diagnoses"].append(diagnosis)
        # Increase support after a wrong answer without exposing the solution early.
        # The submitted evidence keeps its original assistance level.
        level = 4 if passed else min(4, lesson["prompt_level"] + 1)
        workspace["exposures"][lesson["task_key"]] = level
        lesson["prompt_level"] = level
        lesson["status"] = "assessed" if passed or level == 4 else "retry"
        explanation = task["explanation"] if level == 4 else task["hint_levels"][level - 1]
        return {"passed": passed, "choice_id": choice, "error_code": None if passed else task["error_code"],
                "feedback": basis, "explanation": explanation, "solution_revealed": level == 4, "assessment_origin": "objective_rule",
                "diagnosis_id": diagnosis["id"], "status": status}
