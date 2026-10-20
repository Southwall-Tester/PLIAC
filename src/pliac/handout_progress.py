"""Persist real handout milestones and bounded model-transport activity."""
from __future__ import annotations

import asyncio
from time import monotonic

from learnmargin.storage import now

STEPS = (
    ("reading", "读取资料"),
    ("planning", "安排讲解"),
    ("writing", "编写与检查"),
    ("graph", "构建图谱"),
    ("rendering", "排版讲义"),
)
PHASES = [key for key, _ in STEPS]
TERMINAL = {"completed", "failed", "cancelled"}


def phase_for(amount):
    if amount < 24:
        return "reading"
    if amount < 35:
        return "planning"
    if amount < 82:
        return "writing"
    if amount < 88:
        return "graph"
    return "rendering"


def _label(value, limit=180):
    return " ".join(str(value or "").split())[:limit]


def _count(value):
    return min(max(value, 0), 100_000_000) if type(value) is int else 0


def finish_progress(job, status, timestamp=None):
    """Stop persisted clocks, including recovery after a service interruption."""
    detail = job.get("progress_detail")
    if not isinstance(detail, dict):
        return
    timestamp = timestamp or now()
    detail.update(finished_at=timestamp, updated_at=timestamp, heartbeat_at=timestamp)
    for step in detail.get("steps", []):
        if status == "completed" or step["status"] == "running":
            step["status"] = status
    for task in detail.get("tasks", []):
        if task["status"] == "running":
            task.update(status=status, updated_at=timestamp)
    if detail.get("request"):
        request = detail["request"]
        if request["status"] not in TERMINAL:
            request.update(status=status, updated_at=timestamp)
        request["active_count"] = 0
    if status == "completed":
        job["progress"] = 100
        detail["current_task"] = "讲义已准备好"
    else:
        detail["current_task"] = job.get("failed_stage") or job.get("stage") or detail["current_task"]


class ProgressReporter:
    """A legacy-compatible progress callback with concurrent task details.

    Percentages change only when the pipeline reports a real milestone.
    Heartbeats and received characters never advance a completion percentage.
    """

    def __init__(self, store, job):
        self.store, self.job = store, job
        self.requests = {}
        self._last_save = 0.0
        self._closed = False
        stamp = now()
        job["progress"] = 0
        self.data = {
            "version": 1, "phase": "reading", "current_task": "读取课程资料",
            "started_at": stamp, "stage_started_at": stamp,
            "updated_at": stamp, "heartbeat_at": stamp,
            "steps": [{"id": key, "label": label, "status": "running" if index == 0 else "pending"}
                      for index, (key, label) in enumerate(STEPS)],
            "tasks": [], "sections": {"completed": 0, "total": 0}, "request": None,
        }
        job["progress_detail"] = self.data

    def _save(self, *, force=False):
        if self._closed:
            return
        tick = monotonic()
        if force or tick - self._last_save >= .75:
            self.data["updated_at"] = now()
            self.store.save_job(self.job)
            self._last_save = tick

    def _phase(self, phase):
        if phase not in PHASES:
            return
        index = PHASES.index(phase)
        # Concurrent completions from an earlier task must not move the phase back.
        if index < PHASES.index(self.data["phase"]):
            return
        if phase != self.data["phase"]:
            self.data.update(phase=phase, stage_started_at=now())
        for i, step in enumerate(self.data["steps"]):
            step["status"] = "completed" if i < index else "running" if i == index else "pending"

    def __call__(self, stage, amount):
        if self._closed:
            return
        amount = max(0, min(99, int(amount)))
        self._phase(phase_for(amount))
        self.job.update(stage=_label(stage), progress=max(self.job.get("progress", 0), amount))
        active = [task["label"] for task in self.data["tasks"]
                  if task["status"] == "running" and task["phase"] == self.data["phase"]]
        self.data["current_task"] = "；".join(active[-3:]) or _label(stage)
        self._save(force=True)

    def detail(self, event):
        if self._closed or not isinstance(event, dict):
            return
        ident = _label(event.get("task_id"), 90)
        status = event.get("status")
        if not ident or status not in {"running", *TERMINAL} or event.get("phase") not in PHASES:
            return
        self._phase(event["phase"])
        stamp = now()
        tasks = self.data["tasks"]
        task = next((item for item in tasks if item["task_id"] == ident), None)
        if task is None:
            if len(tasks) >= 120:
                # Retain every active task and the most recent completed tasks.
                tasks[:] = [item for item in tasks if item["status"] == "running"] + [
                    item for item in tasks if item["status"] != "running"][-90:]
            task = {"task_id": ident, "started_at": stamp}
            tasks.append(task)
        task.update(label=_label(event.get("label")), status=status, phase=event["phase"], updated_at=stamp)
        for key in ("section_index", "section_total", "attempt"):
            if type(event.get(key)) is int:
                task[key] = _count(event[key])
        self.data["sections"]["total"] = max(self.data["sections"]["total"], task.get("section_total", 0))
        if status == "completed" and ident.endswith(":validate") and task.get("section_index"):
            completed = getattr(self, "_completed_sections", set())
            completed.add(task["section_index"])
            self._completed_sections = completed
            self.data["sections"]["completed"] = len(completed)
        active = [item["label"] for item in tasks if item["status"] == "running"
                  and item["phase"] == self.data["phase"]]
        self.data["current_task"] = "；".join(active[-3:]) or task["label"]
        self._save(force=True)

    def model_event(self, event):
        """Whitelist counters and state; never retain model text or reasoning."""
        if self._closed or not isinstance(event, dict):
            return
        ident = event.get("request_id")
        phase = event.get("phase")
        if not isinstance(ident, str) or len(ident) > 80 or phase not in {
            "request_started", "receiving", "retry", "validating", *TERMINAL
        }:
            return
        stamp = now()
        item = self.requests.get(ident)
        if item is None:
            item = {"started_at": stamp, "last_received_at": None, "received_chars": 0,
                    "reasoning_chars": 0, "attempt": 0}
            self.requests[ident] = item
        status = {"request_started": "waiting", "receiving": "streaming", "retry": "retrying"}.get(phase, phase)
        if phase == "receiving" and event.get("waiting") is True:
            status = "waiting"
        item.update(status=status, updated_at=stamp,
                    received_chars=_count(event.get("response_chars")),
                    reasoning_chars=_count(event.get("reasoning_chars")),
                    attempt=_count(event.get("attempt")))
        if event.get("transport") in {"sse", "json"}:
            item["transport"] = event["transport"]
        if phase == "request_started":
            item["started_at"] = stamp
            item["last_received_at"] = None
        if phase == "receiving" and event.get("waiting") is not True:
            item["last_received_at"] = stamp
        if phase in TERMINAL:
            item["finished_at"] = stamp
        task_id = event.get("task_id")
        task = next((value for value in self.data["tasks"] if value["task_id"] == task_id), None)
        if task is not None:
            # Transport completion is distinct from the pipeline's validation
            # milestone, so it must not mark this task or section completed.
            task.update(model_status=status, received_chars=item["received_chars"],
                        reasoning_chars=item["reasoning_chars"], model_attempt=item["attempt"],
                        last_received_at=item["last_received_at"])
        active = [value for value in self.requests.values() if value["status"] not in TERMINAL]
        current = active or [item]
        latest = max(current, key=lambda value: value["updated_at"])
        receipts = [value["last_received_at"] for value in current if value.get("last_received_at")]
        self.data["request"] = {
            "status": latest["status"], "started_at": min(value["started_at"] for value in current),
            "updated_at": stamp, "last_received_at": max(receipts) if receipts else None,
            "received_chars": sum(value["received_chars"] for value in current),
            "reasoning_chars": sum(value["reasoning_chars"] for value in current),
            "attempt": max(value["attempt"] for value in current), "transport": latest.get("transport", "json"),
            "active_count": len(active),
            "completed_count": sum(value["status"] == "completed" for value in self.requests.values()),
            "total_count": len(self.requests),
        }
        self._save(force=phase != "receiving")

    async def heartbeat(self):
        while not self._closed:
            await asyncio.sleep(3)
            if not self._closed:
                self.data["heartbeat_at"] = now()
                self._save(force=True)

    def finish(self, status):
        if self._closed:
            return
        finish_progress(self.job, status)
        self._save(force=True)
        self._closed = True
