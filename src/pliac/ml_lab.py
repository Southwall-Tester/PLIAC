"""ML Lab sessions share the platform's atomic learner/evidence store."""
import copy
import json
import secrets
import uuid
from datetime import datetime

from learning_agent.course_graph import CourseGraphError, _text
from .workspace import LearningWorkspace
from .ml_contract import SCENES, TASKS, VERSION, public_tasks
from .ml_engine import execute, preview, reproduction
from .rhythm import lab_rhythm
from .lab_context import support_offer


def recent_lab(store, student):
    """Read the unfinished active round without generating learner evidence."""
    graph = store.load_graph()
    if not graph:
        return []
    workspace = store._read_learner(student).get("workspace", {})
    lab = workspace.get("ml_lab", {})
    session = next((item for item in lab.get("sessions", []) if item["id"] == lab.get("active_id")), None)
    if not session or session.get("final"):
        return []
    try:
        mapping = MLLab.binding(graph)
    except CourseGraphError:
        return []
    changed = not MLLab.compatible(session, graph, mapping)
    timestamps = [session.get("created_at")]
    timestamps.extend(event.get("created_at") for event in workspace.get("events", [])
                      if event.get("session_id") == session["id"] and event.get("kind", "").startswith("ml_lab_"))
    saved = []
    for value in timestamps:
        try:
            stamp = datetime.fromisoformat(value)
            if stamp.tzinfo is not None:
                saved.append(stamp.timestamp())
        except (TypeError, ValueError, OverflowError):
            continue
    return [{"kind": "lab", "session_id": session["id"], "restart_required": changed,
             "title": session.get("presentation", {}).get("title", "机器学习实验"),
             "updated_at": max(saved, default=0)}]


class MLLab(LearningWorkspace):
    @staticmethod
    def compatible(session, graph, mapping):
        return (session.get("course_version") == graph["version"]
                and session.get("node_mapping") == mapping
                and session.get("contract_version") == VERSION)

    @staticmethod
    def binding(graph):
        """A formal course must explicitly map the lab's skills to its nodes."""
        required = {node for task in TASKS for node in task["nodes"]}
        config = graph.get("ml_lab", {})
        if not isinstance(config, dict):
            raise CourseGraphError("ML Lab 配置须为知识映射对象。", 409)
        # Course packages (main, 2026-10-09) bind lab skills through a classification_lab activity.
        activity = next((a for a in graph.get("activities", []) if a.get("engine") == "classification_lab"), None)
        if activity and activity.get("node_bindings"):
            mapping = {node: activity["node_bindings"].get(node) for node in required}
        elif graph.get("delivery_mode") == "acceptance_demo":
            mapping = {node: node for node in required}
        else:
            mapping = config.get("node_mapping", {})
        nodes = {node["id"] for node in graph["nodes"]}
        if not isinstance(mapping, dict) or set(mapping) != required or any(not isinstance(value, str) or value not in nodes for value in mapping.values()):
            raise CourseGraphError("本课程尚未配置完整的 ML Lab 知识映射，不能将实验记入其他课程。", 409)
        return copy.deepcopy(mapping)

    def view(self, student_id):
        graph = self.store._require_graph()
        mapping = self.binding(graph)
        activity = next((a for a in graph.get("activities", []) if a.get("engine") == "classification_lab"), {})
        learner = self.store.load_learner(student_id, graph)
        lab = copy.deepcopy(learner.get("workspace", {}).get("ml_lab", {"sessions": [], "active_id": None}))
        active = next((s for s in lab["sessions"] if s["id"] == lab["active_id"]), None)
        restart_required = bool(active and not self.compatible(active, graph, mapping))
        tasks = public_tasks()
        for task in tasks:
            task["nodes"] = [mapping[node] for node in task["nodes"]]
        return {"student_id": student_id, "version": learner["version"], "course_version": graph["version"],
                "scenes": SCENES, "tasks": tasks, "node_mapping": mapping, "lab": lab, "active": active,
                "restart_required": restart_required,
                "support_offer": support_offer(active) if active and not restart_required else None,
                "preview": preview(active["seed"]) if active else [],
                "course_id": graph["id"],
                "knowledge": [{"node_id": n["id"], "title": n["title"], "text": n.get("description", "")} for n in graph["nodes"] if n["id"] in activity.get("knowledge_node_ids", [])], "rhythm": lab_rhythm(TASKS, active, learner.get("workspace", {}))}

    def act(self, operation, payload):
        def apply(graph, learner, workspace):
            mapping = self.binding(graph)
            lab = workspace.setdefault("ml_lab", {"sessions": [], "active_id": None})
            if operation == "start":
                if payload.get("scene") not in SCENES:
                    raise CourseGraphError("请选择实验情境。")
                current = next((s for s in lab["sessions"] if s["id"] == lab["active_id"]), None)
                if current and self.compatible(current, graph, mapping) and current["step"] < len(TASKS):
                    raise CourseGraphError("当前实验正在进行，请继续完成。", 409)
                if len(lab["sessions"]) >= 10:
                    raise CourseGraphError("已保存十轮实验，达到当前保存上限，请导出实验记录。", 409)
                seed = secrets.randbelow(1000000)
                while seed in {old["seed"] for old in lab["sessions"]}:
                    seed = (seed + 1) % 1000000
                session = {"id": uuid.uuid4().hex, "contract_version": VERSION, "scene": payload["scene"],
                           "course_version": graph["version"], "node_mapping": mapping,
                           "scene_origin": "authored_template", "presentation": copy.deepcopy(SCENES[payload["scene"]]), "seed": seed,
                           "mode": "transfer" if any(self.compatible(old, graph, mapping) and old.get("final")
                                                     for old in lab["sessions"]) else "practice", "step": 0,
                           "created_at": self.store._stamp(), "runs": [], "checks": [], "hints": {}, "selected_id": None,
                           "final": None, "profile": {"goal": _text(payload.get("goal", ""), "学习目标", 1000, False)}}
                lab["sessions"].append(session)
                lab["active_id"] = session["id"]
                if session["profile"]["goal"]:
                    learner["profile"]["goals"] = session["profile"]["goal"]
                self._event(workspace, "ml_lab_start", session_id=session["id"])
                return
            session = next((s for s in lab["sessions"] if s["id"] == lab["active_id"]), None)
            if not session or payload.get("session_id") != session["id"]:
                raise CourseGraphError("实验已切换，请重新载入。", 409)
            if not self.compatible(session, graph, mapping):
                raise CourseGraphError("课程、映射或实验规则已更新，旧轮次保留，请开始新版实验。", 409)
            if operation == "rest":
                point = lab_rhythm(TASKS, session, workspace)["current"]
                if not point or point["id"] != payload.get("point_id"):
                    raise CourseGraphError("休息位置已更新，请刷新实验。", 409)
                choice = payload.get("choice")
                if choice not in {"rest", "continue"}:
                    raise CourseGraphError("请选择休息或继续实验。")
                workspace.setdefault("rhythm_marks", {})[point["id"]] = {"choice": choice, "plan": point, "created_at": self.store._stamp()}
                self._event(workspace, "rest_choice", point_id=point["id"], choice=choice)
                return
            if session["step"] >= len(TASKS):
                raise CourseGraphError("本轮实验已完成，可导出报告或开始迁移复测。", 409)
            task = TASKS[session["step"]]
            level = session["hints"].get(task["id"], 0)
            if operation == "support":
                offer = support_offer(session)
                choice = payload.get("choice")
                if not offer or payload.get("task_id") != task["id"]:
                    raise CourseGraphError("帮助邀请已变化，请刷新当前实验。", 409)
                if choice not in {"hint", "continue"}:
                    raise CourseGraphError("请选择查看提示或继续尝试。")
                if choice == "hint":
                    if not offer["hint_available"]:
                        raise CourseGraphError("本步提示已全部展示，可查看已有提示或向智能体提问。", 409)
                    session["hints"][task["id"]] = level + 1
                mark = {**offer, "choice": choice, "created_at": self.store._stamp()}
                session.setdefault("support_choices", {})[task["id"]] = mark
                self._event(workspace, "ml_lab_support_choice", session_id=session["id"], **mark)
            elif operation == "hint":
                session["hints"][task["id"]] = min(3, level + 1)
                self._event(workspace, "ml_lab_hint", session_id=session["id"], task_id=task["id"], level=min(3, level + 1))
            elif operation == "run":
                if session["step"] >= 4:
                    raise CourseGraphError("方案已封存，请完成测试与报告。", 409)
                if len(session["runs"]) >= 60:
                    raise CourseGraphError("本轮已有 60 次实验，请比较已有结果。", 409)
                settings = payload.get("config")
                result = execute(session["seed"], settings)
                run = {"id": uuid.uuid4().hex, "number": len(session["runs"]) + 1,
                       "config": copy.deepcopy(settings), "result": result, "created_at": self.store._stamp()}
                record = self._evidence(graph, learner, self.store._node(graph, mapping["accuracy"]),
                                        json.dumps(run, ensure_ascii=False), "technical", level,
                                        {"lab_session_id": session["id"], "run_id": run["id"]})
                record["origin"] = "system_observation"
                run["evidence_id"] = record["id"]
                session["runs"].append(run)
            elif operation == "check":
                self._check(graph, learner, workspace, session, task, payload, level)
            else:
                raise CourseGraphError("请选择实验提供的操作。", 404)
        result = self._mutate(payload, "ml_lab_" + operation, apply)
        return self.hints(result)

    def _check(self, graph, learner, workspace, session, task, payload, level):
        answer = payload.get("answer", {})
        if not isinstance(answer, dict):
            raise CourseGraphError("请填写当前任务的提交内容。")
        note = _text(answer.get("note", ""), "判断依据", 2000, False)
        runs = session["runs"]
        valid = [r for r in runs if r["config"]["features"] == "sensors" and r["config"]["split"] == "separate"]
        chosen = next((r for r in valid if r["id"] == answer.get("run_id")), None)
        group = [r for r in valid if chosen and r["result"]["split_hash"] == chosen["result"]["split_hash"]]
        depths = {r["config"]["depth"] for r in group}
        passed = False
        refs = []
        if task["id"] == "inspect":
            passed = answer.get("target") == "target" and answer.get("features") == "sensors" and answer.get("timing") == "after"
        elif task["id"] == "split":
            passed = chosen is not None
            refs = [chosen["evidence_id"]] if chosen else []
        elif task["id"] == "compare":
            passed = {0, 1}.issubset(depths) and answer.get("interpretation") == "gap"
            refs = [r["evidence_id"] for r in group]
        elif task["id"] == "select":
            passed = (chosen is not None and {0, 1}.issubset(depths) and any(2 <= d <= 8 for d in depths)
                      and chosen["result"]["validation_accuracy"] >= max(r["result"]["validation_accuracy"] for r in group)
                      and answer.get("basis") == "validation" and len(note.strip()) >= 12)
            refs = [r["evidence_id"] for r in group]
            if passed:
                session["selected_id"] = chosen["id"]
        elif task["id"] == "deliver":
            passed = answer.get("test_role") == "report" and len(note.strip()) >= 12
            chosen = next(r for r in runs if r["id"] == session["selected_id"])
            refs = [chosen["evidence_id"]]
            if passed:
                session["final"] = {"run_id": chosen["id"], "result": execute(session["seed"], chosen["config"], test=True),
                                    "created_at": self.store._stamp()}
        context = {"task_id": "ml_lab_" + task["id"], "task_version": VERSION,
                   "skeleton_id": "ml_tree_lab", "skeleton_version": VERSION,
                   "lab_session_id": session["id"], "experiment_evidence_ids": refs}
        records = []
        mapping = self.binding(graph)
        for node_id in task["nodes"]:
            record = self._evidence(graph, learner, self.store._node(graph, mapping[node_id]),
                                    json.dumps(answer, ensure_ascii=False), "practice", level, context)
            records.append(record["id"])
        feedback = "本步实操验收通过。" if passed else task["hints"][min(level, 2)]
        session["checks"].append({"id": uuid.uuid4().hex, "task_id": task["id"], "passed": bool(passed),
                                   "prompt_level": level, "evidence_ids": records, "experiment_evidence_ids": refs,
                                   "feedback": feedback, "note": note, "answer": copy.deepcopy(answer),
                                   "rule_id": "ml-lab-contract-v1", "created_at": self.store._stamp()})
        if passed:
            session["step"] += 1
        else:
            session["hints"][task["id"]] = min(3, level + 1)
        event = self._event(workspace, "ml_lab_check", session_id=session["id"], task_id=task["id"], passed=bool(passed))
        if passed and session["step"] == len(TASKS):
            from .teaching_flow import current_turn, enqueue
            turn = current_turn(workspace)
            if turn and turn.get("activity", {}).get("type") == "lab":
                enqueue(workspace, graph, turn["proposal"]["target_node_id"], "lab_finished", event["id"])

    def export(self, student_id):
        view = self.view(student_id)
        session = view["active"]
        if not session:
            raise CourseGraphError("请先开始实验。", 409)
        scripts = {f"experiment-{r['number']}.py": reproduction(session["seed"], r["config"],
                    bool(session["final"] and r["id"] == session["selected_id"])) for r in session["runs"]}
        return {"student_id": student_id, "course_id": view["course_id"], "tasks": view["tasks"],
                "tasks_course_version": view["course_version"], "restart_required": view["restart_required"],
                "tasks_scope": "current_course_not_historical_session_snapshot",
                "sessions": view["lab"]["sessions"], "scripts": scripts,
                "assessment": {"practice_complete": session["step"] == len(TASKS),
                               "assisted_tasks": [key for key, value in session["hints"].items() if value],
                               "explanation_review": "pending_evidence_assessment"}}

    def hints(self, result):
        active = result["active"]
        result["hint_texts"] = []
        if active and not result.get("restart_required") and active["step"] < len(TASKS):
            task = TASKS[active["step"]]
            result["hint_texts"] = task["hints"][:active["hints"].get(task["id"], 0)]
        return result
