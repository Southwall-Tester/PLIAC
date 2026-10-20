"""Real-model choice generation with synthetic artifacts and temporary learners."""
import asyncio
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import time
import uuid
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from learning_agent.acceptance_course import AcceptanceCourseStore
from learning_agent.course_graph import CourseGraphStore
from learnmargin.demo import demo_lesson
from learnmargin.models import GeneratedPractice
from learnmargin.pipeline import BASE_SYSTEM
from learnmargin.provider import Provider
from learnmargin.storage import atomic_json
from pliac import choice_generation, handout_practice, learning_scope, margin


async def main():
    config = margin.configured_api()
    report = {"synthetic_material": True, "live_model": True, "model": config.model, "checks": []}
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="pliac-choice-live-") as temporary:
        course = AcceptanceCourseStore(CourseGraphStore(output_dir=Path(temporary)))
        store = margin.storage(course)
        graph = course.load_graph()
        scope = learning_scope.resolve(graph, {"node_id": graph["nodes"][0]["id"]}, store)
        job = dict(id=uuid.uuid4().hex, status="completed", created_at=margin.now(),
                   course_id=graph["id"], course_version=graph["version"], scope=scope,
                   chapter_id=scope["chapter_id"], title="合成旧讲义选项验证")
        store.save_job(job)
        path = store.directory("jobs", job["id"]) / "lesson.json"
        atomic_json(path, demo_lesson().model_dump())
        original = hashlib.sha256(path.read_bytes()).hexdigest()
        await handout_practice.prepare_choices(store, job["id"])
        state = handout_practice.view(course, store, job["id"], "synthetic-choice-smoke")
        assert len(state["questions"]) == 2
        assert all(3 <= len(item["options"]) <= 4 for item in state["questions"])
        assert all(item["prompt"] == item["original_prompt"] for item in state["questions"])
        assert all("answer_key" not in item and item["answer"] is None for item in state["questions"])
        with patch.object(choice_generation.ChoiceProvider, "choices", side_effect=AssertionError("cache miss")):
            await handout_practice.prepare_choices(store, job["id"])
        assert hashlib.sha256(path.read_bytes()).hexdigest() == original
        question = state["questions"][0]
        state = handout_practice.mutate(course, store, job["id"], {
            "student_id": "synthetic-choice-smoke", "expected_version": state["version"],
            "request_id": uuid.uuid4().hex, "operation": "answer", "question_id": question["id"],
            "choice_id": question["options"][0]["id"], "option_set_id": question["option_set_id"], "text": ""})
        learner = course._read_learner("synthetic-choice-smoke")
        assert state["answered"] == 1 and learner["diagnoses"] == []
        assert learner["evidence"][0]["context"]["supplement"] == ""
        report["legacy_questions"] = handout_practice.questions(store, job["id"])
        report["checks"] += ["Two old short-answer questions receive task-specific options",
                            "Original artifact unchanged; repeated preparation hits the saved cache",
                            "Choice-only submission preserves raw evidence without a diagnosis"]
    async with Provider(config) as provider:
        generated = await provider.generate(
            GeneratedPractice, BASE_SYSTEM,
            "生成一题：同一划分下，深度1决策树训练准确率0.72、验证0.70；自由生长树训练1.00、验证0.64。"
            "请学习者选择最符合这些结果的解释。只输出一道GeneratedPractice，3至4个具体答案，"
            "独立参考解析；不让学习者必填文字。")
    report["native_practice"] = generated.model_dump()
    report["checks"].append("New practice generation satisfies the native concrete-option schema")
    report["elapsed_seconds"] = round(time.monotonic() - started, 2)
    report["passed"] = True
    output = ROOT / "outputs/verification/handout-choices-live.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"passed": True, "checks": len(report["checks"]),
                      "elapsed_seconds": report["elapsed_seconds"]}, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
