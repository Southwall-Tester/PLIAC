"""Immutable stage reports assembled from persisted learning evidence."""
import copy
import uuid
from collections import Counter

from learning_agent.course_graph import CourseGraphError
from .memory import learning_memory
from .workspace import LearningWorkspace


def append_snapshot(graph, learner, workspace, request_id, stamp, node_ids=None):
    memory = learning_memory(graph, learner)
    if node_ids is not None:
        memory["nodes"] = {key: value for key, value in memory["nodes"].items() if key in node_ids}
    if not memory["nodes"]:
        raise CourseGraphError("尚无学习过程记录，请先学习或完成一次核验后再保存总结。", 409)
    reports = workspace.setdefault("stage_reports", [])
    node_ids = set(memory["nodes"])
    # Reports snapshot only student-facing facts, never private rubrics,
    # future hints, camera media or internal provider configuration.
    evidence = [{key: item.get(key) for key in ("id", "node_id", "course_version", "text", "source_type", "origin", "prompt_level", "created_at")}
        for item in learner["evidence"] if item["node_id"] in node_ids and item["course_id"] == graph["id"]]
    diagnoses = [{key: item.get(key) for key in ("id", "node_id", "course_version", "status", "basis", "evidence_ids", "criteria", "created_at", "resolves_diagnosis_ids")}
        for item in learner["diagnoses"] if item["node_id"] in node_ids and item["course_id"] == graph["id"]]
    for diagnosis in diagnoses:
        diagnosis["applicable"] = diagnosis["id"] in learner["states"].get(diagnosis["node_id"], {}).get("applicable_diagnosis_ids", [])
    report = {"id": uuid.uuid4().hex, "request_id": request_id, "title": graph["title"] + " · 阶段学习总结",
        "course_id": graph["id"], "course_version": graph["version"], "learner_version": learner["version"],
        "created_at": stamp, "goals": learner["profile"].get("goals", ""),
        "scope": "截至保存时，本课程已有学习过程记录的知识点，不代表整门课程考核。",
        "counts": dict(Counter(item["status"] for item in memory["nodes"].values())),
        "nodes": copy.deepcopy(memory["nodes"]), "evidence": copy.deepcopy(evidence), "diagnoses": copy.deepcopy(diagnoses),
        "notes": [copy.deepcopy(items[-1]) for node, items in workspace.get("notes", {}).items() if node in node_ids and items and items[-1]["text"].strip()],
        "material_ids": [turn["request_id"] for turn in workspace.get("tutor_turns", []) if turn["proposal"]["target_node_id"] in node_ids],
        "limitations": "依据现有任务与证据形成的阶段记录，不是完整能力测量；受助、未核验、冲突及旧版本结论应分别解释。"}
    reports.append(report)
    return report


class StageReports(LearningWorkspace):
    def save(self, payload):
        def apply(graph, learner, workspace):
            report = append_snapshot(graph, learner, workspace, payload["request_id"], self.store._stamp())
            self._event(workspace, "stage_report_saved", report_id=report["id"])
        return self._mutate(payload, "stage_report", apply)
