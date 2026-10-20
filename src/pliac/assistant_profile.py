"""Evidence-attributed, editable learning preferences and dialogue estimates.

Weights are retrieval priorities, not calibrated probabilities of mastery.
"""
import hashlib
import json
import math
import re
from collections import Counter
from datetime import datetime, timezone
from pydantic import BaseModel, Field, model_validator
from typing import Literal
from learning_agent.course_graph import _atomic_json

POLICY = "assistant-profile-v1"
CATEGORIES = {"goal": "学习目标", "interest": "兴趣", "background": "知识背景", "preference": "讲解偏好"}
SLOTS = {
    "goal": {"current_goal"},
    "interest": {"topic"},
    "background": {"experience"},
    "preference": {"detail", "format", "pace", "language", "examples", "tone"},
}


class MemoryUpdate(BaseModel):
    category: Literal["goal", "interest", "background", "preference"]
    slot: Literal["current_goal", "topic", "experience", "detail", "format", "pace", "language", "examples", "tone"]
    value: str = Field(min_length=1, max_length=240)
    quote: str = Field(min_length=2, max_length=600)
    basis: Literal["explicit", "inferred"]

    @model_validator(mode="after")
    def category_matches_slot(self):
        if self.slot not in SLOTS[self.category]:
            raise ValueError("slot must belong to the selected profile category")
        return self


class Diagnosis(BaseModel):
    concept_id: str = Field(max_length=160)
    quote: str = Field(min_length=2, max_length=600)
    signal: Literal["misconception", "partial", "correct", "question"]
    reason: str = Field(min_length=1, max_length=500)
    check_question: str = Field(max_length=500)
    source_ids: list[str] = Field(max_length=4)


class MemoryNote(BaseModel):
    summary: str = Field(min_length=1, max_length=400)
    quote: str = Field(min_length=2, max_length=600)
    domain: Literal["learning", "work", "coding", "general"]
    subject: str = Field(min_length=1, max_length=100)
    kind: Literal["task", "decision", "experience"] = "task"
    supersedes: list[str] = Field(default_factory=list, max_length=3)


class TutorReply(BaseModel):
    answer: str = Field(min_length=1, max_length=48000)
    diagnosis: list[Diagnosis] = Field(default_factory=list, max_length=3)
    profile_updates: list[MemoryUpdate] = Field(default_factory=list, max_length=5)
    memory_note: MemoryNote | None = None


def tokens(text):
    text = str(text).lower()
    return re.findall(r"[a-z0-9_]+", text) + [
        part[i:i+2] for part in re.findall(r"[\u4e00-\u9fff]+", text)
        for i in range(max(1, len(part)-1))]


def rank_documents(query, documents):
    """BM25 with CJK bigrams, deterministic tie order, no model/network indexing."""
    bags = [Counter(tokens(text)) for text in documents]
    average = sum(map(lambda b: sum(b.values()), bags)) / max(1, len(bags)) or 1
    df = Counter(t for bag in bags for t in bag)
    scores = []
    for bag in bags:
        score = 0.
        for term in set(tokens(query)):
            frequency = bag.get(term, 0)
            if frequency:
                inverse = math.log(1 + (len(bags)-df[term]+.5)/(df[term]+.5))
                score += inverse * frequency * 2.2 / (frequency + 1.2*(.25+.75*sum(bag.values())/average))
        scores.append(score)
    return scores


def load(folder):
    path = folder / "profile" / "current.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {
        "policy": POLICY, "revision": 0, "enabled": True, "items": [], "dismissed": [], "concepts": {}}


def save(folder, profile):
    profile["revision"] += 1
    _atomic_json(folder / "profile" / "current.json", profile)


def weight(item, now=None):
    age = max(0, ((now or datetime.now(timezone.utc))-datetime.fromisoformat(item["updated_at"])).total_seconds()/86400)
    half_life = 30 if item["category"] == "interest" else (180 if item["basis"] in {"explicit", "edited"} else 45)
    strength = {"edited": 1., "explicit": .9, "inferred": .45}[item["basis"]]
    return strength * (1 + min(item.get("observations", 1)-1, 4)*.1) * 2**(-age/half_life)


def relevant(profile, question, course_id=""):
    if not profile["enabled"]:
        return dict(preferences=[], learning_focus=[])
    items = [i for i in profile["items"] if i["active"]]
    scores = rank_documents(question, [i["value"] for i in items])
    ranked = sorted(zip(items, scores), key=lambda row: weight(row[0])*(1+row[1]), reverse=True)
    preferences = [{k: i[k] for k in ("id", "category", "slot", "value", "basis")} for i, score in ranked
                   if weight(i) > .15 and (score > 0 or i["category"] in {"preference", "goal"})][:8]
    focus = sorted([c for c in profile["concepts"].values() if c["course_id"] == course_id],
                   key=lambda c: c["updated_at"], reverse=True)[:5] if course_id else []
    return dict(preferences=preferences, learning_focus=focus)


def apply(folder, reply, user, context, conversation, requested_revision):
    profile = load(folder)
    # User edits/toggles during an in-flight model request always take precedence.
    if not profile["enabled"] or profile["revision"] != requested_revision:
        return [], []
    now = datetime.now(timezone.utc).isoformat()
    accepted = []
    for update in reply.profile_updates:
        if update.quote not in user["content"] or update.slot not in SLOTS[update.category]:
            continue
        scope = update.value.lower() if update.category in {"interest", "background"} else update.slot
        ident = hashlib.sha256(f"{update.category}:{scope}".encode()).hexdigest()[:24]
        if ident in profile["dismissed"]:
            continue
        old = next((i for i in profile["items"] if i["id"] == ident and i["active"]), None)
        if old and (old["basis"] == "edited" or (old["basis"] == "explicit" and update.basis == "inferred")):
            continue
        evidence = dict(conversation_id=conversation, message_id=user["id"], quote=update.quote)
        if old and old["value"] == update.value:
            if evidence not in old["evidence"]:
                old["evidence"] = [*old["evidence"], evidence][-5:]
                old["observations"] += 1
                old["updated_at"] = now
                if update.basis == "explicit":
                    old["basis"] = "explicit"
        else:
            if old:
                old["active"] = False
            profile["items"].append(dict(id=ident, category=update.category, slot=update.slot, value=update.value,
                                         basis=update.basis, evidence=[evidence], observations=1, active=True, updated_at=now))
        accepted.append(ident)
    references = {r["id"]: r for r in context["references"]}
    concepts = {r.get("concept_id"): r for r in context["references"] if r.get("concept_id")}
    diagnoses = []
    labels = {"misconception": "发现理解偏差", "partial": "需要补全推理", "correct": "本轮解释清楚", "question": "正在核验"}
    for candidate in reply.diagnosis:
        ref = concepts.get(candidate.concept_id)
        if not ref or candidate.quote not in user["content"] or not candidate.source_ids:
            continue
        if any(s not in references for s in candidate.source_ids):
            continue
        if not any(references[s].get("concept_id") == candidate.concept_id for s in candidate.source_ids):
            continue
        row = candidate.model_dump() | dict(concept_title=ref["title"], label=labels[candidate.signal],
                                          course_id=context.get("course_id", ""), updated_at=now,
                                          origin="model_inference", message_id=user["id"], conversation_id=conversation,
                                          policy=POLICY)
        diagnoses.append(row)
        key = row["course_id"] + ":" + candidate.concept_id
        previous = profile["concepts"].get(key, {})
        row["observations"] = previous.get("observations", 0) + 1
        profile["concepts"][key] = row
    profile["items"] = profile["items"][-200:]
    profile["concepts"] = dict(sorted(profile["concepts"].items(), key=lambda item:item[1]["updated_at"])[-200:])
    if accepted or diagnoses:
        _atomic_json(folder / "profile" / "evidence" / (user["id"] + ".json"),
                     dict(user_message_id=user["id"], conversation_id=conversation, diagnosis=diagnoses,
                          accepted_memory_ids=accepted, policy=POLICY))
        save(folder, profile)
    return diagnoses, accepted
