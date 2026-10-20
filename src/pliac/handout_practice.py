"""Artifact-scoped practice in the shared learner store; never an auto-diagnosis."""
import copy
import hashlib
import json
import uuid

from learning_agent.course_graph import CourseGraphError, _dict, _text, _integer, safe_id
from .learning_scope import saved, job_scope
from .workspace import empty_workspace
from .answer_options import build_choice_bundle


def question_items(store, job_id):
    lesson = saved(store, job_id, "lesson.json")
    result = []
    for section in lesson["sections"]:
        items = [dict(item, kind="practice") for item in section.get("practice", [])]
        items += [{**item, "id": "prompt:" + item["id"], "prompt": item["task"], "hint": item.get("check", ""),
                   "kind": "study_question"} for item in section.get("study_prompts", []) if item.get("kind") == "question"]
        for item in items:
            result.append((section, item))
    return result


async def prepare_choices(store, job_id):
    """Upgrade legacy questions in a separate cache, preserving the artifact."""
    from .choice_generation import prepare_choice_requests
    requests = [{"scope": f"handout:{job_id}:{section['id']}:{item['id']}",
                 "prompt": item["prompt"], "reference_answer": item["answer"],
                 "context": section["explanation"]}
                for section, item in question_items(store, job_id) if len(item.get("options", [])) < 2]
    if requests:
        await prepare_choice_requests(requests, store.directory("jobs", job_id) / "answer_options")


def questions(store, job_id):
    result = []
    for section, item in question_items(store, job_id):
        ident = f"{section['id']}:{item['id']}"
        bundle = build_choice_bundle(item["prompt"], item["answer"], context=section["explanation"],
                                     alternatives=item.get("misconceptions", []),
                                     existing_options=item.get("options", []), answer_key=item.get("answer_key", ""),
                                     scope=f"handout:{job_id}:{ident}")
        if item.get("options"):
            bundle["origin"] = "handout_artifact"
        result.append({**item, **bundle, "id": ident, "original_prompt": item["prompt"],
                       "section_id": section["id"], "section_title": section["title"],
                       "source_refs": section["source_refs"]})
    return result


def view(course, store, job_id, student_id):
    safe_id(student_id, "匿名编号")
    items = questions(store, job_id)
    learner = course._read_learner(student_id)
    record = learner.get("workspace", {}).get("handout_practice", {}).get(job_id, {})
    public = []
    for item in items:
        exposure = record.get("exposures", {}).get(item["id"], 0)
        public.append({**{k: v for k, v in item.items() if k not in {"hint", "check", "answer", "answer_key"}},
                       "hint": item["hint"] if exposure >= 1 else None,
                       "answer": item["answer"] if exposure >= 2 else None, "exposure": exposure})
    responses = record.get("responses", [])
    return {"student_id": student_id, "version": learner["version"], "job_id": job_id,
            "questions": public, "drafts": record.get("drafts", {}), "responses": copy.deepcopy(responses),
            "choice_drafts": record.get("choice_drafts", {}),
            "answered": len({r["question_id"] for r in responses}), "total": len(items)}


def mutate(course, store, job_id, payload):
    _dict(payload, "练习请求")
    student = safe_id(payload.get("student_id"), "匿名编号")
    receipt = safe_id(payload.get("request_id"), "请求编号")
    expected = _integer(payload.get("expected_version"), "预期学习记录版本")
    operation = payload.get("operation")
    if operation not in {"draft", "hint", "solution", "answer"}:
        raise CourseGraphError("练习操作无效。")
    question = next((q for q in questions(store, job_id) if q["id"] == payload.get("question_id")), None)
    if not question:
        raise CourseGraphError("这道题不属于当前学习单元。", 404)
    choice_id = payload.get("choice_id", "")
    if not isinstance(choice_id, str):
        raise CourseGraphError("答案选项无效。")
    choice = next((option for option in question["options"] if option["id"] == choice_id), None) if choice_id else None
    if choice_id and not choice:
        raise CourseGraphError("请选择这道题提供的答案。")
    if choice and payload.get("option_set_id") != question["option_set_id"]:
        raise CourseGraphError("题目选项已更新，请重新选择。", 409)
    signature = hashlib.sha256(json.dumps({k: v for k, v in payload.items() if k != "expected_version"},
                                         sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    with course._writer():
        learner = course._read_learner(student)
        workspace = learner.setdefault("workspace", empty_workspace())
        unit = workspace.setdefault("handout_practice", {}).setdefault(job_id, {"drafts": {}, "responses": [], "exposures": {}, "receipts": {}})
        previous = unit["receipts"].get(receipt)
        if previous:
            if previous != signature:
                raise CourseGraphError("同一请求编号不能用于不同作答。", 409)
        else:
            course._expected(learner, expected)
            if len(unit["receipts"]) >= 5000:
                raise CourseGraphError("本单元学习记录已达到容量，请先导出归档。", 409)
            ident = question["id"]
            if operation == "draft":
                unit["drafts"][ident] = _text(payload.get("text", ""), "作答草稿", 4000, False)
                unit.setdefault("choice_drafts", {})[ident] = choice_id
            elif operation in {"hint", "solution"}:
                unit["exposures"][ident] = max(unit["exposures"].get(ident, 0), 1 if operation == "hint" else 2)
            else:
                job = store.job(job_id)
                supplement = _text(payload.get("text", ""), "补充说明", 4000, False)
                if not choice and not supplement:
                    raise CourseGraphError("请选择一个答案。")
                text = (f"选择 {choice['id']}：{choice['text']}" + (f"\n补充说明：{supplement}" if supplement else "")
                        if choice else supplement)
                evidence = {"id": uuid.uuid4().hex, "student_id": student, "course_id": job["course_id"],
                    "course_version": job["course_version"], "node_id": "", "node_fingerprint": "",
                    "source_type": "practice", "origin": "learner_expression", "text": text,
                    "prompt_level": unit["exposures"].get(ident, 0), "expressed_relations": [], "created_at": course._stamp(),
                    "context": {"job_id": job_id, "scope": job_scope(job), "question_id": ident,
                                "question": question["prompt"], "source_refs": question["source_refs"],
                                "original_question": question["original_prompt"],
                                "answer_mode": question["answer_mode"] if choice else "free_text",
                                "selected_option": copy.deepcopy(choice), "supplement": supplement,
                                "option_set_id": question["option_set_id"] if choice else "",
                                "option_origin": question["origin"] if choice else "",
                                "assessment_origin": "unreviewed_generated_practice"}}
                # The generated question is not a reviewed node task. Preserve
                # provenance without assigning a diagnosis to every parent node.
                learner["evidence"].append(evidence)
                unit["responses"].append({"question_id": ident, "evidence_id": evidence["id"], "text": text,
                                           "choice_id": choice_id, "supplement": supplement,
                                           "option_set_id": question["option_set_id"] if choice else "",
                                           "exposure": evidence["prompt_level"], "created_at": evidence["created_at"]})
                unit["drafts"].pop(ident, None)
                unit.setdefault("choice_drafts", {}).pop(ident, None)
            unit["receipts"][receipt] = signature
            course._commit(learner)
    return view(course, store, job_id, student)
