"""Whitelisted activity events alongside media, without psychological inference."""
from datetime import datetime

LABELS = {"ml_lab_check": "实验成果检查", "ml_lab_hint": "查看实验提示", "ml_lab_support_choice": "选择实验帮助方式",
          "assessment_started": "开始核验", "assessment_submitted": "保存核验作答", "assessment_diagnosed": "形成核验结果",
          "teaching_reading_finished": "选择继续学习", "tutor_replied": "保存教学回复"}


def activity_timeline(store, student, session):
    if session["status"] in {"revoked", "expired"}:
        return {"items": [], "truncated": False}
    field = {"lab": "session_id", "assessment": "assessment_id", "material": "turn_id"}.get(session["activity_kind"])
    if not field:
        return {"items": [], "truncated": False}
    events = store._read_learner(student).get("workspace", {}).get("events", [])
    clips = session["clips"]
    end = max((clip["start_ms"] + clip["duration_ms"] for clip in clips), default=0)
    items = []
    for event in events:
        kind = event.get("kind")
        key = "request_id" if session["activity_kind"] == "material" and kind == "tutor_replied" else field
        if kind not in LABELS or event.get(key) != session["activity_id"]:
            continue
        try:
            stamp = datetime.fromisoformat(event["created_at"].replace("Z", "+00:00"))
            if stamp.tzinfo is None:
                continue
            relative = (stamp.timestamp() - session["started"]) * 1000
        except (KeyError, ValueError, TypeError):
            continue
        if relative < 0 or relative > end:
            continue
        sequences = [clip["sequence"] for clip in clips if clip["start_ms"] <= relative < clip["start_ms"] + clip["duration_ms"]]
        item = {"id": event["id"], "label": LABELS[kind], "relative_ms": round(relative), "sequences": sequences}
        if kind == "ml_lab_check" and type(event.get("passed")) is bool:
            item["detail"] = "成果检查通过，不等于概念掌握" if event["passed"] else "成果检查未通过，不代表情绪判断"
        if kind == "ml_lab_support_choice":
            item["detail"] = {"hint": "选择分步提示", "continue": "选择继续尝试"}.get(event.get("choice"), "")
        items.append(item)
    items.sort(key=lambda item: (item["relative_ms"], item["id"]))
    return {"items": items[-200:], "truncated": len(items) > 200}
