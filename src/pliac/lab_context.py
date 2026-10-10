"""Bounded, observed experiment context; never expose seeds or unseen hints."""
import copy

from learning_agent.course_graph import CourseGraphError
from .ml_contract import TASKS, VERSION, public_tasks


def assessment_lab_help(workspace, node_id, course_version):
    """Observed hint delivery for a mapped node, not lab completion or emotion."""
    sessions = {item['id']: item for item in workspace.get('ml_lab', {}).get('sessions', [])}
    tasks = {item['id']: item for item in TASKS}
    result = []
    for event in workspace.get('events', []):
        kind = event.get('kind')
        delivered = (kind == 'ml_lab_hint'
            or kind == 'ml_lab_check' and event.get('passed') is False
            or kind == 'ml_lab_support_choice' and event.get('choice') == 'hint')
        if not delivered:
            continue
        session = sessions.get(event.get('session_id'))
        task = tasks.get(event.get('task_id'))
        if not session or not task or session.get('course_version') != course_version:
            continue
        mapping = session.get('node_mapping', {})
        if node_id in [mapping.get(ident) for ident in task['nodes']]:
            result.append(event)
    return result


def support_offer(session):
    """A help invitation after two failed artifact checks, not an emotion label."""
    if not session or session["step"] >= len(TASKS):
        return None
    task = TASKS[session["step"]]["id"]
    if task in session.get("support_choices", {}):
        return None
    checks = [item for item in session.get("checks", []) if item["task_id"] == task and not item["passed"]]
    if len(checks) < 2:
        return None
    return {"task_id": task, "check_ids": [item["id"] for item in checks[-2:]],
            "policy": "two-artifact-checks-v1", "hint_available": session.get("hints", {}).get(task, 0) < 3}


def experiment_context(graph, workspace, mapping):
    lab = workspace.get("ml_lab", {})
    session = next((item for item in lab.get("sessions", []) if item["id"] == lab.get("active_id")), None)
    if not session:
        return {"node_mapping": mapping, "active": None}
    valid = (session.get("course_version") == graph["version"] and session.get("node_mapping") == mapping
             and session.get("contract_version") == VERSION)
    if not valid:
        return {"node_mapping": mapping, "active": None, "notice": "历史实验与当前课程、映射或实验规则不一致，不能据此安排当前实验操作。"}
    task = public_tasks()[session["step"]] if session["step"] < len(TASKS) else None
    if task:
        task["nodes"] = [mapping[node] for node in task["nodes"]]
    chosen = session.get("selected_id")
    runs = session.get("runs", [])
    kept = runs[-6:]
    selected = next((run for run in runs if run["id"] == chosen), None)
    if selected and not any(run["id"] == chosen for run in kept):
        kept = [selected, *kept]
    observed = [{"id": run["id"], "number": run["number"], "config": copy.deepcopy(run["config"]),
        "result": {key: copy.deepcopy(run["result"].get(key)) for key in
                   ("train_accuracy", "validation_accuracy", "overlap", "counts", "confusion_matrix", "tree_nodes")}}
        for run in kept]
    final = session.get("final") if session["step"] == len(TASKS) else None
    return {"node_mapping": mapping, "active": {"id": session["id"], "step": session["step"],
        "mode": session["mode"], "task": task, "presentation": copy.deepcopy(session.get("presentation")),
        "runs": observed, "run_count": len(runs), "runs_truncated": len(kept) < len(runs),
        "checks": [{key: copy.deepcopy(check.get(key)) for key in
                    ("task_id", "passed", "note", "feedback", "prompt_level", "evidence_ids", "experiment_evidence_ids")}
                   for check in session.get("checks", [])[-5:]],
        "hints": copy.deepcopy(session.get("hints", {})), "selected_id": chosen,
        "support_choices": copy.deepcopy(session.get("support_choices", {})),
        "final": {"run_id": final["run_id"], "test_accuracy": final["result"]["test_accuracy"]} if final else None}}


def validate_lab_request(context, ident):
    active = context["lab"]["active"]
    if not active or active["id"] != ident:
        raise CourseGraphError("实验轮次或版本已变化，请回到当前实验后重新提问。", 409)


def record_lab_help(workspace, ident, turn_id):
    lab = workspace.get("ml_lab", {})
    session = next((item for item in lab.get("sessions", []) if item["id"] == ident), None)
    if not session or lab.get("active_id") != ident or session.get("contract_version") != VERSION:
        raise CourseGraphError("实验轮次已变化，旧辅导不会写入新实验。", 409)
    if session["step"] < len(TASKS):
        task = TASKS[session["step"]]["id"]
        # The model may have provided a direct hint; never claim independent work.
        session["hints"][task] = max(1, session["hints"].get(task, 0))
        session.setdefault("tutor_help", []).append({"task_id": task, "turn_id": turn_id})
