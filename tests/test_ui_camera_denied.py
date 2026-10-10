"""Browser denial and stop-retry with real protected API; never open a device."""
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

from playwright.sync_api import expect, sync_playwright
from test_ui_documents import isolated_application
from test_ui_access import enter_created


def main():
    env = {"PLIAC_REQUIRE_AUTH": "1", "PLIAC_MEDIA_ENABLED": "1",
           "PLIAC_MEDIA_RETENTION_DAYS": "1", "PLIAC_MEDIA_CONTACT": "synthetic test only"}
    with tempfile.TemporaryDirectory(prefix="pliac-camera-denied-") as folder, patch.dict(os.environ, env):
        with isolated_application(Path(folder)) as (base, _, _), sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page()
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.add_init_script("""window.testOpens=0;
                navigator.mediaDevices.getUserMedia=async () => {
                    window.testOpens++;
                    throw new DOMException('Synthetic permission denied', 'NotAllowedError');
                };""")
            page.goto(base + "/app/courses/ml_acceptance_demo?lab=1")
            page.get_by_role("button", name="创建匿名学习档案").click()
            enter_created(page)
            lab = page.get_by_role("article", name="机器学习实验")
            lab.get_by_role("button", name="开始实验", exact=True).click()
            expect(lab).to_contain_text("已完成 0 / 5 步")
            camera = page.locator(".camera-panel")
            camera.locator("summary").click()
            expect(camera.get_by_text("请先进入已保存的学习材料、核验或实验活动。", exact=True)).to_have_count(0)
            student = page.evaluate("localStorage.getItem('pliac.local-learner')")
            query = f"course_id=ml_acceptance_demo&student_id={student}"

            def sessions():
                response = page.request.get(base + "/api/media/sessions?" + query)
                assert response.ok, response.text()
                return response.json()

            camera.get_by_role("checkbox").check()
            camera.get_by_role("button", name="授权并开始采集").click()
            expect(camera.get_by_role("alert")).to_contain_text("浏览器未允许摄像头访问")
            expect(camera.locator("summary")).to_contain_text("设备未采集")
            rows = sessions()
            assert len(rows) == 1 and rows[0]["status"] == "closed", rows
            detail = page.request.get(base + "/api/media/session?" + query + "&session_id=" + rows[0]["id"]).json()
            assert not detail["clips"], detail
            assert page.evaluate("window.testOpens") == 1

            # A failed stop must not masquerade as confirmed server cleanup.
            page.route("**/api/media/control?*", lambda route: route.fulfill(
                status=503, content_type="application/json", body='{"detail":"synthetic stop failure"}'))
            camera.get_by_role("button", name="授权并开始采集").click()
            expect(camera.get_by_role("alert")).to_contain_text("服务端停止状态未确认")
            assert any(row["status"] == "active" for row in sessions())
            page.unroute("**/api/media/control?*")
            camera.get_by_role("button", name="停止本次采集", exact=True).click()
            expect(camera.get_by_role("alert")).to_have_count(0)
            assert all(row["status"] == "closed" for row in sessions())
            expect(lab).to_contain_text("已完成 0 / 5 步")
            camera.locator("summary").click()
            lab.get_by_role("link", name="返回学习材料").click()
            expect(lab).to_have_count(0)
            assert not errors, errors
            browser.close()
    print("PASS: denied device remains optional; server stopped with zero clips; failed stop disclosed and retry succeeds; learning navigation works")


if __name__ == "__main__":
    main()
