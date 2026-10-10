"""Deterministic, source-linked memory projections; never new diagnoses."""
import copy


def learning_memory(graph, learner):
    workspace = learner.get("workspace", {})
    result = {"policy": "source-linked-memory-v1", "course_version": graph["version"] if graph else None,
        "learner_version": learner["version"], "nodes": {}}
    if not graph:
        return result
    for node in graph["nodes"]:
        ident = node["id"]
        evidence = [item for item in learner.get("evidence", []) if item["node_id"] == ident and item["course_id"] == graph["id"]]
        diagnoses = [item for item in learner.get("diagnoses", []) if item["node_id"] == ident and item["course_id"] == graph["id"]]
        resolved = {ref for item in diagnoses for ref in item.get("resolves_diagnosis_ids", [])}
        turns = [item for item in workspace.get("tutor_turns", []) if item["proposal"]["target_node_id"] == ident]
        tasks = [item for item in workspace.get("assessments", []) if item["node_id"] == ident]
        notes = workspace.get("notes", {}).get(ident, [])
        if not (evidence or diagnoses or turns or notes or tasks):
            continue
        state = learner.get("states", {}).get(ident, {"status": "unknown", "reason": "尚无掌握证据"})
        result["nodes"][ident] = {
            "title": node["title"], "status": state["status"], "reason": state["reason"],
            "due_at": state.get("due_at"), "version_changed": state.get("version_changed", False),
            "evidence_count": len(evidence), "diagnosis_count": len(diagnoses),
            "recent_evidence_ids": [item["id"] for item in evidence[-5:]],
            "recent_diagnosis_ids": [item["id"] for item in diagnoses[-5:]],
            "recent_feedback": [{"diagnosis_id": item["id"], "course_version": item["course_version"],
                "text": item["basis"], "resolved": item["id"] in resolved,
                "applicable": item["id"] in state.get("applicable_diagnosis_ids", [])} for item in diagnoses[-3:]],
            "assisted_evidence_count": sum(bool(item.get("prompt_level")) for item in evidence),
            "material_ids": [item["request_id"] for item in turns[-3:]],
            "note_id": notes[-1]["id"] if notes and notes[-1]["text"].strip() else None,
            "pending_assessments": [{"id": item["id"], "status": item["status"], "course_version": item["course_version"]}
                for item in tasks if item["status"] in {"open", "submitted"}][-5:],
        }
    return result


def recall_memory(graph, learner, node_ids):
    memory = learning_memory(graph, learner)
    memory["nodes"] = {key: copy.deepcopy(value) for key, value in memory["nodes"].items() if key in node_ids}
    return memory
