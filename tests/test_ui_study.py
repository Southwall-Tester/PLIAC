"""Actual sidebar, recovery, cards and separate practice entry; synthetic data."""
import json
import tempfile
import uuid
from pathlib import Path

from playwright.sync_api import expect, sync_playwright
from test_ui_documents import isolated_application
from learning_agent.acceptance_course import build_graph

OUT = Path(__file__).resolve().parents[1] / "outputs/verification"


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    report = {"synthetic_only": True, "page_errors": [], "checks": []}
    try:
        with tempfile.TemporaryDirectory() as tmp, isolated_application(Path(tmp)) as (base, _, _), sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page(viewport={"width": 1440, "height": 1000})
            page.on("pageerror", lambda e: report["page_errors"].append(str(e)))
            student = "synthetic-study-ui"
            url = base + "/api/learning?course_id=ml_acceptance_demo&student_id=" + student
            def view():
                return page.request.get(url).json()
            def act(operation, **fields):
                result = page.request.post(base + "/api/learning/" + operation + "?course_id=ml_acceptance_demo", data={
                    "student_id": student, "course_version": 1, "expected_version": view()["learner"]["version"],
                    "request_id": uuid.uuid4().hex, **fields})
                assert result.ok, result.text()
                return result.json()
            act("onboard")
            for n in build_graph()["nodes"][:3]:
                l = act("next", node_id=n["id"], study_protocol=1)["current_lesson"]
                act("answer", lesson_id=l["id"], choice_id=n["check_task"]["answer_key"], confidence="unsure")
            page.goto(base + "/learn?course_id=ml_acceptance_demo&student_id=" + student + "&view=study")
            expect(page.locator("#questionText")).not_to_be_empty()
            expect(page.locator("#lessonPanel > #restPrompt")).to_be_visible()
            assert view()["rhythm"]["current"]["estimated_minutes"] >= 15
            page.screenshot(path=str(OUT / "study-rest-below-lesson.png"), full_page=True)
            page.locator("#resumeNote").fill("回来从三份数据的用途继续")
            page.locator("#takeBreak").click()
            expect(page.locator("#restText")).to_contain_text("已暂存")
            page.reload()
            expect(page.locator("#resumeNote")).to_have_value("回来从三份数据的用途继续")
            page.locator("#skipBreak").click()
            expect(page.locator("#restPrompt")).to_be_hidden()
            report["checks"].append("Pause below the lesson, optional continuation and return note survive reload")

            page.locator("#chunkEditor summary").click()
            page.locator('[data-card-field="trigger"]').fill("需要选择模型或报告最终表现时")
            page.locator('[data-card-field="steps"]').fill("先拟合，再用验证集选型，最后测试")
            page.locator("#chunkForm button").click()
            expect(page.locator("#cardStatus")).to_have_text("已保存")
            expect(page.locator("#chunkLibrary")).to_contain_text("我的解题卡")
            page.reload()
            expect(page.locator('[data-card-field="steps"]')).to_have_value("先拟合，再用验证集选型，最后测试")
            page.screenshot(path=str(OUT / "study-reading-desktop.png"), full_page=True)
            assert any(card["fields"]["steps"] == "先拟合，再用验证集选型，最后测试"
                       for card in view()["workspace"]["chunk_cards"].values())
            expect(page.locator("#handbookPanel")).to_be_hidden()
            expect(page.locator("#handbook")).to_be_empty()
            report["checks"].append("Learner-authored cards save and restore in the optional editor; the diagnostic handbook stays hidden")

            expect(page.locator("#mixedDialog")).to_be_hidden()
            page.locator("#openMixed").click()
            expect(page.locator("#mixedDialog")).to_be_visible()
            before = len(view()["learner"]["diagnoses"])
            page.locator('[name="mixedChoice"][value="1"]').check()
            expect(page.locator("#mixedReason")).not_to_have_attribute("required", "")
            page.locator("#mixedConfidence").select_option("sure")
            page.locator("#mixedForm button").click()
            expect(page.locator("#mixedHistory")).to_contain_text("选择正确")
            assert len(view()["learner"]["diagnoses"]) == before
            assert view()["study_activities"]["mixed_history"][-1]["reason"] == ""
            page.set_viewport_size({"width":390,"height":844})
            page.evaluate("GraphTheme.toggle()")
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            background = page.locator("#mixedDialog").evaluate("e=>getComputedStyle(e).backgroundColor")
            assert background != "rgb(255, 255, 255)", background
            page.screenshot(path=str(OUT / "study-practice-mobile-dark.png"), full_page=False)
            page.locator("#closeMixed").click()
            report["checks"].append("Mixed practice submits by selection without typed text and preserves diagnoses; mobile dark layout fits")
            assert not report["page_errors"], report["page_errors"]
            browser.close()
    finally:
        (OUT / "study-ui-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
