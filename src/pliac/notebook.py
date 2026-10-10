"""Learner-authored, revisioned notes; not independent mastery evidence."""
import uuid

from learning_agent.course_graph import CourseGraphError, _text
from .workspace import LearningWorkspace


class Notebook(LearningWorkspace):
    def save(self, payload):
        def apply(graph, learner, workspace):
            node = self.store._node(graph, payload.get("node_id"))
            text = _text(payload.get("text", ""), "学习笔记", 8000, False)
            notes = workspace.setdefault("notes", {})
            history = notes.setdefault(node["id"], [])
            if len(history) >= 100:
                raise CourseGraphError("此知识点已有 100 个笔记版本，请先归档。", 409)
            material_id = payload.get("material_id")
            if material_id and not any(turn["request_id"] == material_id
                and turn["proposal"]["target_node_id"] == node["id"] for turn in workspace.get("tutor_turns", [])):
                raise CourseGraphError("笔记引用的学习材料不存在或不属于当前知识点。", 400)
            record = {"id": uuid.uuid4().hex, "revision": len(history) + 1, "node_id": node["id"],
                "text": text, "course_version": graph["version"], "material_id": material_id,
                "origin": "learner_note", "created_at": self.store._stamp()}
            history.append(record)
            self._event(workspace, "note_saved", note_id=record["id"], node_id=node["id"], revision=record["revision"])
        return self._mutate(payload, "note_save", apply)


def relevant_notes(learner, node_ids):
    records = [history[-1] for node, history in learner.get("workspace", {}).get("notes", {}).items()
               if node in node_ids and history and history[-1]["text"].strip()]
    return sorted(records, key=lambda item: item["created_at"], reverse=True)[:8]
