"""Immutable authored acceptance course; never impersonates human publication."""
import copy
import json
import uuid

from .course_graph import ROOT, CourseGraphError, CourseGraphStore, _fingerprint, validate_graph

DEMO_ID = "ml_acceptance_demo"
NOTICE = ""


def build_graph():
    source = json.loads((ROOT / "data/acceptance_course.json").read_text(encoding="utf-8"))
    graph = {k: copy.deepcopy(source[k]) for k in ("id", "version", "title", "overview", "chapters", "sources")}
    graph.update(schema_version=1, delivery_mode="acceptance_demo", nodes=[], edges=[], resources=[],
                 review_policy={"intervals_days": [1, 7, 30]})
    for entry in source["nodes"]:
        tasks = []
        for index, question in enumerate(entry["questions"]):
            task = {**copy.deepcopy(question), "id": f"demo_{entry['id']}_{index + 1}", "version": 1,
                    "hint_levels": entry["hints"], "rubric": ["选择正确选项；独立核验要求未使用本题提示或解析。"]}
            task["options"] = [{"id": chr(65 + i), "text": text} for i, text in enumerate(question["options"])]
            tasks.append(task)
        graph["nodes"].append({"id": entry["id"], "chapter_id": entry["chapter_id"], "title": entry["title"],
            "description": entry["concept"], "objectives": [entry["objective"]], "aliases": [],
            "misconception": entry["pitfall"], "source_ids": [entry["source"]], "review_status": "draft",
            "check_question": tasks[0]["question"], "check_task": tasks[0], "retest_tasks": tasks[1:],
            "expected_answer": tasks[0]["explanation"],
            "lesson_content": [{"id": key, "heading": heading, "text": entry[key]} for key, heading in
                               (("objective", "这一节学会什么"), ("concept", "理解概念"),
                                ("example", "一起看一个例子"), ("pitfall", "容易出错的地方"))]})
    for before, after in zip(graph["nodes"], graph["nodes"][1:]):
        graph["edges"].append({"id": f"pre_{before['id']}_{after['id']}", "source": before["id"],
            "target": after["id"], "type": "prerequisite", "reason": "示范课程从数据定义到模型评估的教学顺序。",
            "source_ids": [], "review_status": "draft"})
    for chapter in graph["chapters"]:
        chapter["completion_policy"] = {"mode": "all_required_mastered",
            "required_node_ids": [n["id"] for n in graph["nodes"] if n["chapter_id"] == chapter["id"]],
            "configured_by": "课程预设",
            "basis": "本章每个节点均有当前、无提示的客观题通过证据；到期复习或未处理的新困惑会重新进入待核验。"}
    validate_graph(graph)
    return graph


class AcceptanceCourseStore(CourseGraphStore):
    is_demo = True

    def __init__(self, default_store):
        super().__init__(output_dir=default_store.output_dir / "acceptance_demo" / "v1", clock=default_store.clock)

    def load_graph(self, view="published", version=None):
        if view not in {"draft", "published"} or (version is not None and (type(version) is not int or version != 1)):
            raise CourseGraphError("示范课程仅提供固定的 v1 验收内容。", 409)
        return build_graph()

    def publication(self):
        return {"draft_version": 1, "published_version": None, "demo_version": 1,
                "delivery_mode": "acceptance_demo", "notice": NOTICE}

    def save_graph(self, *args, **kwargs):
        raise CourseGraphError("内置示范课程是只读样本，请在独立课程中编辑教学内容。", 409)

    def publish(self, *args, **kwargs):
        raise CourseGraphError("内置示范课程不作为人工审核后的正式课程发布。", 409)

    def _confirmed(self, diagnosis):
        return super()._confirmed(diagnosis) or (diagnosis.get("review_status") == "rule_verified"
            and diagnosis.get("assessment_origin") == "objective_rule" and diagnosis.get("rule_id") == "demo-choice-v1")

    def _published_history(self):
        return []  # Immutable v1; no publication pointer or invented review record.

    @staticmethod
    def tasks(node):
        return [node["check_task"], *node["retest_tasks"]]

    def choose_task(self, node, workspace):
        tasks = self.tasks(node)
        attempted = {old["task"]["id"] for old in workspace["lessons"] if old["node_id"] == node["id"]
                     and (old["responses"] or old["prompt_level"])}
        return next((task for task in tasks if task["id"] not in attempted), tasks[-1])

    def lesson_task(self, node, lesson):
        return next(task for task in self.tasks(node) if task["id"] == lesson["task"]["id"])

    def grade(self, graph, learner, workspace, lesson, node, record, choice):
        task = self.lesson_task(node, lesson)
        passed = choice == task["answer_key"]
        independent = self._independent(record)
        status = "mastered" if passed and independent else "uncertain" if passed else "needs_review"
        basis = ("本题独立作答通过。" if status == "mastered" else
                 "提示或解析后答对，需换题独立复测；若两题均已看过，请教师复核。" if passed else
                 "本次选项未通过，请重读算例、按需查看提示，再安排本节点复测。")
        previous = [d for d in learner["diagnoses"] if d["node_id"] == node["id"]
                    and d.get("assessment_origin") == "objective_rule"]
        refs = [record["id"], *[e["id"] for e in learner["evidence"] if e["node_id"] == node["id"]
                               and e["source_type"] == "self_assessment"]]
        diagnosis = {"id": uuid.uuid4().hex, "student_id": learner["student_id"], "course_id": graph["id"],
            "course_version": graph["version"], "node_id": node["id"], "node_fingerprint": _fingerprint(node),
            "status": status, "basis": basis, "review_status": "rule_verified", "reviewer": "",
            "assessment_origin": "objective_rule", "rule_id": "demo-choice-v1", "evidence_ids": refs,
            "resolves_diagnosis_ids": [d["id"] for d in previous], "created_at": self._stamp(), "review_stage": 0}
        if status == "mastered":
            diagnosis["mastered_at"] = record["created_at"]
        learner["diagnoses"].append(diagnosis)
        # Feedback exposes the solution. Future use of this exact question is assisted,
        # even in a new lesson or after refresh. The submitted evidence stays immutable.
        workspace["exposures"][lesson["task_key"]] = 4
        lesson["prompt_level"] = 4
        lesson["status"] = "assessed"
        return {"passed": passed, "choice_id": choice, "error_code": None if passed else task["error_code"],
                "feedback": basis, "explanation": task["explanation"], "assessment_origin": "objective_rule",
                "diagnosis_id": diagnosis["id"], "status": status}
