"""Evidence-preserving learning sessions. No model-generated mastery decisions."""
from __future__ import annotations

import copy
import hashlib
import json
import uuid

import networkx as nx

from learning_agent.course_graph import (
    CourseGraphError, _dict, _fingerprint, _integer, _list, _text, safe_id, student_graph,
)
from learning_agent.recommendation import recommend_resources
from .study import StudyActivities, study_view, confidence
from .rhythm import course_rhythm

SELF_LABELS = {"new": "尚未学过", "unsure": "学过但不确定", "confident": "能够独立解释和应用"}


def empty_workspace():
    return {"schema_version": 1, "onboarded": False, "self_assessments": {}, "lessons": [],
            "current_lesson_id": None, "drafts": {}, "events": [], "reports": [], "exposures": {}, "receipts": {}}


class LearningWorkspace(StudyActivities):
    def __init__(self, course_store):
        self.store = course_store

    def view(self, student_id):
        safe_id(student_id, "匿名编号")
        graph = self.store.load_graph()
        learner = self.store.load_learner(student_id, graph)
        workspace = copy.deepcopy(learner.get("workspace", empty_workspace()))
        workspace.pop("receipts", None)
        workspace.pop("exposures", None)
        from .memory import learning_memory
        workspace["memory"] = learning_memory(graph, learner)
        for assessment in workspace.get("assessments", []):
            for private in ("rubric", "reference_answer", "answer_key", "task_key"):
                assessment.pop(private, None)
        current = next((x for x in workspace["lessons"] if x["id"] == workspace["current_lesson_id"]), None)
        return {"course": student_graph(graph), "publication": self.store.publication(),
                "concept_map": self.store.concept_map() if hasattr(self.store, "concept_map") else None,
                "learner": {k: v for k, v in learner.items() if k != "workspace"}, "workspace": workspace,
                "current_lesson": current, "course_changed": bool(current and graph and current["course_version"] != graph["version"]),
                "chapters": self.chapter_reports(graph, learner) if graph else [],
                "handbook": self.handbook(graph, learner) if graph else [],
                "study_activities": study_view(graph, workspace), "rhythm": course_rhythm(graph, workspace)}

    def _mutate(self, payload, operation, apply):
        _dict(payload, "学习请求")
        student = safe_id(payload.get("student_id"), "匿名编号")
        request_id = safe_id(payload.get("request_id"), "请求编号")
        expected = _integer(payload.get("expected_version"), "预期学习记录版本")
        version = _integer(payload.get("course_version"), "课程版本", 1)
        # Retries may refresh expected_version, but must not change the operation.
        signature = hashlib.sha256(json.dumps({k: v for k, v in payload.items() if k != "expected_version"},
                                              sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        with self.store._writer():
            learner = self.store._read_learner(student)
            workspace = learner.setdefault("workspace", empty_workspace())
            receipt = workspace["receipts"].get(request_id)
            if receipt:
                if receipt["signature"] != signature or receipt["operation"] != operation:
                    raise CourseGraphError("同一请求编号不能用于不同操作。", 409)
            else:
                self.store._expected(learner, expected)
                graph = self.store._require_graph()
                if graph["version"] != version:
                    raise CourseGraphError("课程已更新，请重新载入并生成新小节；旧记录仍保留。", 409)
                self.store._derive(learner, graph)
                if len(workspace["events"]) >= 10000 or len(workspace["receipts"]) >= 20000:
                    raise CourseGraphError("学习会话记录已达到容量，请先导出并归档。", 409)
                apply(graph, learner, workspace)
                from .memory import learning_memory
                self.store._derive(learner, graph)
                if operation in {"assessment_result", "learning_plan_accepted"}:
                    from .learning_plan import close_supported_plan
                    close_supported_plan(graph, learner, workspace, self.store._stamp())
                workspace["memory"] = learning_memory(graph, learner)
                workspace["memory"]["learner_version"] = learner["version"] + 1
                workspace["receipts"][request_id] = {"operation": operation, "signature": signature}
                self.store._commit(learner)
        return self.view(student)

    def _event(self, workspace, kind, **fields):
        event = {"id": uuid.uuid4().hex, "kind": kind, "created_at": self.store._stamp(), **fields}
        workspace["events"].append(event)
        return event

    def _evidence(self, graph, learner, node, text, source, level=0, context=None):
        record = {"id": uuid.uuid4().hex, "student_id": learner["student_id"], "course_id": graph["id"],
                  "course_version": graph["version"], "node_id": node["id"], "node_fingerprint": _fingerprint(node),
                  "source_type": source, "origin": "learner_expression", "prompt_level": level,
                  "text": _text(text, "原始证据", 4000), "context": context or {}, "expressed_relations": [],
                  "created_at": self.store._stamp()}
        learner["evidence"].append(record)
        return record

    def preferences(self, payload):
        def apply(graph, learner, workspace):
            interests = [_text(item, "案例兴趣", 100) for item in _list(payload.get("interests", []), "案例兴趣", 30)]
            explanation = _text(payload.get("explanation_preferences", ""), "讲解偏好", 1000, False)
            learner["profile"]["interests"] = list(dict.fromkeys(interests))
            learner["profile"]["explanation_preferences"] = explanation
            self._event(workspace, "preferences_changed", course_version=graph["version"], origin="learner_declared")
        return self._mutate(payload, "preferences", apply)

    def onboard(self, payload):
        def apply(graph, learner, workspace):
            for name, label in (("goals", "学习目标"), ("background", "学习背景")):
                learner["profile"][name] = _text(payload.get(name, ""), label, 2000, False)
            if "interests" in payload:
                learner["profile"]["interests"] = [_text(x, "兴趣", 100) for x in _list(payload["interests"], "兴趣", 30)]
            assessments = _dict(payload.get("self_assessments", {}), "三档自评")
            if len(assessments) > 500:
                raise CourseGraphError("自评节点过多。")
            for node_id, value in assessments.items():
                node = self.store._node(graph, node_id)
                if not isinstance(value, str) or value not in SELF_LABELS:
                    raise CourseGraphError("自评须选择尚未学过、学过但不确定或能够独立解释和应用。")
                previous = workspace["self_assessments"].get(node_id)
                if previous and previous["value"] == value and previous["course_version"] == graph["version"]:
                    continue
                evidence = self._evidence(graph, learner, node, SELF_LABELS[value], "self_assessment")
                workspace["self_assessments"][node_id] = {"value": value, "evidence_id": evidence["id"], "course_version": graph["version"]}
            first = not workspace["onboarded"]
            workspace["onboarded"] = True
            event = self._event(workspace, "onboarding", course_version=graph["version"])
            if "agent_guided" in payload:
                if type(payload["agent_guided"]) is not bool:
                    raise CourseGraphError("自动教学选项须为布尔值。")
                flow = workspace.setdefault("teaching_flow", {"pending": None, "current_turn_id": None})
                flow["enabled"] = payload["agent_guided"]
                flow.update(plan_request=None, pending_plan_id=None, active_plan_id=None)
                if flow["enabled"]:
                    flow["current_turn_id"] = None
                    if "plan_mode" in payload:
                        mode, form = payload["plan_mode"], payload.get("preferred_form", "mixed")
                        if mode not in {"systematic", "topic", "task"} or form not in {"mixed", "explanation", "practice", "lab"}:
                            raise CourseGraphError("学习范围类型或形式偏好无效。")
                        anchor = payload.get("start_node_id") or ""
                        if anchor:
                            self.store._node(graph, anchor)
                        flow["pending"] = None
                        flow["plan_request"] = {"id": event["id"], "mode": mode, "preferred_form": form,
                                                "anchor_node_id": anchor, "course_version": graph["version"]}
                    else:
                        node = self.store._node(graph, payload.get("start_node_id"))
                        from .teaching_flow import enqueue
                        enqueue(workspace, graph, node["id"], "initial_diagnosis" if first else "goal_changed", event["id"])
                else:
                    flow["pending"] = None
        return self._mutate(payload, "onboard", apply)

    def _choose_node(self, graph, learner, workspace):
        dag = nx.DiGraph()
        dag.add_nodes_from(n["id"] for n in graph["nodes"])
        dag.add_edges_from((e["source"], e["target"]) for e in graph["edges"] if e["type"] == "prerequisite")
        ordered = list(nx.topological_sort(dag))
        unfinished = [i for i in ordered if learner["states"][i]["status"] != "mastered"]
        frontier = [i for i in unfinished if all(learner["states"][p]["status"] == "mastered" for p in dag.predecessors(i))]
        if not frontier:
            return None
        # The authored route is a teaching preference, never a fabricated edge.
        # Reuse the same task order and remedial loop for existing demo records.
        if getattr(self.store, "is_demo", False) and graph.get("learning_order"):
            route = graph["learning_order"]
            return min(frontier, key=lambda i: (0 if learner["states"][i]["due"] or learner["states"][i]["status"] == "needs_review" else 1,
                                                route.index(i)))
        # Unobserved tasks before waiting tasks; reviewed weaknesses and due reviews first.
        counts = {i: sum(x["node_id"] == i for x in workspace["lessons"]) for i in frontier}
        return min(frontier, key=lambda i: (0 if learner["states"][i]["due"] or learner["states"][i]["status"] == "needs_review" else 1,
                                            counts[i], ordered.index(i)))

    def next_lesson(self, payload):
        def apply(graph, learner, workspace):
            if not workspace["onboarded"]:
                raise CourseGraphError("请先保存学习目标与起点自评。", 409)
            requested = payload.get("node_id") or self._choose_node(graph, learner, workspace)
            if not requested:
                raise CourseGraphError("所有节点当前均有掌握证据，可查看章节报告或选择节点复习。", 409)
            node = self.store._node(graph, requested)
            selection = recommend_resources(graph, learner["states"], node["id"])
            state = learner["states"][node["id"]]
            task = node.get("check_task") if node.get("check_question") else None
            demo = getattr(self.store, "is_demo", False)
            if demo:
                task = self.store.choose_task(node, workspace)
            question = task["question"] if demo else node.get("check_question")
            # Re-labeling a seen question with a new version cannot erase assistance.
            task_key = hashlib.sha256(json.dumps([node["id"], question], ensure_ascii=False).encode()).hexdigest()
            level = workspace["exposures"].get(task_key, 0)
            seen_hints = {h["level"]: copy.deepcopy(h) for old in workspace["lessons"]
                          if old["task_key"] == task_key for h in old["hints"]}
            lesson = {"id": uuid.uuid4().hex, "course_id": graph["id"], "course_version": graph["version"],
                      "chapter_id": node["chapter_id"], "node_id": node["id"], "title": node["title"],
                      "created_at": self.store._stamp(), "reason": state["reason"],
                      "mode": "retest" if state["due"] else "remediate" if state["status"] == "needs_review" else "diagnose",
                      "paragraphs": [{"id": "concept", "text": node.get("description", "")},
                                     *[{"id": f"objective_{i}", "text": text} for i, text in enumerate(node["objectives"])]],
                      "question": question or "请用自己的话说明这一概念，并指出一个仍不确定的地方。",
                      "task": {"id": task["id"], "version": task["version"]} if task else None,
                      "task_key": task_key, "prompt_level": level, "hints": [seen_hints[k] for k in sorted(seen_hints)],
                      "resource_ids": [r["id"] for r in selection["resources"]], "resources": selection["resources"],
                      "prerequisite_gaps": selection["frontier_node_ids"] if selection["frontier_node_ids"] != [node["id"]] else [],
                      "evidence_ids": list(state["evidence_ids"]), "diagnosis_ids": list(state["diagnosis_ids"]),
                      "state_snapshot": copy.deepcopy(learner["states"]), "learner_revision": learner["version"],
                      "policy_version": selection["rule_version"], "selection_trace": selection,
                      "responses": [], "annotations": [], "status": "active"}
            if payload.get("study_protocol") == 1:
                lesson["study"] = {"mode": "recall" if state["due"] else "reading",
                                   "recall_started": bool(state["due"]), "material_reopened": False,
                                   "support_viewed": False}
            if demo:
                lesson.update(paragraphs=copy.deepcopy(node["lesson_content"]), options=copy.deepcopy(task["options"]),
                              sources=[copy.deepcopy(s) for s in graph["sources"] if s["id"] in node["source_ids"]])
            workspace["lessons"].append(lesson)
            workspace["current_lesson_id"] = lesson["id"]
            learner["profile"]["current_position"] = {k: lesson[k] for k in ("course_id", "course_version", "chapter_id", "node_id")}
            learner["profile"]["current_position"]["context_ref"] = lesson["id"]
            learner["profile"]["current_memory"] = {"lesson_id": lesson["id"], "node_id": node["id"], "mode": lesson["mode"]}
            self._event(workspace, "lesson_started", lesson_id=lesson["id"], node_id=node["id"], course_version=graph["version"])
        return self._mutate(payload, "next", apply)

    def _lesson(self, payload, graph, workspace):
        lesson = next((x for x in workspace["lessons"] if x["id"] == payload.get("lesson_id")), None)
        if not lesson or lesson["id"] != workspace["current_lesson_id"]:
            raise CourseGraphError("学习小节已切换，请重新载入。", 409)
        if lesson["course_version"] != graph["version"]:
            raise CourseGraphError("这个小节属于旧课程版本，请生成新小节后继续。", 409)
        return lesson

    def draft(self, payload):
        def apply(graph, learner, workspace):
            lesson = self._lesson(payload, graph, workspace)
            text = _text(payload.get("text", ""), "作答草稿", 4000, False)
            workspace["drafts"][lesson["id"]] = {"text": text, "saved_at": self.store._stamp()}
            if "confidence" in payload:
                value = payload["confidence"]
                workspace["drafts"][lesson["id"]]["confidence"] = confidence(value) if value else ""
            if lesson.get("options"):
                choice = self._choice(lesson, payload, required=False)
                workspace["drafts"][lesson["id"]]["choice_id"] = choice
        return self._mutate(payload, "draft", apply)

    @staticmethod
    def _choice(lesson, payload, required=True):
        choice = payload.get("choice_id", "")
        if not isinstance(choice, str) or choice not in {o["id"] for o in lesson["options"]} | ({""} if not required else set()):
            raise CourseGraphError("请选择当前题目中的一个选项。")
        return choice

    def hint(self, payload):
        def apply(graph, learner, workspace):
            lesson = self._lesson(payload, graph, workspace)
            if not lesson["task"]:
                raise CourseGraphError("这个节点尚未配置诊断题及分级提示，请先记录自己的理解。", 409)
            level = workspace["exposures"].get(lesson["task_key"], 0)
            if level >= 4:
                raise CourseGraphError("该题已给出全部四级提示，请整理思路后作答。", 409)
            node = self.store._node(graph, lesson["node_id"])
            level += 1
            task = self.store.lesson_task(node, lesson) if getattr(self.store, "is_demo", False) else node["check_task"]
            text = task["hint_levels"][level - 1]
            if getattr(self.store, "is_demo", False) and level == 4:
                text += "\n" + task["explanation"]
            workspace["exposures"][lesson["task_key"]] = level
            lesson["prompt_level"] = level
            lesson["hints"].append({"level": level, "text": text, "created_at": self.store._stamp()})
            self._event(workspace, "hint", lesson_id=lesson["id"], prompt_level=level, text=text, origin="system_completion")
        return self._mutate(payload, "hint", apply)

    def answer(self, payload):
        def apply(graph, learner, workspace):
            lesson = self._lesson(payload, graph, workspace)
            node = self.store._node(graph, lesson["node_id"])
            level = workspace["exposures"].get(lesson["task_key"], 0)
            task = lesson["task"]
            context = {"turn_id": len(lesson["responses"]) + 1}
            if lesson.get("study"):
                context["study"] = copy.deepcopy(lesson["study"])
                context["confidence"] = confidence(payload.get("confidence"))
            if task:
                context.update(task_id=task["id"], task_version=task["version"])
            text = payload.get("text")
            demo = getattr(self.store, "is_demo", False)
            if demo:
                if lesson["status"] == "assessed":
                    raise CourseGraphError("本小节已提交，请安排新的复测小节；原始作答已保留。", 409)
                choice = self._choice(lesson, payload)
                option = next(o for o in lesson["options"] if o["id"] == choice)
                reasoning = _text(payload.get("text", ""), "作答思路", 3500, False)
                text = f"{choice}. {option['text']}" + (f"\n我的思路：{reasoning}" if reasoning else "")
            record = self._evidence(graph, learner, node, text, "quiz" if task else "dialog", level, context)
            lesson["responses"].append({"evidence_id": record["id"], "text": record["text"], "prompt_level": level, "created_at": record["created_at"], "context": copy.deepcopy(context)})
            lesson["status"] = "awaiting_review"
            if demo:
                lesson["responses"][-1]["judgement"] = self.store.grade(graph, learner, workspace, lesson, node, record, choice)
            workspace["drafts"].pop(lesson["id"], None)
            self._event(workspace, "answer", lesson_id=lesson["id"], evidence_id=record["id"], prompt_level=level)
        return self._mutate(payload, "answer", apply)

    def annotate(self, payload):
        def apply(graph, learner, workspace):
            lesson = self._lesson(payload, graph, workspace)
            paragraph = next((p for p in lesson["paragraphs"] if p["id"] == payload.get("paragraph_id")), None)
            quote = _text(payload.get("quote"), "标记原文", 3000)
            if not paragraph or quote not in paragraph["text"]:
                raise CourseGraphError("标记必须逐字对应当前小节的段落。")
            question = _text(payload.get("question"), "困惑说明", 800)
            record = self._evidence(graph, learner, self.store._node(graph, lesson["node_id"]),
                                    f"原文：{quote}\n我的问题：{question}", "annotation")
            lesson["annotations"].append({"paragraph_id": paragraph["id"], "quote": quote, "question": question, "evidence_id": record["id"]})
            self._event(workspace, "annotation", lesson_id=lesson["id"], evidence_id=record["id"])
        return self._mutate(payload, "annotate", apply)

    def ask(self, payload):
        """Persist a learner question and grounded course support, separate from grading."""
        def apply(graph, learner, workspace):
            lesson = self._lesson(payload, graph, workspace)
            if lesson.get("study", {}).get("recall_started"):
                lesson["study"]["support_viewed"] = True
            question = _text(payload.get("text"), "本节问题", 1200)
            node = self.store._node(graph, lesson["node_id"])
            discussions = lesson.setdefault("discussions", [])
            if len(discussions) >= 100:
                raise CourseGraphError("本节已有 100 条提问，请整理知识手册后继续。", 409)
            paragraphs = [p for p in lesson["paragraphs"] if p.get("text")]
            # Return stored teaching material. Never claim a live model answered the
            # question or infer mastery from the system's explanatory completion.
            wants_example = any(word in question for word in ("例子", "案例", "举例", "example"))
            preferred = "example" if wants_example else "concept"
            paragraph = next((p for p in paragraphs if p["id"] == preferred), paragraphs[0] if paragraphs else None)
            content = paragraph["text"] if paragraph else node["description"]
            heading = paragraph.get("heading", node["title"]) if paragraph else node["title"]
            response = content + "\n\n对照这段内容，你卡住的是哪个词、哪个步骤，或哪个前置概念？请指出具体位置，我们把问题继续记在这一节。"
            evidence = self._evidence(graph, learner, node, question, "dialog", context={"lesson_id": lesson["id"], "kind": "learner_question"})
            discussions.append({"id": uuid.uuid4().hex, "question": question, "response": response,
                                "evidence_id": evidence["id"], "source_paragraph_id": paragraph["id"] if paragraph else None,
                                "source_heading": heading, "response_origin": "course_material", "created_at": self.store._stamp()})
            self._event(workspace, "learner_question", lesson_id=lesson["id"], evidence_id=evidence["id"])
        return self._mutate(payload, "ask", apply)

    def resource(self, payload):
        def apply(graph, learner, workspace):
            lesson = self._lesson(payload, graph, workspace)
            resource_id = payload.get("resource_id")
            # Recompute from current states: a historical recommendation is not an authorization.
            allowed = recommend_resources(graph, learner["states"], lesson["node_id"])["resources"]
            resource = next((r for r in allowed if r["id"] == resource_id), None)
            if not resource:
                raise CourseGraphError("资源不在当前可用推荐中，请刷新后选择。", 409)
            record = {"id": uuid.uuid4().hex, "student_id": learner["student_id"], "course_id": graph["id"],
                      "course_version": graph["version"], "node_id": resource["recommendation_node_id"], "resource_id": resource_id,
                      "lesson_id": lesson["id"], "requested_node_id": lesson["node_id"],
                      "created_at": self.store._stamp()}
            learner["resource_uses"].append(record)
            self._event(workspace, "resource", lesson_id=lesson["id"], resource_use_id=record["id"])
        return self._mutate(payload, "resource", apply)

    def chapter_reports(self, graph, learner):
        result = []
        for index, chapter in enumerate(graph["chapters"]):
            nodes = [n for n in graph["nodes"] if n["chapter_id"] == chapter["id"]]
            rule = chapter.get("completion_policy")
            required = rule["required_node_ids"] if rule else [n["id"] for n in nodes if n.get("scope", "core") == "core"]
            unresolved = [i for i in required if learner["states"][i]["status"] != "mastered"]
            passed = bool(rule and required and not unresolved)
            rows = [{"node_id": n["id"], "title": n["title"], **copy.deepcopy(learner["states"][n["id"]])} for n in nodes]
            result.append({"chapter_id": chapter["id"], "title": chapter["title"], "course_id": graph["id"],
                           "course_version": graph["version"], "learner_version": learner["version"],
                           "evaluated_at": self.store._stamp(), "rule": copy.deepcopy(rule), "passed": passed,
                           "outcome": "passed" if passed else "not_configured" if not rule else "pending",
                           "required_node_ids": required, "unresolved_node_ids": unresolved, "nodes": rows,
                           "next_chapter_id": graph["chapters"][index + 1]["id"] if passed and index + 1 < len(graph["chapters"]) else None,
                           "advice": "当前证据满足章节规则，可以继续下一单元并保留复习计划。" if passed else
                                     "请教师配置本章必达节点。" if not rule else
                                     "先处理需要补学的节点，再用新任务核验未涉及、冲突、到期或证据不足的节点。"})
        return result

    def handbook(self, graph, learner):
        result = []
        for node in graph["nodes"]:
            state = learner["states"][node["id"]]
            current_raw = [e for e in learner["evidence"] if e["node_id"] == node["id"] and e["course_version"] == graph["version"]]
            prompted = [e["id"] for e in current_raw if (e.get("prompt_level") or 0) > 0]
            annotations = [e["id"] for e in current_raw if e["source_type"] == "annotation"]
            answers = [e for e in current_raw if e["source_type"] in {"quiz", "dialog", "practice"}]
            if state["status"] not in {"needs_review", "uncertain"} and not prompted and not annotations and len(answers) < 2:
                continue
            result.append({"node_id": node["id"], "title": node["title"], "status": state["status"],
                           "reason": state["reason"], "concept": node.get("description", ""),
                           "evidence_ids": list(state["evidence_ids"]), "diagnosis_ids": list(state["diagnosis_ids"]),
                           "prompted_evidence_ids": prompted, "annotation_evidence_ids": annotations,
                           "repeated_submissions": len(answers), "due_at": state["due_at"],
                           "next_step": "换一道未见的新题，减少提示并独立解释，再核验是否掌握。" if prompted else
                                        "结合原始作答和教师反馈补学，随后用新的任务证据复测。"})
        return result

    def report(self, payload):
        def apply(graph, learner, workspace):
            reports = self.chapter_reports(graph, learner)
            report = next((r for r in reports if r["chapter_id"] == payload.get("chapter_id")), None)
            if not report:
                raise CourseGraphError("章节不存在。", 404)
            report["id"] = uuid.uuid4().hex
            report["handbook"] = [h for h in self.handbook(graph, learner) if h["node_id"] in {n["node_id"] for n in report["nodes"]}]
            workspace["reports"].append(report)
            self._event(workspace, "report", report_id=report["id"], chapter_id=report["chapter_id"])
        return self._mutate(payload, "report", apply)

    def teacher_view(self, student_id):
        view = self.view(student_id)
        graph = self.store.load_graph(version=view["course"]["version"]) if view["course"] else None
        tasks = {n["id"]: {"question": n.get("check_question", ""), "expected_answer": n.get("expected_answer", ""),
                             "rubric": n.get("check_task", {}).get("rubric", [])} for n in graph["nodes"]} if graph else {}
        view["teacher_tasks"] = tasks
        if getattr(self.store, "is_demo", False):
            for node in graph["nodes"]:
                variants = self.store.tasks(node)
                tasks[node["id"]]["question"] = "\n\n".join(f"{t['id']}：{t['question']}" for t in variants)
                tasks[node["id"]]["expected_answer"] = "\n\n".join(
                    f"{t['id']}：{t['answer_key']} · {t['explanation']}" for t in variants)
        return view
