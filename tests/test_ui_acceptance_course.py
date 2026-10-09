"""Complete the built-in course with synthetic answers in an isolated browser app."""
import json
import tempfile
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

from test_ui_documents import isolated_application
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
            with isolated_application(Path(temporary)) as (base, _store, _documents), sync_playwright() as p:
                browser = p.chromium.launch()
                page = browser.new_page(viewport={"width": 1440, "height": 1000})
                page.on("pageerror", lambda e: report["page_errors"].append(str(e)))
                page.goto(base + "/courses")
                page.locator("[data-course-id=ml_acceptance_demo] .learning-course").click()
                page.locator("#studentId").fill("synthetic-course-acceptance")
                page.locator("#identityForm button[type=submit]").click()
                expect(page.locator("#notice")).to_be_hidden()
                page.locator("#goals").fill("Synthetic: complete the acceptance course")
                page.locator("#onboardForm button[type=submit]").click()
                expect(page.locator("#onboarding")).not_to_be_visible()
                page.locator("#nextLesson").click()
                expect(page.locator("#lessonContent")).to_contain_text("容易出错的地方")
                passed("Built-in complete course is available without publishing or manufacturing review")

                page.locator('[name=answerChoice][value="A"]').check()
                page.locator("#saveDraftButton").click()
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
                expect(page.locator('[data-node="sample"] .state-dot')).to_have_class("state-dot needs_review")
                page.locator("#nextLesson").click()
                expect(page.locator("#questionText")).to_contain_text("违约")
                page.locator('[name=answerChoice][value="D"]').check()
                if page.locator("#recallToggle").inner_text().startswith("收起"):
                    page.locator("#recallToggle").click()
                page.locator("#answerConfidence").select_option("sure")
                page.locator("#answerForm button[type=submit]").click()
                expect(page.locator('[data-node="sample"] .state-dot')).to_have_class("state-dot mastered")
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
                        expect(page.locator('[data-node="partition"] .state-dot')).to_have_class("state-dot uncertain")
                        page.locator("#nextLesson").click()
                        expect(page.locator("#questionText")).to_contain_text("200")
                        page.locator(f'[name=answerChoice][value="{node["retest_tasks"][0]["answer_key"]}"]').check()
                        if page.locator("#recallToggle").inner_text().startswith("收起"):
                            page.locator("#recallToggle").click()
                        page.locator("#answerConfidence").select_option("sure")
                        page.locator("#answerForm button[type=submit]").click()
                        expect(page.locator('[data-node="partition"] .state-dot')).to_have_class("state-dot mastered")
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
                assert page.locator("#chapterReports .badge", has_text="当前达标").count() == 2
                passed("All ten lessons complete and both chapter rules pass")
                for chapter_id in ("data", "model"):
                    page.locator(f'[data-report="{chapter_id}"]').click()
                    expect(page.locator("#saveStatus")).to_have_text("已保存到本机")
                expect(page.locator("#chapterReports")).to_contain_text("已保存 2 份报告")
                with page.expect_download() as download:
                    page.locator("#exportButton").click()
                exported = json.loads(Path(download.value.path()).read_text(encoding="utf-8"))
                assert len(exported["workspace"]["reports"]) == 2
                with page.expect_download() as download:
                    page.locator("#exportHandbook").click()
                assert "划分" in Path(download.value.path()).read_text(encoding="utf-8")
                passed("Chapter report snapshots and evidence handbook export correctly")
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
