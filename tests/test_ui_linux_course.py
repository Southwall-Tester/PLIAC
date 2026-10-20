"""Real Chromium inspection of the authored Linux draft in isolated stores."""
import json
from pathlib import Path
import sys
import tempfile

from playwright.sync_api import sync_playwright, expect
from test_ui_documents import isolated_application

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from build_linux_course import COURSE_ID, DEST
from install_course_draft import install


def main():
    output = ROOT / "outputs/verification/linux-course"
    output.mkdir(parents=True, exist_ok=True)
    report = {"temporary_stores": True, "page_errors": [], "checks": []}
    with tempfile.TemporaryDirectory() as tmp:
        with isolated_application(Path(tmp)) as (base, store, documents):
            install(DEST / "course.json", store)
            with sync_playwright() as p:
                browser = p.chromium.launch()
                page = browser.new_page(viewport={"width": 1600, "height": 1000}, device_scale_factor=1)
                page.on("pageerror", lambda error: report["page_errors"].append(str(error)))
                page.add_init_script("""Object.defineProperty(window,'NetworkView',{
                  get(){return this.__View},set(View){this.__View=class extends View{
                    constructor(...args){super(...args);window.__network=this;}
                  }}});""")
                page.goto(base + "/manage/courses")
                card = page.locator(f'[data-course-id="{COURSE_ID}"]')
                expect(card).to_contain_text("Linux 命令入门")
                expect(card).to_contain_text("46 个知识点")
                expect(card.locator(".learning-course")).to_have_count(0)
                card.locator(".edit-course").click()
                page.wait_for_function("window.__network?.data?.nodes.length===55 && !window.__network.busy")
                expect(page.locator("#activeCourseTitle")).to_contain_text("Linux 命令入门")
                expect(page.locator("#reviewBadge")).to_have_text("草稿 v1")
                page.screenshot(path=str(output / "graph.png"))
                report["checks"].append("Management card opens all 46 concepts plus course/chapter hierarchy")
                page.locator("#filtersButton").click()
                page.locator("#search").fill("grep")
                page.locator('[data-node="grep"]').click()
                expect(page.locator("#detailContent")).to_contain_text("grep 文本筛选")
                expect(page.locator("#detailContent")).to_contain_text("Shell 引号")
                expect(page.locator("#detailContent")).to_contain_text("find 文件查找")
                expect(page.locator("#detailContent a[href*='gnu.org']").first).to_be_visible()
                page.locator("#detailContent summary").click()
                expect(page.locator("#detailContent")).to_contain_text("grep -F 'a.b' app.log")
                page.screenshot(path=str(output / "grep-detail.png"))
                report["checks"].append("Search and concept details expose prerequisite, confusion, source and teacher answer")
                page.reload()
                page.wait_for_function("window.__network?.data?.nodes.length>=3 && !window.__network.busy")
                expect(page.locator("#activeCourseTitle")).to_contain_text("Linux 命令入门")
                page.goto(base + "/course-reader?course_id=" + COURSE_ID + "&node_id=grep&mode=author")
                expect(page.locator("body")).to_contain_text("grep 文本筛选")
                page.screenshot(path=str(output / "reader-scope.png"))
                report["checks"].append("Existing scoped reader recognizes the authored grep material without another upload")
                page.goto(base + "/courses")
                expect(page.locator(f'[data-course-id="{COURSE_ID}"]')).to_have_count(0)
                report["checks"].append("Unreviewed draft is not advertised as a published learner course")
                browser.close()
    assert not report["page_errors"], report
    report["passed"] = True
    (output / "ui-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
