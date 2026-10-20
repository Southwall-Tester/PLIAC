"""Complete the built-in course with synthetic answers in an isolated browser app."""
import json
import tempfile
import uuid
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

from test_ui_documents import isolated_application
from test_ui_journey import algorithmic_journey, complete_baseline, expect_student_learning_only
from learning_agent.acceptance_course import build_graph, DEMO_ID

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "outputs/verification"


def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    report = {"synthetic_only": True, "persistent_course_store_used": False, "checks": [], "page_errors": []}

    def passed(message):
        report["checks"].append(message)
        print("PASS", message, flush=True)

    try:
        with tempfile.TemporaryDirectory(prefix="pliac-demo-ui-") as temporary:
            with isolated_application(Path(temporary)) as (base, _store, _documents), algorithmic_journey(), sync_playwright() as p:
                browser = p.chromium.launch()
                page = browser.new_page(viewport={"width": 1440, "height": 1000})
                page.on("pageerror", lambda e: report["page_errors"].append(str(e)))
                def saved_state():
                    response = page.request.get(base + "/api/learning", params={
                        "course_id": DEMO_ID, "student_id": "synthetic-course-acceptance"})
                    assert response.ok, response.text()
                    return response.json()
                page.goto(base + "/courses")
                page.locator("[data-course-id=ml_acceptance_demo] .learning-course").click()
                page.locator("#studentId").fill("synthetic-course-acceptance")
                page.locator("#identityForm button[type=submit]").click()
                expect(page.locator("#notice")).to_be_hidden()
                page.locator("#goals").fill("Synthetic: complete the acceptance course")
                page.locator("#onboardForm button[type=submit]").click()
                expect(page.locator("#onboarding")).not_to_be_visible()
                complete_baseline(page)
                expect(page.locator("#lessonContent")).to_contain_text("容易出错的地方")
                passed("Built-in complete course is available without publishing or manufacturing review")

                expect(page.locator("#saveDraftButton")).to_have_count(0)
                with page.expect_response(lambda response: response.status == 200
                                          and "/api/learning/draft?" in response.url):
                    page.locator('[name=answerChoice][value="A"]').check()
                expect(page.locator("#saveStatus")).to_have_text("已保存到本机")
                page.reload()
                page.locator("#identityForm button[type=submit]").click()
                expect(page.locator('[name=answerChoice][value="A"]')).to_be_checked()
                passed("Reload restores active lesson and selected answer")
                if page.locator("#recallToggle").inner_text().startswith("收起"):
                    page.locator("#recallToggle").click()
                page.locator("#answerConfidence").select_option("sure")
                page.locator("#answerForm button[type=submit]").click()
                expect(page.locator("#responses")).to_contain_text("需要再想一想")
                expect(page.locator('[data-node="sample"]')).to_have_attribute("title", "正在学习")
                assert saved_state()["learner"]["states"]["sample"]["status"] == "needs_review"
                page.locator("#nextLesson").click()
                expect(page.locator("#questionText")).to_contain_text("违约")
                page.locator('[name=answerChoice][value="D"]').check()
                if page.locator("#recallToggle").inner_text().startswith("收起"):
                    page.locator("#recallToggle").click()
                page.locator("#answerConfidence").select_option("sure")
                page.locator("#answerForm button[type=submit]").click()
                expect(page.locator("#responses")).to_contain_text("回答正确")
                assert saved_state()["learner"]["states"]["sample"]["status"] == "mastered"
                passed("Wrong answer leads to remediation and a different retest, then mastery")

                for index, node in enumerate(build_graph()["nodes"][1:], start=1):
                    page.locator("#nextLesson").click()
                    expect(page.locator("#lessonContent h3").first).to_have_text(node["title"])
                    task = node["check_task"]
                    if index == 1:
                        page.locator("#hintButton").click()
                        expect(page.locator("#hintList")).to_contain_text("提示 1")
                    page.locator(f'[name=answerChoice][value="{task["answer_key"]}"]').check()
                    if page.locator("#recallToggle").inner_text().startswith("收起"):
                        page.locator("#recallToggle").click()
                    page.locator("#answerConfidence").select_option("sure")
                    page.locator("#answerForm button[type=submit]").click()
                    expect(page.locator("#responses")).to_contain_text("回答正确")
                    if index == 1:
                        expect(page.locator('[data-node="partition"]')).to_have_attribute("title", "正在学习")
                        assert saved_state()["learner"]["states"]["partition"]["status"] == "uncertain"
                        page.locator("#nextLesson").click()
                        expect(page.locator("#questionText")).to_contain_text("200")
                        page.locator(f'[name=answerChoice][value="{node["retest_tasks"][0]["answer_key"]}"]').check()
                        if page.locator("#recallToggle").inner_text().startswith("收起"):
                            page.locator("#recallToggle").click()
                        page.locator("#answerConfidence").select_option("sure")
                        page.locator("#answerForm button[type=submit]").click()
                        expect(page.locator("#responses")).to_contain_text("回答正确")
                        assert saved_state()["learner"]["states"]["partition"]["status"] == "mastered"
                        passed("Hint-assisted success requires an independent alternate question")
                    if index == 5:
                        page.screenshot(path=str(OUTPUT / "acceptance-course-desktop.png"), full_page=True)
                    if index == 8:
                        page.set_viewport_size({"width": 390, "height": 844})
                        page.locator("#themeButton").click()
                        page.wait_for_function("document.getAnimations().every(a => a.playState !== 'running')")
                        assert page.locator('#themeButton').evaluate("e => Math.max(...getComputedStyle(e).backgroundColor.match(/\\d+/g).slice(0,3).map(Number)) < 100")
                        page.screenshot(path=str(OUTPUT / "acceptance-course-mobile-dark.png"), full_page=True)
                        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
                        page.set_viewport_size({"width": 1440, "height": 1000})
                        page.locator("#themeButton").click()
                expect(page.locator("#courseProgress")).to_contain_text("10 / 10")
                expect(page.locator("#nextLesson")).to_be_disabled()
                expect_student_learning_only(page)
                assert all(chapter["passed"] for chapter in saved_state()["chapters"])
                passed("All ten lessons complete and both chapter rules pass")
                for chapter_id in ("data", "model"):
                    state = saved_state()
                    response = page.request.post(base + "/api/learning/report?course_id=" + DEMO_ID, data={
                        "student_id": "synthetic-course-acceptance", "course_version": state["course"]["version"],
                        "expected_version": state["learner"]["version"], "request_id": uuid.uuid4().hex,
                        "chapter_id": chapter_id})
                    assert response.ok, response.text()
                exported = page.request.get(base + "/api/course-graph/learner/export", params={
                    "course_id": DEMO_ID, "student_id": "synthetic-course-acceptance"}).json()
                assert len(exported["workspace"]["reports"]) == 2
                assert any("划分" in item["title"] for item in saved_state()["handbook"])
                passed("Backend retains chapter report snapshots, exports and handbook data while learner diagnostic lists stay empty")
                page.screenshot(path=str(OUTPUT / "acceptance-course-complete.png"), full_page=True)
                page.goto(base + f"/review?course_id={DEMO_ID}")
                page.locator("#identityForm button[type=submit]").click()
                expect(page.locator("#taskAuthoring")).to_be_hidden()
                expect(page.locator("#policyForm")).to_be_hidden()
                expect(page.locator("#reviewEvidence")).to_contain_text("demo_sample_2")
                passed("Teacher can inspect evidence and both task variants, without editing the immutable demo")
                assert not report["page_errors"], report["page_errors"]
                browser.close()
    finally:
        (OUTPUT / "acceptance-course-ui-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
