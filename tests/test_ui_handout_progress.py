"""Browser evidence for detailed handout progress, using synthetic job snapshots."""
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from playwright.sync_api import expect, sync_playwright
from test_ui_documents import isolated_application
from test_ui_journey import algorithmic_journey, complete_baseline

OUTPUT = Path(__file__).resolve().parents[1] / "outputs/verification/journey"


def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    started = (datetime.now(timezone.utc) - timedelta(seconds=65)).isoformat()
    stamp = datetime.now(timezone.utc).isoformat()
    job = {"id": "synthetic-progress-job", "status": "running", "progress": 24,
           "stage": "整理内容总览与学习路线", "created_at": started,
           "progress_detail": {
               "version": 1, "phase": "planning", "current_task": "安排概念、例题与学习顺序",
               "started_at": started, "stage_started_at": started, "updated_at": stamp,
               "steps": [{"id": ident, "label": label, "status": state} for ident, label, state in (
                   ("reading", "读取资料", "completed"), ("planning", "安排讲解", "running"),
                   ("writing", "编写与检查", "pending"), ("graph", "构建图谱", "pending"),
                   ("rendering", "排版讲义", "pending"))],
               "sections": {"completed": 0, "total": 0}, "tasks": [],
               "request": {"status": "waiting", "started_at": started, "updated_at": stamp,
                           "last_received_at": None, "received_chars": 0, "reasoning_chars": 0,
                           "attempt": 1, "transport": "sse", "active_count": 1,
                           "completed_count": 0, "total_count": 1}}}
    report = {"synthetic_only": True, "page_errors": [], "polls": 0, "checks": []}
    with tempfile.TemporaryDirectory(prefix="pliac-progress-ui-") as temporary, \
         isolated_application(Path(temporary)) as (base, _, _), algorithmic_journey(), \
         sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        page.on("pageerror", lambda error: report["page_errors"].append(str(error)))

        def handouts(route):
            if route.request.method == "POST":
                route.fulfill(json=job)
            else:
                report["polls"] += 1
                route.fulfill(json={"jobs": [job]})

        page.route("**/api/handouts**", handouts)
        page.goto(base + "/learn?course_id=ml_acceptance_demo")
        expect(page.locator("#onboarding")).to_be_visible()
        page.locator("#onboardContinue").click()
        complete_baseline(page)
        card = page.locator("#autoLessonProgressDetail")
        expect(card).to_be_visible()
        expect(card.locator(".hp-task")).to_have_text("安排概念、例题与学习顺序")
        expect(card.locator(".hp-step")).to_have_count(5)
        expect(card.locator(".hp-response")).to_contain_text("正在等待模型回复")
        expect(card.locator(".hp-elapsed")).to_contain_text("1 分")
        expect(card.locator(".hp-sections")).to_be_hidden()
        expect(page.locator("#lessonContent")).to_be_visible()
        initial = card.locator(".hp-elapsed").inner_text()
        page.wait_for_function("text=>document.querySelector('#autoLessonProgressDetail .hp-elapsed').textContent!==text", arg=initial)
        expect(card.locator(".hp-bar")).to_have_attribute("value", "24")
        page.reload()
        expect(card).to_be_visible()
        expect(card.locator(".hp-elapsed")).to_contain_text("1 分")
        job["progress_detail"]["request"].update(
            status="streaming", received_chars=812, reasoning_chars=200, last_received_at=stamp)
        expect(card.locator(".hp-response")).to_contain_text("已接收 812 字符", timeout=10000)
        expect(card.locator(".hp-response")).to_contain_text("最近响应")
        expect(card.locator(".hp-bar")).to_have_attribute("value", "24")
        # A model request can finish while the next pipeline task is starting.
        job["progress_detail"]["request"].update(status="completed", completed_count=1, active_count=0)
        expect(card.locator(".hp-response")).to_contain_text("本轮模型回复已收到", timeout=10000)
        expect(card.locator(".hp-response")).not_to_contain_text("等待")
        expect(card.locator(".hp-activity")).to_be_hidden()
        detail = job["progress_detail"]
        job.update(progress=49, stage="编写小节")
        detail.update(phase="writing", current_task="编写「路径定位」；检查「目录切换」",
                      stage_started_at=stamp, sections={"completed": 1, "total": 3},
                      tasks=[{"task_id": "one", "label": "检查「Shell」", "status": "completed"},
                             {"task_id": "two", "label": "编写「路径定位」", "status": "running",
                              "model_status": "streaming", "received_chars": 800},
                             {"task_id": "three", "label": "检查「目录切换」", "status": "running",
                              "model_status": "retrying", "model_attempt": 2}])
        detail["steps"][1]["status"] = "completed"
        detail["steps"][2]["status"] = "running"
        detail["request"].update(status="streaming", received_chars=1600, active_count=2,
                                 completed_count=1, total_count=3, started_at=stamp)
        expect(card.locator(".hp-sections")).to_have_text("讲解小节 1 / 3 已完成", timeout=10000)
        card.locator("summary").click()
        expect(card.locator(".hp-tasks li")).to_have_count(3)
        expect(card.locator(".hp-tasks")).to_contain_text("模型重试中 · 第 2 次请求")
        page.screenshot(path=str(OUTPUT / "handout-progress-desktop.png"), full_page=True)
        card.screenshot(path=str(OUTPUT / "handout-progress-card-desktop.png"))
        page.set_viewport_size({"width": 390, "height": 844})
        page.locator("#themeButton").click()
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1")
        page.screenshot(path=str(OUTPUT / "handout-progress-mobile-dark.png"), full_page=True)
        card.screenshot(path=str(OUTPUT / "handout-progress-card-mobile-dark.png"))
        job.update(status="failed", error="合成测试：本轮请求超时")
        detail["finished_at"] = datetime.now(timezone.utc).isoformat()
        detail["request"]["status"] = "failed"
        detail["steps"][2]["status"] = "failed"
        expect(card.locator(".hp-activity")).to_be_hidden(timeout=10000)
        expect(page.locator("#autoLessonStatus")).to_contain_text("本轮请求超时")
        elapsed = card.locator(".hp-elapsed").inner_text()
        page.wait_for_timeout(1200)
        expect(card.locator(".hp-elapsed")).to_have_text(elapsed)
        expect(card.locator(".hp-bar")).to_be_hidden()
        # The same production component accepts historical jobs without details.
        legacy = {"id": "legacy", "status": "running", "stage": "整理内容总览与学习路线",
                  "progress": 24, "created_at": started}
        page.evaluate("""job=>{
            const host=document.createElement('section');host.id='legacyProgress';
            document.querySelector('main').append(host);
            window.legacyProgress=new HandoutProgress(host);window.legacyProgress.update(job);
        }""", legacy)
        expect(page.locator("#legacyProgress .hp-task")).to_have_text(legacy["stage"])
        expect(page.locator("#legacyProgress .hp-steps")).to_be_hidden()
        expect(page.locator("#legacyProgress .hp-response")).to_be_hidden()
        assert not report["page_errors"]
        assert report["polls"] >= 4
        report["checks"] = [
            "Real server start time survives refresh and local elapsed time increases without advancing 24%",
            "Waiting, streaming and completed model requests show distinct honest activity",
            "Writing shows completed sections, active tasks and received characters on desktop/mobile dark",
            "Failure freezes elapsed time; historical jobs retain their real coarse stage",
        ]
        report["passed"] = True
        browser.close()
    (OUTPUT / "handout-progress-report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
