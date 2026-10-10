"""Browser refresh and cached explanation-assessment recovery; synthetic only."""
import asyncio
import json
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

from playwright.sync_api import expect, sync_playwright
from test_ui_documents import isolated_application, ROOT
from test_learning_workspace import platform_fixture, publish_synthetic
from learning_agent.course_graph import CourseGraphError
from pliac.assessment import AssessmentService
from pliac.tutor import AssessmentProposal


def main():
    calls = []
    saves = []
    original_save = AssessmentService.save_result

    async def model(record, config):
        calls.append(record["id"])
        await asyncio.sleep(2)
        return AssessmentProposal(criteria=[{"criterion_id": item["id"], "outcome": "met", "quote": record["answer"],
            "reason": "合成测试标准核对，不代表真实教学评价。"} for item in record["rubric"]],
            feedback="合成评价已恢复。", follow_up_question=""), {"model": "synthetic"}

    def save(service, *args):
        saves.append(True)
        if len(saves) == 1:
            raise CourseGraphError("synthetic commit interruption", 503)
        return original_save(service, *args)

    with tempfile.TemporaryDirectory(prefix="assessment-recovery-") as directory:
        with isolated_application(Path(directory)) as (base, store, _), patch("pliac.tutor_api.configured_api", return_value=object()), patch("pliac.tutor_api.evaluate_answer", model), patch.object(AssessmentService, "save_result", save), sync_playwright() as playwright:
            graph = platform_fixture()
            current = store.load_graph("draft")
            graph.update(id=current["id"], version=current["version"])
            publish_synthetic(store, graph)
            browser = playwright.chromium.launch(channel=os.environ.get("PLIAC_BROWSER_CHANNEL") or None)
            page = browser.new_page(viewport={"width": 1440, "height": 960})
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.goto(base + "/app/courses/" + graph["id"])
            panel = page.get_by_role("region", name="理解核验")
            panel.get_by_role("button", name="开始核验").click()
            panel.get_by_role("textbox", name="你的解释").fill("synthetic saved answer")
            panel.get_by_role("button", name="保存作答").click()
            expect(panel).to_contain_text("作答已保存，尚未形成评价")
            panel.get_by_role("button", name="按标准评价").click()
            expect(panel.get_by_role("status")).to_be_visible()
            saved = page.evaluate("""() => Object.entries(localStorage).filter(([key]) => key.startsWith('pliac.assessment-request:')).map(([key,value]) => ({key, ...JSON.parse(value)}))""")
            pending = next(item for item in saved if 'evaluate' in item['signature'])
            ident = json.loads(pending["signature"])["fields"]["assessment_id"]
            student = page.evaluate("localStorage.getItem('pliac.local-learner')")
            page.reload()
            expect(panel).to_contain_text("synthetic saved answer")
            for _ in range(60):
                status = page.request.get(base + f'/api/tutor/jobs/assessment-{ident}-v{pending["expected"]}?course_id={graph["id"]}&student_id={student}')
                if status.ok and status.json()["status"] == "generated" and saves:
                    break
                page.wait_for_timeout(100)
            assert status.ok and status.json()["status"] == "generated" and saves
            panel.get_by_role("button", name="按标准评价").click()
            expect(panel).to_contain_text("合成评价已恢复。")
            assert len(calls) == 1, calls
            learner = store.load_learner(student)
            assert len(learner["evidence"]) == 1 and len(learner["diagnoses"]) == 1
            assert not errors, errors
            output = ROOT / "outputs" / "verification"
            output.mkdir(parents=True, exist_ok=True)
            panel.screenshot(path=str(output / "assessment-recovery.png"))
            print("PASS browser refresh, saved answer, cached evaluation, one model call, one diagnosis")
            browser.close()


if __name__ == "__main__":
    main()
