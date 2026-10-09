"""Content-load planning, adapted from LearnMargin's complete-boundary approach.

Minutes are planning estimates, never elapsed time or mastery evidence.
See docs/study-design.md for weights, calibration limits and provenance.
"""
import hashlib
import json
import math
from pathlib import Path

POLICY_VERSION = "content-load-v1"
WEIGHTS = {"concepts": 1.2, "decisions": 1.5, "checks": 1.0, "calculations": 1.5,
           "comparisons": 2.0, "runs": 2.0, "explanations": 2.0, "questions": 2.0}
PROFILE_PATH = Path(__file__).resolve().parents[2] / "data/study_loads.json"


def estimate(load):
    """Accept author/model estimates, or auditable counts of semantic work units."""
    if not isinstance(load, dict) or not str(load.get("rationale", "")).strip():
        return None
    if "minutes" in load:
        value = load["minutes"]
        if type(value) not in (float, int) or not math.isfinite(value) or not 0 < value <= 180:
            return None
        return round(value, 2)
    units = load.get("units")
    if not isinstance(units, dict) or not units or set(units) - set(WEIGHTS):
        return None
    if any(type(v) not in (float, int) or not math.isfinite(v) or not 0 <= v <= 60 for v in units.values()):
        return None
    total = sum(WEIGHTS[k] * v for k, v in units.items())
    return round(total, 2) if 0 < total <= 180 else None


def plan_pauses(blocks, target=25, minimum=15, tail=20, not_before=0):
    """Choose the nearest complete boundary on either side of the target.

    Unknown loads are barriers. No inferred duration is fabricated for them.
    Blocks are indivisible; adjacent light questions must share one block.
    """
    if not all(math.isfinite(x) and x > 0 for x in (target, minimum, tail)):
        raise ValueError("节奏参数须为有限正数。")
    points, start = [], 0
    while start < len(blocks):
        total, candidates = 0, []
        end = start
        for end in range(start, len(blocks)):
            minutes = estimate(blocks[end].get("load"))
            if minutes is None:
                break
            total += minutes
            if total >= minimum and end >= not_before:
                candidates.append((abs(total - target), end, total))
            if total >= target and candidates:
                break
        if total < target:
            candidates = [c for c in candidates if c[2] >= tail]
        if not candidates:
            start = end + 1
            continue
        _, chosen, minutes = min(candidates)
        block = blocks[chosen]
        points.append({"id": block["id"], "after": block["after"], "resume": block["resume"],
                       "estimated_minutes": round(minutes, 2), "break_minutes": 5,
                       "basis": "content_estimate", "policy_version": POLICY_VERSION,
                       "rationale": [b["load"]["rationale"] for b in blocks[start:chosen + 1]],
                       "block_ids": [b["id"] for b in blocks[start:chosen + 1]]})
        start = chosen + 1
    return points


def profiles():
    return json.loads(PROFILE_PATH.read_text(encoding="utf-8"))


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]


def _result(blocks, workspace, current_ids):
    marks = workspace.get("rhythm_marks", {})
    # A learner-selected pause or continuation starts a new planning segment.
    last = max((i for i, b in enumerate(blocks) if b["id"] in marks), default=-1)
    remaining = blocks[last + 1:]
    earliest = min((i for i, b in enumerate(remaining) if b["id"] in current_ids), default=0)
    points = plan_pauses(remaining, not_before=earliest)
    current = next((p for p in points if p["id"] in current_ids and p["id"] not in marks), None)
    return {"policy_version": POLICY_VERSION, "plan": points, "current": current,
            "blocks": [{"id": b["id"], "after": b["after"], "minutes": estimate(b.get("load")),
                        "load": b.get("load")} for b in blocks], "estimated": True}


def lab_rhythm(tasks, session, workspace, load_profiles=None):
    if not session:
        return _result([], workspace, set())
    authored = load_profiles if load_profiles is not None else profiles()["lab"]
    blocks = []
    for i, task in enumerate(tasks):
        signature = fingerprint(task)
        profile = authored.get(task["id"], {})
        # Contract edits need a refreshed author estimate unless the contract supplies its own.
        load = task.get("study_load") or (profile.get("load") if profile.get("content_fingerprint") == signature else None)
        if load:
            load = json.loads(json.dumps(load))
            failures = sum(c["task_id"] == task["id"] and not c["passed"] for c in session["checks"])
            if failures and "units" in load:
                load["units"]["checks"] = load["units"].get("checks", 0) + min(failures, 3)
                load["rationale"] += f"；另含 {min(failures, 3)} 次提交后的检查修正。"
        following = tasks[i + 1]["title"] if i + 1 < len(tasks) else "查看实验报告"
        blocks.append({"id": f"lab:{session['id']}:{task['id']}:{signature}", "after": {"task_id": task["id"], "step": i + 1},
                       "load": load, "resume": f"接着{following}。"})
    current_ids = {b["id"] for b in blocks if b["after"]["step"] == session["step"]}
    return _result(blocks, workspace, current_ids)


def course_rhythm(graph, workspace):
    if not graph:
        return _result([], workspace, set())
    nodes = {n["id"]: n for n in graph["nodes"]}
    authored = graph.get("study", {}).get("load_profiles", {})
    lessons = [l for l in workspace["lessons"] if l["course_version"] == graph["version"]
               and (l["responses"] or l["id"] == workspace["current_lesson_id"])]
    visited = {l["node_id"] for l in lessons}
    # Look ahead on the authored route, while accumulated work follows actual visits.
    route = graph.get("learning_order", list(nodes))
    future = [{"id": "future:" + node, "node_id": node, "responses": []} for node in route if node not in visited]
    blocks, current_ids = [], set()
    for l in [*lessons, *future]:
        node = nodes.get(l["node_id"])
        if not node:
            continue
        content = [node.get("description"), node.get("objectives"), node.get("lesson_content"), node.get("check_question")]
        profile = authored.get(node["id"], {})
        loads = node.get("study_load") or (profile.get("blocks") if profile.get("content_fingerprint") == fingerprint(content) else [])
        # An unknown section remains a barrier, rather than guessing from text length.
        if not isinstance(loads, list) or not loads:
            loads = [{"boundary": "practice", "load": None}]
        for item in loads:
            if not isinstance(item, dict) or not isinstance(item.get("boundary"), str):
                item = {"boundary": "practice", "load": None}
            boundary = item["boundary"]
            ident = f"course:{graph['id']}:{graph['version']}:{l['id']}:{boundary}"
            blocks.append({"id": ident, "after": {"lesson_id": l["id"], "node_id": node["id"], "boundary": boundary},
                           "load": item.get("load"), "resume": item.get("resume", "从当前小节接着学习。")})
            if l["id"] == workspace["current_lesson_id"]:
                current_ids.add(ident)
    return _result(blocks, workspace, current_ids)
