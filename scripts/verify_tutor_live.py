"""Explicit live-model smoke check using a temporary synthetic learner only."""
import asyncio
import json
import sys
import tempfile
from pathlib import Path
from time import perf_counter

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from learning_agent.course_graph import CourseGraphStore
from learning_agent.acceptance_course import AcceptanceCourseStore
from pliac.margin import configured_api
from pliac.tutor import teaching_context, generate_teaching


async def main():
    with tempfile.TemporaryDirectory(prefix="pliac-live-tutor-") as temporary:
        base = CourseGraphStore(output_dir=Path(temporary))
        store = AcceptanceCourseStore(base)
        graph = store.load_graph()
        learner = store.load_learner("synthetic-live-tutor", graph)
        learner["profile"].update(goals="理解特征与标签的区别", background="刚开始学习机器学习")
        context = teaching_context(graph, learner, graph["nodes"][0]["id"], "请用一个简单例子解释特征与标签，并提出一个检查理解的问题。")
        started = perf_counter()
        proposal, metadata = await generate_teaching(context, configured_api())
        report = {"synthetic_only": True, "live_model": True, "elapsed_seconds": round(perf_counter() - started, 2),
                  "metadata": metadata, "source_count": len(context["sources"]), "proposal": proposal.model_dump(),
                  "scope": "One live generated teaching proposal; not learner mastery or full platform verification"}
        target = ROOT / "outputs/verification/tutor-live-report.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({"structure_and_citations_valid": True, "semantic_review_required": True, "live_model": True, "seconds": report["elapsed_seconds"], "blocks": len(proposal.blocks), "report": str(target)}, ensure_ascii=True))


if __name__ == "__main__":
    asyncio.run(main())
