"""Real-model smoke test using labelled synthetic learners, never real records."""
import asyncio
import json
from pathlib import Path
import sys
import tempfile
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "scripts")]
from pliac import journey, assistant_memory as memory, assistant_profile as profiles
from pliac.assistant import ChatProvider
from pliac.margin import configured_api
from build_linux_course import DEST


async def main():
    config = configured_api().model_copy(update={"timeout_seconds": 120})
    graph = json.loads((DEST / "course.json").read_text(encoding="utf-8"))
    by_id = {n["id"]: n for n in graph["nodes"]}
    profile = dict(goals="理解Shell和当前工作目录，为Shell自动化打基础", background="会输入几个Linux命令", interests=["自动化"])
    assessments = {n: {"value": "confident" if n in {"shell", "cwd"} else "new"} for n in by_id}
    learner = dict(profile=profile, workspace={"self_assessments": assessments})
    questions = journey.questions(graph, profile, assessments)
    records = []
    for scenario in ("overconfident", "corrected"):
        evidence = []
        for q in questions:
            text = {"shell": "终端就是Linux内核，Shell只负责显示字符。",
                    "cwd": "执行ls /tmp就把当前工作目录切换到了/tmp。"}.get(q["node_id"], "这部分我还没学过。")
            if scenario == "corrected" and q["node_id"] in {"shell", "cwd"}:
                text = by_id[q["node_id"]].get("expected_answer") or "这部分我还没学过。"
            evidence.append(dict(id=uuid.uuid4().hex, **q, text=text, origin="synthetic_learner"))
        current = dict(evidence=evidence, self_assessments=assessments, questions=questions)
        started = time.monotonic()
        async with journey.JourneyProvider(config) as provider:
            result = await provider.plan(journey.model_context(graph, learner, current))
        route, diagnoses = journey.build_route(graph, learner, current, result)
        records.append(dict(scenario=scenario, route=route, diagnoses=diagnoses,
                            elapsed_seconds=round(time.monotonic() - started, 2)))
        print(scenario, [c["calibration"] for c in route["calibration"]], flush=True)
    beginner_assessments = {n: {"value": "new"} for n in by_id}
    beginner = dict(profile={**profile, "background": "第一次学习Linux命令"},
                    workspace={"self_assessments": beginner_assessments})
    beginner_questions = journey.questions(graph, beginner["profile"], beginner_assessments)
    beginner_current = dict(evidence=[], self_assessments=beginner_assessments, questions=beginner_questions)
    started = time.monotonic()
    async with journey.JourneyProvider(config) as provider:
        beginner_result = await provider.plan(journey.model_context(graph, beginner, beginner_current))
    beginner_route, beginner_diagnoses = journey.build_route(graph, beginner, beginner_current, beginner_result)
    records.append(dict(scenario="beginner_without_assessment", route=beginner_route,
                        diagnoses=beginner_diagnoses, elapsed_seconds=round(time.monotonic() - started, 2)))
    print("beginner_without_assessment", len(beginner_route["steps"]), "steps", flush=True)
    with tempfile.TemporaryDirectory() as temp:
        folder = Path(temp)
        conversation = uuid.uuid4().hex
        user = dict(id=uuid.uuid4().hex, role="user", content="实验结果路径是 /tmp/plc_probe_729/result.json。", status="complete",
                    created_at="2026-10-20T00:00:00+00:00", context={})
        old = dict(id=conversation, messages=[user, dict(id=uuid.uuid4().hex, role="assistant",
                   content="已了解实验结果的位置。", status="complete")])
        (folder / f"{conversation}.json").write_text(json.dumps(old, ensure_ascii=False), encoding="utf-8")
        memory.remember(folder, old, user, profiles.TutorReply(answer="记录", memory_note=dict(
            summary="实验结果存放位置", quote="实验结果路径", subject="实验结果", domain="coding")), 0)
        new = dict(id=uuid.uuid4().hex, messages=[dict(id=uuid.uuid4().hex, role="user", status="complete",
                   content="plc_probe_729 的实验结果文件完整路径是什么？", context={})])
        messages, recalled, metrics = memory.prepare(folder, new, {})
        async with ChatProvider(config) as provider:
            answer = await provider.chat(messages, dict(memory=recalled, references=[], personalization={}))
    checks = dict(
        overconfidence_detected=any(c["calibration"]=="overestimated" for c in records[0]["route"]["calibration"]),
        correction_recognized=any(c["calibration"]=="calibrated_confident" for c in records[1]["route"]["calibration"]),
        only_prior_knowledge_tested=all(q["self_assessment"] != "new" for q in questions) and len(questions) <= 3,
        beginner_skips_assessment=not beginner_questions and not beginner_diagnoses and not beginner_route["calibration"],
        beginner_complete_route=len(beginner_route["steps"]) == len(by_id),
        omitted_detail_recalled="/tmp/plc_probe_729/result.json" in answer.answer,
        memory_budget_bounded=metrics["selected_chars"]<=metrics["budget"],
    )
    output = ROOT / "outputs/verification/journey/live-model.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(dict(synthetic=True, model=config.model, checks=checks,
                                      assessments=records, memory_answer=answer.answer, metrics=metrics),
                                 ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(checks, ensure_ascii=False), flush=True)
    if not all(checks.values()):
        raise SystemExit("Inspect synthetic live-model report: " + str(output))


if __name__ == "__main__":
    asyncio.run(main())
