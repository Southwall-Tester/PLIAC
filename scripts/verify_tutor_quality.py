"""List cases by default. Live execution requires an explicit bounded selection."""
import argparse
import asyncio
import json
import sys
import tempfile
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from learning_agent.acceptance_course import AcceptanceCourseStore
from learning_agent.course_graph import CourseGraphStore
from pliac.margin import configured_api
from pliac.tutor import generate_teaching
from pliac.tutor_quality import CASES, evaluate_cases


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="Calls the configured paid provider with synthetic contexts.")
    parser.add_argument("--case", action="append", choices=[case["id"] for case in CASES], default=[])
    parser.add_argument("--max-cases", type=int, default=0)
    args = parser.parse_args()
    if not args.live:
        print(json.dumps({"live_model": False, "cases": CASES}, ensure_ascii=False, indent=2))
        return
    if not args.case or not 1 <= args.max_cases <= len(CASES) or len(set(args.case)) > args.max_cases:
        parser.error(f"Live execution needs explicit --case selections and --max-cases from 1 to {len(CASES)}.")
    config = configured_api()
    if config is None:
        parser.error("No configured provider; no model call was made.")
    selected = [case for case in CASES if case["id"] in args.case]
    with tempfile.TemporaryDirectory(prefix="pliac-quality-") as directory:
        store = AcceptanceCourseStore(CourseGraphStore(output_dir=Path(directory)))
        report = asyncio.run(evaluate_cases(store, selected, generate_teaching, config, live_model=True))
    target = ROOT / "outputs/verification" / ("tutor-quality-" + uuid.uuid4().hex + ".json")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"report": str(target), "cases": len(selected), "semantic_review_required": True}))


if __name__ == "__main__":
    main()
