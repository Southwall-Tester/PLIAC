"""Versioned experiment contracts. Course identity never selects grading rules."""
import json
from learning_agent.course_graph import ROOT

CONTRACT = json.loads((ROOT / "data/activities/classification_lab.v1.json").read_text(encoding="utf-8"))
VERSION = CONTRACT["version"]
SCENES = CONTRACT["scenes"]
TASKS = CONTRACT["tasks"]


def public_tasks():
    tasks = [{key: value for key, value in task.items() if key != "hints"} for task in TASKS]
    # Keep the authored v1 artifact immutable; this UI/check policy only makes
    # prose optional alongside the existing substantive answer selections.
    for task in tasks:
        if task["id"] == "select":
            task["acceptance"] = "同一划分至少比较三种深度，其中包含 2—8 的深度；选择验证准确率最高的实验和选型依据。"
        elif task["id"] == "deliver":
            task["acceptance"] = "在测试前封存参数，选择测试结果的用途，再完成一次测试。"
        task["answer_policy"] = "structured_choices_with_optional_note_v2"
    return tasks
