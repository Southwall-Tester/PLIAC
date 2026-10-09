"""Retrieval conditions, learner-authored chunks and bounded mixed practice.

These activities preserve raw expression; they never create mastery diagnoses.
The demo's authored v1 questions remain immutable.
"""
import copy
import uuid

from learning_agent.course_graph import CourseGraphError, _dict, _text

CONFIDENCE = {"sure": "确定", "unsure": "不太确定", "guess": "猜的"}
CARD_FIELDS = {"trigger": "什么时候用", "reason": "为什么这样做", "steps": "关键步骤",
               "boundary": "容易误判的地方", "reflection": "我的卡点与修正"}
MIXED = [
    {"id": "roles-a", "nodes": ["roles", "partition"], "question": "已经准备好三份互不重叠的数据。现在要比较深度不同的模型，应依据哪份数据的成绩选择方案？",
     "options": ["训练集", "验证集", "测试集"], "key": 1, "explanation": "验证集用于比较候选方案；训练集用于拟合，测试集留到方案确定之后。"},
    {"id": "roles-b", "nodes": ["roles", "partition"], "question": "某份数据的标签被训练算法用来调整模型参数。这份数据承担什么职责？",
     "options": ["验证集", "测试集", "训练集"], "key": 2, "explanation": "参与拟合参数的是训练集。验证集提供选择依据，测试集评估已经确定的方案。"},
    {"id": "roles-c", "nodes": ["roles", "partition"], "question": "参数已封存，现在要报告模型对未参与拟合和选型的数据的表现，应使用哪份数据？",
     "options": ["测试集", "训练集", "验证集"], "key": 0, "explanation": "测试集用于最终评估；看过测试成绩再据此调参，会改变这份数据的用途。"},
    {"id": "fit-a", "nodes": ["underfit", "overfit", "leakage"], "question": "在相同且无泄漏的划分上，深树的训练准确率为 99%，验证准确率为 69%；中等深度分别为 87% 和 84%。深树更值得检查什么？",
     "options": ["欠拟合", "过拟合", "事后信息泄漏"], "key": 1, "explanation": "训练表现改善而验证表现下降，支持检查过拟合。这个现象本身不能证明数据泄漏。"},
    {"id": "fit-b", "nodes": ["underfit", "overfit", "leakage"], "question": "划分与特征相同，一层树的训练和验证准确率都约 60%；增加适当深度后，两者均明显提高。原模型更符合哪种情况？",
     "options": ["欠拟合", "过拟合", "事后信息泄漏"], "key": 0, "explanation": "浅树在训练数据上也难以拟合，增加表达能力后两者改善，支持欠拟合判断。"},
    {"id": "fit-c", "nodes": ["underfit", "overfit", "leakage"], "question": "模型加入检修完成后才产生的回执，验证准确率从 80% 升到 99%，但任务要求提前预测是否需要检修。首先应检查什么？",
     "options": ["欠拟合", "过拟合", "事后信息泄漏"], "key": 2, "explanation": "回执在预测时尚不可用，属于事后信息泄漏。判断依据是信息产生时间，而非单看分数。"},
]


def confidence(value):
    if value not in CONFIDENCE:
        raise CourseGraphError("请先选择对这次回答的把握。")
    return value


def eligible_tasks(graph, workspace):
    if graph.get("delivery_mode") != "acceptance_demo":
        return []
    studied = {x["node_id"] for x in workspace["lessons"] if x["responses"]}
    # Relation types guide comparison, never create prerequisite edges.
    confusable = {e["source"] for e in graph["edges"] if e["type"] == "confusable"}
    confusable |= {e["target"] for e in graph["edges"] if e["type"] == "confusable"}
    return [t for t in MIXED if set(t["nodes"]) <= studied
            and (t["id"].startswith("roles") or set(t["nodes"]) & confusable)]


def study_view(graph, workspace):
    if not graph:
        return {}
    attempts = workspace.get("mixed_attempts", [])
    seen = {a["task_id"] for a in attempts}
    tasks = eligible_tasks(graph, workspace)
    # Rotate methods instead of issuing three consecutive questions of one type.
    order = ["roles-a", "fit-a", "roles-b", "fit-b", "roles-c", "fit-c"]
    available = {t["id"]: t for t in tasks if t["id"] not in seen}
    task = next((available[i] for i in order if i in available), None)
    return {"mixed_task": {k: copy.deepcopy(v) for k, v in task.items() if k not in {"key", "explanation"}} if task else None,
            "mixed_completed": len(attempts), "mixed_total": len(tasks),
            "mixed_history": copy.deepcopy(attempts), "cards": copy.deepcopy(workspace.get("chunk_cards", {}))}


class StudyActivities:
    def rest(self, payload):
        from .rhythm import course_rhythm
        def apply(graph, learner, workspace):
            rhythm = course_rhythm(graph, workspace)
            point = next((p for p in rhythm["plan"] if p["id"] == payload.get("point_id")
                          and p["after"]["lesson_id"] == workspace["current_lesson_id"]), None)
            if not point:
                raise CourseGraphError("休息位置已更新，请刷新当前小节。", 409)
            choice = payload.get("choice")
            if choice not in {"rest", "continue"}:
                raise CourseGraphError("请选择休息或继续学习。")
            workspace.setdefault("rhythm_marks", {})[point["id"]] = {"choice": choice, "plan": point, "created_at": self.store._stamp()}
            self._event(workspace, "rest_choice", point_id=point["id"], choice=choice)
        return self._mutate(payload, "rest", apply)

    def study(self, payload):
        def apply(graph, learner, workspace):
            lesson = self._lesson(payload, graph, workspace)
            action = payload.get("action")
            session = lesson.setdefault("study", {"mode": "reading", "recall_started": False,
                                                "material_reopened": False, "support_viewed": False})
            if action == "recall":
                session.update(mode="recall", recall_started=True)
            elif action == "read":
                if session["recall_started"]:
                    session["material_reopened"] = True
                session["mode"] = "reading"
            elif action == "break":
                note = _text(payload.get("note", ""), "回来后的起点", 1000, False)
                session.update(paused=True, resume_note=note)
            elif action in {"continue", "dismiss_break"}:
                session.update(paused=False, break_dismissed=True)
            else:
                raise CourseGraphError("请选择回想、阅读或休息操作。")
            self._event(workspace, "study_" + action, lesson_id=lesson["id"])
        return self._mutate(payload, "study", apply)

    def card(self, payload):
        def apply(graph, learner, workspace):
            node = self.store._node(graph, payload.get("node_id"))
            fields = _dict(payload.get("fields"), "解题卡")
            values = {key: _text(fields.get(key, ""), label, 600, False) for key, label in CARD_FIELDS.items()}
            if not any(values.values()):
                raise CourseGraphError("请先写下一个要点或卡点。")
            text = "\n".join(f"{CARD_FIELDS[k]}：{v}" for k, v in values.items() if v)
            record = self._evidence(graph, learner, node, text, "dialog", context={"activity": "chunk_card"})
            workspace.setdefault("chunk_cards", {})[node["id"]] = {
                "fields": values, "evidence_id": record["id"], "course_version": graph["version"],
                "saved_at": record["created_at"], "title": node["title"]}
        return self._mutate(payload, "card", apply)

    def mixed(self, payload):
        def apply(graph, learner, workspace):
            task = next((t for t in eligible_tasks(graph, workspace) if t["id"] == payload.get("task_id")), None)
            if not task:
                raise CourseGraphError("先完成相关小节的练习，再进行混合辨析。", 409)
            attempts = workspace.setdefault("mixed_attempts", [])
            if any(a["task_id"] == task["id"] for a in attempts):
                raise CourseGraphError("本题已提交，请查看反馈并继续下一题。", 409)
            choice = payload.get("choice")
            if type(choice) is not int or not 0 <= choice < len(task["options"]):
                raise CourseGraphError("请选择当前题目的一个选项。")
            certainty = confidence(payload.get("confidence"))
            reason = _text(payload.get("reason"), "判断依据", 1200)
            context = {"task_id": "mixed_" + task["id"], "task_version": 1, "activity": "mixed",
                       "confidence": certainty, "related_node_ids": task["nodes"]}
            record = self._evidence(graph, learner, self.store._node(graph, task["nodes"][0]),
                                    task["options"][choice] + "\n" + reason, "quiz", context=context)
            attempts.append({"id": uuid.uuid4().hex, "task_id": task["id"], "question": task["question"],
                             "choice": choice, "reason": reason, "confidence": certainty,
                             "correct": choice == task["key"], "explanation": task["explanation"],
                             "evidence_id": record["id"], "created_at": self.store._stamp()})
            self._event(workspace, "mixed_answer", evidence_id=record["id"])
        return self._mutate(payload, "mixed", apply)
