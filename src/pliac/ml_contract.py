"""Versioned experiment contracts. Course identity never selects grading rules."""
import json
from learning_agent.course_graph import ROOT

CONTRACT = json.loads((ROOT / "data/activities/classification_lab.v1.json").read_text(encoding="utf-8"))
VERSION = CONTRACT["version"]
SCENES = CONTRACT["scenes"]
TASKS = CONTRACT["tasks"]


def public_tasks():
    return [{key: value for key, value in task.items() if key != "hints"} for task in TASKS]
