"""Server-owned teaching triggers; activity progress never manufactures mastery."""
import uuid

from learning_agent.course_graph import CourseGraphError
from .workspace import LearningWorkspace


def enqueue(workspace, graph, node_id, reason, source_id):
    flow = workspace.get("teaching_flow")
    if not flow:
        return
    flow["pending"] = {"id": uuid.uuid4().hex, "node_id": node_id, "reason": reason,
                       "source_id": source_id, "course_version": graph["version"]}


def current_turn(workspace):
    ident = workspace.get("teaching_flow", {}).get("current_turn_id")
    return next((turn for turn in workspace.get("tutor_turns", []) if turn["request_id"] == ident), None)


def after_assessment(workspace, graph, record):
    current = current_turn(workspace)
    if current and current.get("activity", {}).get("id") == record["id"]:
        enqueue(workspace, graph, record["node_id"], "assessment_evaluated", record["id"])


def validate_trigger(workspace, graph, body):
    validate_scope_version(workspace, graph)
    flow = workspace.get("teaching_flow", {})
    pending = flow.get("pending")
    if not flow.get("enabled") or not pending or pending["id"] != body.get("trigger_id"):
        raise CourseGraphError("这次自动安排已暂停、完成或被新的学习选择替代，请刷新状态。", 409)
    if pending["course_version"] != graph["version"] or pending["node_id"] != body.get("node_id"):
        raise CourseGraphError("教学触发对应的课程或知识点已变化，请重新选择学习目标。", 409)
    return pending


def validate_scope_version(workspace, graph):
    flow = workspace.get("teaching_flow", {})
    ids = {flow.get("active_plan_id"), flow.get("pending_plan_id")}
    records = [plan for plan in workspace.get("learning_plans", []) if plan["id"] in ids]
    request = flow.get("plan_request")
    if any(plan["course_version"] != graph["version"] for plan in records) or (request and request["course_version"] != graph["version"]):
        raise CourseGraphError("课程已更新，请先调整目标并重新协商学习范围；历史记录保留，仍可自主浏览。", 409)


class TeachingFlow(LearningWorkspace):
    def command(self, payload):
        def apply(graph, learner, workspace):
            if not workspace.get("onboarded"):
                raise CourseGraphError("请先保存目标与学习起点。", 409)
            flow = workspace.setdefault("teaching_flow", {"enabled": False, "pending": None, "current_turn_id": None})
            operation = payload.get("operation")
            if operation == "pause":
                flow["enabled"] = False
                self._event(workspace, "teaching_paused")
                return
            validate_scope_version(workspace, graph)
            if operation in {"resume", "choose"}:
                if flow.get("plan_request") or flow.get("pending_plan_id"):
                    raise CourseGraphError("请先采用或调整待定的学习范围；仍可自主浏览课程。", 409)
                node = self.store._node(graph, payload.get("node_id"))
                flow["enabled"] = True
                event = self._event(workspace, "teaching_choice", node_id=node["id"], choice=operation)
                if operation == "resume" and flow.get("pending") and flow["pending"]["course_version"] == graph["version"]:
                    pending = flow["pending"]
                    enqueue(workspace, graph, pending["node_id"], pending["reason"], pending["source_id"])
                    return
                current = current_turn(workspace)
                if operation == "resume" and current and current["course_version"] == graph["version"] and not flow.get("pending"):
                    return
                flow["current_turn_id"] = None
                enqueue(workspace, graph, node["id"], "student_choice", event["id"])
                return
            if operation == "continue":
                turn = current_turn(workspace)
                if not turn or turn["request_id"] != payload.get("turn_id") or turn["course_version"] != graph["version"]:
                    raise CourseGraphError("当前教学活动已变化，请打开当前活动后继续。", 409)
                if flow.get("pending"):
                    raise CourseGraphError("下一步已等待安排，无需重复完成当前活动。", 409)
                activity = turn.get("activity", {})
                if activity.get("type") in {"assessment", "lab"}:
                    raise CourseGraphError("请先完成当前核验或实验，不能用阅读完成代替任务证据。", 409)
                flow["enabled"] = True
                event = self._event(workspace, "teaching_reading_finished", turn_id=turn["request_id"], node_id=turn["proposal"]["target_node_id"])
                enqueue(workspace, graph, turn["proposal"]["target_node_id"], "reading_finished", event["id"])
                return
            raise CourseGraphError("不支持的教学流程操作。", 400)
        return self._mutate(payload, "teaching_flow", apply)
