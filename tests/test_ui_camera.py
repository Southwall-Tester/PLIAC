"""Fake browser camera only, temporary identities/storage, no model calls."""
import os
import uuid
import tempfile
from pathlib import Path
from unittest.mock import patch

from playwright.sync_api import expect, sync_playwright
from test_ui_documents import isolated_application
from test_ui_access import enter_created


def main():
    env = {"PLIAC_REQUIRE_AUTH": "1", "PLIAC_MEDIA_ENABLED": "1",
           "PLIAC_MEDIA_RETENTION_DAYS": "1", "PLIAC_MEDIA_CONTACT": "synthetic test only",
           "PLIAC_MEDIA_REVIEW_ENABLED": "1", "PLIAC_ADMIN_SECRET": "synthetic-camera-review-" + "x" * 32}
    with tempfile.TemporaryDirectory(prefix="pliac-camera-ui-") as folder, patch.dict(os.environ, env):
        with isolated_application(Path(folder)) as (base, _, _), sync_playwright() as p:
            browser = p.chromium.launch(args=["--use-fake-device-for-media-stream", "--use-fake-ui-for-media-stream"])
            page = browser.new_page(viewport={"width": 1360, "height": 1000})
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.add_init_script("""window.testTracks=[];window.testOpens=0;
                const original=navigator.mediaDevices.getUserMedia.bind(navigator.mediaDevices);
                navigator.mediaDevices.getUserMedia=async constraints => {
                    window.testOpens++; const stream=await original(constraints);
                    window.testTracks.push(...stream.getTracks());return stream;
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
            assert page.evaluate("window.testOpens") == 0
            expect(camera.get_by_role("button", name="授权并开始采集")).to_be_disabled()
            camera.get_by_role("checkbox").check()
            camera.get_by_role("button", name="授权并开始采集").click()
            expect(camera.locator("summary")).to_contain_text("正在采集")
            page.wait_for_timeout(1000)
            student = page.evaluate("localStorage.getItem('pliac.local-learner')")
            state = page.request.get(base + f"/api/ml-lab?course_id=ml_acceptance_demo&student_id={student}").json()
            hint = page.request.post(base + '/api/ml-lab/hint?course_id=ml_acceptance_demo', data={
                'student_id': student, 'session_id': state['active']['id'], 'course_version': state['course_version'],
                'expected_version': state['version'], 'request_id': uuid.uuid4().hex})
            assert hint.ok, hint.text()
            expect(camera).to_contain_text("已保存 1 个片段", timeout=25000)
            assert page.evaluate("testTracks.every(t=>t.kind==='video')")
            camera.get_by_role("button", name="暂停并关闭设备").click()
            expect(camera.locator("summary")).to_contain_text("设备未采集")
            assert page.evaluate("testTracks.every(t=>t.readyState==='ended')")
            review = camera.get_by_role("region", name="本人片段回看")
            expect(review.get_by_label("采集记录").locator("option")).to_have_count(2)
            review.get_by_label("采集记录").select_option(index=1)
            review.get_by_role("button", name="片段 1", exact=False).click()
            player = review.get_by_label("已保存片段播放器")
            expect(player).to_be_visible()
            page.wait_for_function("document.querySelector('video[aria-label=\"已保存片段播放器\"]').videoWidth > 0")
            review.get_by_text('关联活动的关键事件', exact=True).click()
            expect(review).to_contain_text('查看实验提示')
            review.get_by_role('button', name='打开关联片段 1', exact=True).click()
            expect(player).to_be_visible()
            admin_context = browser.new_context()
            admin_context.request.post(base + '/api/access/admin', data={'secret': env['PLIAC_ADMIN_SECRET']})
            admin = admin_context.new_page()
            admin.goto(base + '/app/admin/media-review')
            admin.get_by_label('课程编号', exact=True).fill('ml_acceptance_demo')
            admin.get_by_label('学习者匿名编号', exact=True).fill(page.evaluate("localStorage.getItem('pliac.local-learner')"))
            admin.get_by_role('button', name='查询授权记录').click()
            admin.get_by_label('采集记录').select_option(index=1)
            admin.get_by_role('button', name='片段 1', exact=False).click()
            admin.wait_for_function("document.querySelector('video[aria-label=\"已保存片段播放器\"]').videoWidth > 0")
            admin.get_by_text('关联活动的关键事件', exact=True).click()
            expect(admin.get_by_role('region', name='授权片段回看')).to_contain_text('查看实验提示')
            expect(admin.get_by_role('button', name='撤回并删除所选记录')).to_have_count(0)
            review.get_by_role("button", name="撤回并删除所选记录").click()
            expect(player).to_have_count(0)
            expect(review).to_contain_text("没有可回看的片段")
            expect(review.get_by_text('关联活动的关键事件', exact=True)).to_have_count(0)
            admin.get_by_role('button', name='刷新保存记录').click()
            expect(admin.get_by_label('已保存片段播放器')).to_have_count(0)
            expect(admin.get_by_role('region', name='授权片段回看')).to_contain_text('没有可回看的片段')
            expect(admin.get_by_text('关联活动的关键事件', exact=True)).to_have_count(0)
            admin_context.close()
            camera.get_by_role("button", name="撤回并删除本次片段").click()
            expect(camera).to_contain_text("已保存 0 个片段")
            camera.get_by_role("button", name="授权并开始采集").click()
            expect(camera.locator("summary")).to_contain_text("正在采集")
            camera.locator("summary").click()
            lab.get_by_role("link", name="返回学习材料").click()
            expect(camera.locator("summary")).to_contain_text("设备未采集")
            assert page.evaluate("testTracks.every(t=>t.readyState==='ended')")
            assert not errors, errors
            with patch.dict(os.environ, {"PLIAC_MEDIA_ENABLED": "0"}):
                page.evaluate("sessionStorage.clear()")
                page.reload()
                expect(camera).to_be_visible()
                camera.locator("summary").click()
                expect(camera.get_by_role("button", name="授权并开始采集")).to_be_disabled()
                expect(camera.get_by_label("采集记录").locator("option")).to_have_count(3)
                assert page.evaluate("window.testOpens") == 0
            browser.close()
    print("PASS: no device before consent; fake video decoded and saved; pause releases tracks; revoke deletes; activity navigation closes device")


if __name__ == "__main__":
    main()
