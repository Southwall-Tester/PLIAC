"""Anonymous registration, isolated records, recovery and logout in real Chromium."""
import json
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

from playwright.sync_api import expect, sync_playwright
from test_ui_documents import isolated_application

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "outputs/verification"


def enter_created(page):
    expect(page.get_by_role("heading", name="保存你的恢复码")).to_be_visible()
    code = page.get_by_label("本次恢复码").input_value()
    assert len(code) >= 32
    page.get_by_label("我已在安全位置保存恢复码").check()
    page.get_by_role("button", name="进入学习空间").click()
    return code


def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    report = {"synthetic_only": True, "checks": [], "errors": []}
    with tempfile.TemporaryDirectory(prefix="pliac-access-ui-") as folder, patch.dict(os.environ, {"PLIAC_REQUIRE_AUTH": "1"}):
        with isolated_application(Path(folder)) as (base, _, _), sync_playwright() as p:
            browser = p.chromium.launch(channel=os.environ.get("PLIAC_BROWSER_CHANNEL") or None)
            first = browser.new_context(viewport={"width": 1440, "height": 960})
            second = browser.new_context(viewport={"width": 390, "height": 844})
            page, other = first.new_page(), second.new_page()
            for tab in (page, other):
                tab.on("pageerror", lambda error: report["errors"].append(str(error)))
            target = base + "/app/courses/ml_acceptance_demo"
            page.goto(target)
            expect(page.get_by_role("heading", name="从你的学习档案开始")).to_be_visible()
            assert first.request.get(base + "/api/tutor/archive?student_id=unknown").status == 401
            page.screenshot(path=str(OUTPUT / "identity-entry-desktop.png"), full_page=True)
            page.get_by_role("button", name="创建匿名学习档案").click()
            old_code = enter_created(page)
            expect(page.locator(".lesson h1")).to_be_visible()
            student = page.evaluate("localStorage.getItem('pliac.local-learner')")
            assert old_code not in page.evaluate("JSON.stringify(localStorage)")
            page.get_by_role("button", name="设置学习起点").click()
            page.get_by_label("学习目标", exact=True).fill("synthetic protected learner goal")
            page.get_by_label("由智能体接续安排学习").uncheck()
            page.get_by_role("button", name="保存目标与起点").click()
            expect(page.get_by_role("button", name="保存目标与起点")).not_to_be_visible()
            page.get_by_role("button", name="切换教学对话").click()
            page.locator(".composer textarea").fill("private unsent draft")
            page.reload()
            page.get_by_role("button", name="切换教学对话").click()
            expect(page.locator(".composer textarea")).to_have_value("private unsent draft")
            report["checks"].append("Registration opens deep link; protected goal save and draft refresh work")

            other.goto(target)
            other.get_by_role("button", name="创建匿名学习档案").click()
            expect(other.get_by_role("heading", name="保存你的恢复码")).to_be_visible()
            assert other.evaluate("document.documentElement.scrollWidth <= innerWidth")
            other.screenshot(path=str(OUTPUT / "identity-recovery-mobile.png"), full_page=True, mask=[other.get_by_label("本次恢复码")])
            enter_created(other)
            expect(other.locator(".lesson h1")).to_be_visible()
            second_id = other.evaluate("localStorage.getItem('pliac.local-learner')")
            assert student != second_id
            assert second.request.get(base + f"/api/learning?course_id=ml_acceptance_demo&student_id={student}").status == 403
            own = second.request.get(base + f"/api/learning?course_id=ml_acceptance_demo&student_id={second_id}")
            assert own.status == 200 and "synthetic protected learner goal" not in own.text()
            assert second.request.post(base + "/api/course-graph/diagnoses", data={"student_id": second_id}).status == 403
            report["checks"].append("Independent browser identity cannot read another learner or write diagnoses")

            # Same browser, different identity: logout clears private local caches, not saved records.
            other.goto(base + "/app/account")
            other.get_by_role("button", name="退出此浏览器的学习身份").click()
            expect(other.get_by_role("heading", name="从你的学习档案开始")).to_be_visible()
            other.get_by_label("恢复码", exact=True).fill(old_code)
            other.get_by_role("button", name="恢复我的档案").click()
            rotated = enter_created(other)
            assert rotated != old_code
            expect(other.get_by_role("heading", name="从上次停下的地方继续。")).to_be_visible()
            assert other.evaluate("localStorage.getItem('pliac.local-learner')") == student
            restored = second.request.get(base + f"/api/learning?course_id=ml_acceptance_demo&student_id={student}")
            assert restored.status == 200 and "synthetic protected learner goal" in restored.text()
            assert first.request.get(base + f"/api/learning?course_id=ml_acceptance_demo&student_id={student}").status == 401
            page.evaluate("window.dispatchEvent(new Event('focus'))")
            expect(page.get_by_role("heading", name="从你的学习档案开始")).to_be_visible()
            # A new identity on the expired first browser must not inherit the old unsent draft.
            page.get_by_role("button", name="创建匿名学习档案").click()
            enter_created(page)
            expect(page.locator(".lesson h1")).to_be_visible()
            page.get_by_role("button", name="切换教学对话").click()
            expect(page.locator(".composer textarea")).to_have_value("")
            report["checks"].append("Recovery rotates code, restores server goal, revokes prior browser and isolates its draft")

            # Open another tab of the recovered identity; logout removes its stale UI too.
            another = second.new_page()
            another.goto(target)
            expect(another.locator(".lesson h1")).to_be_visible()
            other.goto(base + "/app/account")
            other.get_by_role("button", name="退出此浏览器的学习身份").click()
            expect(another.get_by_role("heading", name="从你的学习档案开始")).to_be_visible()
            expect(other.get_by_role("heading", name="从你的学习档案开始")).to_be_visible()
            assert not second.request.get(base + "/api/access/session").json()["identity"]
            report["checks"].append("Explicit logout clears browser caches and invalidates sibling-tab private view")
            assert not report["errors"], report["errors"]
            browser.close()
    (OUTPUT / "identity-ui-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main()
