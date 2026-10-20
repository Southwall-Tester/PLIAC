"""Stable selectable responses with explicit recognition evidence provenance.

Authored choices stay intact. Legacy tasks may combine a reference answer with
explicit same-question alternatives, never unrelated neighboring text.
The returned answer_key is private and must be removed from student responses.
"""
from __future__ import annotations

import copy
import hashlib
import json
import threading
from collections import OrderedDict

from learning_agent.course_graph import CourseGraphError, _text

POLICY = "answer-options-v1"
_GENERATED = OrderedDict()
_LOCK = threading.RLock()


def _set_id(scope, bundle):
    # The public identity describes what was displayed, not the private key.
    visible = {key: bundle[key] for key in ("prompt", "original_prompt", "options", "origin", "answer_mode")
               if key in bundle}
    return hashlib.sha256(json.dumps([POLICY, scope, visible], ensure_ascii=False,
                                     sort_keys=True).encode("utf-8")).hexdigest()[:24]


def register_generated(scope, bundle):
    """Register a validated, persisted generation without changing authored data."""
    with _LOCK:
        saved = copy.deepcopy(bundle)
        saved.setdefault("original_prompt", saved["prompt"])
        saved.setdefault("option_set_id", _set_id(scope, saved))
        _GENERATED[scope] = saved
        _GENERATED.move_to_end(scope)
        while len(_GENERATED) > 2048:
            _GENERATED.popitem(last=False)


def get_generated(scope):
    with _LOCK:
        return copy.deepcopy(_GENERATED.get(scope))


def node_choice_request(graph, node, task=None, prompt=None):
    task = task or node.get("check_task") or {}
    values = {"prompt": prompt or task.get("question") or node.get("check_question") or
                       f"请解释“{node['title']}”的含义，并举一个例子。",
              "reference_answer": task.get("expected_answer") or node.get("expected_answer", ""),
              "misconception": node.get("misconception", ""),
              "context": node.get("description", ""),
              "existing_options": copy.deepcopy(task.get("options", [])),
              "answer_key": task.get("answer_key", "")}
    digest = hashlib.sha256(json.dumps(values, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()[:20]
    values["scope"] = f"{graph['id']}:{graph['version']}:{node['id']}:{task.get('id', '')}:{digest}"
    return values


def bundle_for_request(request):
    misconception = str(request.get("misconception", "")).strip()
    for prefix in ("误以为", "认为", "以为"):
        if misconception.startswith(prefix):
            misconception = misconception[len(prefix):].lstrip("：: ")
            break
    # Editorial labels describe an error rather than answer the question.
    # The generation service can rewrite them using the full task; this
    # immediate adapter only reuses an actual declarative answer.
    if misconception.startswith(("把", "混淆", "误将", "忽略", "没有区分", "未区分")):
        misconception = ""
    return build_choice_bundle(
        request["prompt"], request["reference_answer"], context=request.get("context", ""),
        alternatives=[misconception] if misconception else [],
        existing_options=request.get("existing_options", []), answer_key=request.get("answer_key", ""),
        scope=request["scope"])


def build_choice_bundle(prompt: str, answer: str = "", *, context: str = "",
                        alternatives=(), existing_options=(), answer_key: str = "",
                        scope: str = ""):
    original = str(prompt or "").strip()
    authored = []
    for index, item in enumerate(existing_options or ()):
        if isinstance(item, dict):
            ident, text = str(item.get("id", "")), str(item.get("text", "")).strip()
        else:
            ident, text = str(index + 1), str(item).strip()
        if ident and text:
            authored.append({"id": ident, "text": text})
    if len(authored) >= 2 and len({item["id"] for item in authored}) == len(authored):
        displayed, options, correct = original, authored, str(answer_key or "")
        origin, mode = "authored", "recognition"
    else:
        generated = get_generated(scope)
        if generated:
            return generated
        reference = str(answer or "").strip()
        distractors = []
        for value in alternatives or ():
            text = str(value.get("text", "") if isinstance(value, dict) else value).strip()
            if text and text != reference and text not in distractors:
                distractors.append(text)
        if reference and distractors:
            candidates = [(reference, True), *[(text, False) for text in distractors[:3]]]
            candidates.sort(key=lambda item: hashlib.sha256(
                (scope + original + item[0]).encode("utf-8")).hexdigest())
            options = [{"id": chr(65 + index), "text": text}
                       for index, (text, _) in enumerate(candidates)]
            correct = next(options[index]["id"] for index, (_, valid) in enumerate(candidates) if valid)
            displayed, origin, mode = original, "reference_alternatives", "recognition"
        else:
            # No source permits scoring a made-up answer. Offer a concrete
            # teaching action while preserving the original question.
            displayed = f"关于这道题：{original}\n\n你希望先获得哪种讲解？"
            options = [{"id": "explain", "text": "先解释这道题涉及的概念和条件"},
                       {"id": "example", "text": "先用一个完整例子示范解答步骤"}]
            correct, origin, mode = "", "support_request", "support_request"
    result = {"prompt": displayed, "original_prompt": original, "options": options,
              "answer_key": correct, "origin": origin, "answer_mode": mode}
    result["option_set_id"] = _set_id(scope, result)
    return result


def public_bundle(bundle):
    """Only information required to render a frozen task."""
    return {"question": bundle["prompt"], "original_question": bundle["original_prompt"],
            "options": copy.deepcopy(bundle["options"]), "option_set_id": bundle["option_set_id"],
            "option_origin": bundle["origin"], "answer_mode": bundle["answer_mode"]}


def selected_response(question, payload, *, max_text=2000, allow_legacy_text=False):
    """Validate a selection; never attribute an offered option to free recall."""
    free_text = _text(payload.get("text", ""), "补充说明", max_text, False)
    supplied_set = payload.get("option_set_id")
    if supplied_set and supplied_set != question.get("option_set_id"):
        raise CourseGraphError("题目选项已更新，请重新载入后选择。", 409)
    choice = payload.get("choice_id")
    if not choice and allow_legacy_text and free_text:
        return {"text": free_text, "free_text": free_text, "response_mode": "free_text"}
    option = next((item for item in question.get("options", [])
                   if isinstance(choice, str) and item["id"] == choice), None)
    if option is None:
        raise CourseGraphError("请从本题选项中选择一个答案。")
    selection = {"choice_id": choice, "option_text": option["text"],
                 "option_set_id": question.get("option_set_id"),
                 "origin": question.get("option_origin", question.get("origin", "authored")),
                 "answer_mode": question.get("answer_mode", "recognition"),
                 "options": copy.deepcopy(question["options"])}
    text = f"所选答案：{option['text']}" + (f"\n补充说明：{free_text}" if free_text else "")
    return {"text": text, "free_text": free_text, "choice_id": choice,
            "selection": selection, "response_mode": "selection"}
