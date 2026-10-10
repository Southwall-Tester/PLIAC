"""Real browser/API persistence with an explicitly simulated teaching model."""
import asyncio
import json
import tempfile
import uuid
from pathlib import Path
from unittest.mock import patch

from playwright.sync_api import expect, sync_playwright
from test_ui_documents import isolated_application
from pliac.tutor import TeachingProposal
from learning_agent.course_graph import CourseGraphError
from learning_agent.api import resolve_course_store
from pliac.teaching_jobs import TeachingJobs

ROOT = Path(__file__).resolve().parents[1]


def main():
    import os
    calls = []

    async def model(context, config):
        calls.append(context["message"])
        assert context["learner"]["goals"] == "理解输入与预测目标"
        assert context["learner"]["background"] == "刚开始学机器学习"
        assert context['learner']['interests'] == ['校园活动']
        assert context['learner']['explanation_preferences'] == '先例子后公式'
        await asyncio.sleep(.5)
        if context["message"] == "模拟模型失败":
            raise CourseGraphError("模拟服务不可用", 502)
        if context["message"] == "刷新恢复测试" or context.get("intent") == "advance":
            await asyncio.sleep(2)
        source = context["sources"][0]
        proposal = TeachingProposal(response="合成测试回复：先区分输入与预测目标。", target_node_id=context["current_node_id"],
            action="probe", rationale="合成测试教学依据", question="请举出一个输入和目标。", uncertainty="尚未完成掌握核验",
            blocks=[{"heading": "合成测试讲解", "text": "这是浏览器联调内容，不用于证明教学效果。", "citations": [{"source_id": source["id"], "quote": source["text"][:20]}]}])
        return proposal, {"model": "synthetic-browser-test", "usage": []}

    with tempfile.TemporaryDirectory(prefix="pliac-tutor-ui-") as temporary:
        with isolated_application(Path(temporary)) as (base, _, _), patch("pliac.tutor_api.configured_api", return_value=object()), patch("pliac.tutor_api.generate_teaching", model), sync_playwright() as p:
            browser = p.chromium.launch(channel=os.environ.get("PLIAC_BROWSER_CHANNEL") or None)
            page = browser.new_page(viewport={"width": 1440, "height": 960})
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.goto(base + "/app/courses/ml_acceptance_demo")
            expect(page.locator(".lesson h1")).to_be_visible()
            page.get_by_role("button", name="目标与起点").click()
            page.get_by_text('案例与讲解偏好（可随时修改）', exact=True).click()
            page.get_by_label('希望使用的案例主题').fill('校园活动')
            page.get_by_label('讲解方式偏好').fill('先例子后公式')
            page.get_by_role('button', name='保存案例与讲解偏好').click()
            expect(page.locator('.learning-preferences')).to_contain_text('偏好已保存')
            page.get_by_label("学习目标", exact=True).fill("理解输入与预测目标")
            page.get_by_label("由智能体接续安排学习").uncheck()
            page.get_by_label("已有基础", exact=True).fill("刚开始学机器学习")
            student = page.evaluate("localStorage.getItem('pliac.local-learner')")
            current = page.request.get(base + f"/api/learning?course_id=ml_acceptance_demo&student_id={student}").json()
            changed = page.request.post(base + "/api/tutor/notes?course_id=ml_acceptance_demo", data={
                "student_id": student, "request_id": uuid.uuid4().hex, "course_version": current["course"]["version"],
                "expected_version": current["learner"]["version"], "node_id": current["course"]["nodes"][0]["id"],
                "text": "Synthetic concurrent update"})
            assert changed.ok, changed.text()
            page.get_by_role("button", name="保存目标与起点").click()
            expect(page.get_by_role("alert")).to_be_visible()
            expect(page.get_by_role("textbox", name="学习目标", exact=True)).to_have_value("理解输入与预测目标")
            page.get_by_role("button", name="保存目标与起点").click()
            expect(page.locator(".lesson h1")).to_have_text("01 样本、特征与标签")
            page.get_by_role("button", name="切换教学对话").click()
            draft = page.get_by_role("textbox")
            draft.fill("解释输入和目标")
            jobs = TeachingJobs(resolve_course_store("ml_acceptance_demo"))
            with patch.dict(os.environ, {"PLIAC_TEACHING_MAX_ACTIVE_PER_COURSE": "1"}):
                owner, _ = jobs.claim("synthetic-blocker", "browser-capacity", "synthetic")
                page.get_by_role("button", name="发送学习问题").click()
                expect(page.get_by_role("alert")).to_contain_text("教学服务繁忙")
                expect(draft).to_have_value("解释输入和目标")
                assert calls == [], calls
                jobs.update("synthetic-blocker", "browser-capacity", owner, "interrupted")
                page.get_by_role("button", name="恢复或重试上次请求").click()
            draft.fill("下一条问题先保留")
            expect(page.locator(".tutor-turn")).to_have_count(1)
            expect(draft).to_have_value("下一条问题先保留")
            page.get_by_text("查看依据", exact=True).click()
            expect(page.locator("blockquote")).to_be_visible()
            page.get_by_role("link", name="在正文区阅读完整讲解").click()
            expect(page.locator(".teaching-material h1")).to_have_text("合成测试讲解")
            page.reload()
            expect(page.locator(".teaching-material h1")).to_have_text("合成测试讲解")
            reading = page.get_by_label('跨次续读')
            expect(reading.get_by_role('button', name='保存为续读位置')).to_be_enabled()
            page.locator('.lesson-pane').evaluate('(element) => element.scrollTop = 200')
            reading.get_by_role('button', name='保存为续读位置').click()
            expect(reading).to_contain_text('续读位置已保存到服务器')
            fresh_context = browser.new_context(viewport={'width': 1440, 'height': 960})
            fresh_context.add_init_script("localStorage.setItem('pliac.local-learner', " + json.dumps(student) + ")")
            fresh = fresh_context.new_page()
            fresh.goto(base + '/app/')
            continuation = fresh.get_by_role('region', name='继续学习')
            expect(continuation).to_contain_text('服务器续读点')
            continuation.get_by_role('link').first.click()
            expect(fresh).to_have_url(page.url)
            expect(fresh.get_by_role('button', name='回到续读位置')).to_be_enabled()
            self_scroll = fresh.locator('.lesson-pane').evaluate('(element) => element.scrollTop')
            assert self_scroll == 0, self_scroll
            fresh.get_by_role('button', name='回到续读位置').click()
            assert fresh.locator('.lesson-pane').evaluate('(element) => element.scrollTop') > 100
            fresh_context.close()
            page.get_by_role("button", name="切换教学对话").click()
            expect(page.locator(".tutor-turn")).to_have_count(1)
            draft = page.get_by_role("textbox")
            expect(draft).to_have_value("下一条问题先保留")
            draft.fill("模拟模型失败")
            page.get_by_role("button", name="发送学习问题").click()
            expect(page.get_by_role("alert")).to_contain_text("模拟服务不可用")
            expect(draft).to_have_value("模拟模型失败")
            expect(page.locator(".tutor-turn")).to_have_count(1)
            assert calls == ["解释输入和目标", "模拟模型失败"], calls
            draft.fill("刷新恢复测试")
            page.get_by_role("button", name="发送学习问题").click()
            expect(page.locator('.conversation').get_by_role("status")).to_contain_text("正在组织课程讲解")
            saved_request = page.evaluate("""() => JSON.parse(localStorage.getItem(
                'pliac.teaching-request:' + localStorage.getItem('pliac.local-learner') + ':ml_acceptance_demo'))""")
            assert saved_request['message'] == '刷新恢复测试'
            page.reload()
            expect(page.locator('.teaching-material h1')).to_be_visible()
            page.get_by_role("button", name="切换教学对话").click()
            expect(page.get_by_role('button', name='恢复或重试上次请求')).to_be_visible()
            for _ in range(60):
                status = page.request.get(base + f'/api/tutor/jobs/{saved_request["id"]}?course_id=ml_acceptance_demo&student_id={student}')
                if status.ok and status.json()['status'] == 'generated':
                    break
                page.wait_for_timeout(100)
            assert status.ok and status.json()['status'] == 'generated'
            page.get_by_role('button', name='恢复或重试上次请求').click()
            expect(page.locator('.tutor-turn')).to_have_count(2)
            expect(page.get_by_role('button', name='恢复或重试上次请求')).to_have_count(0)
            assert calls.count('刷新恢复测试') == 1, calls
            before_advance = len(calls)
            page.get_by_role('button', name='安排下一步学习').click()
            expect(page.get_by_role('button', name='正在结合学习证据安排…')).to_be_visible()
            advance_request = page.evaluate("""() => Object.entries(localStorage).filter(([key]) => key.startsWith('pliac.advance-request:')).map(([, value]) => JSON.parse(value))[0]""")
            assert advance_request
            page.reload()
            expect(page.get_by_role('button', name='恢复上次学习安排')).to_be_visible()
            for _ in range(60):
                status = page.request.get(base + f'/api/tutor/jobs/{advance_request["id"]}?course_id=ml_acceptance_demo&student_id={student}')
                if status.ok and status.json()['status'] == 'generated':
                    break
                page.wait_for_timeout(100)
            assert status.ok and status.json()['status'] == 'generated'
            page.get_by_role('button', name='恢复上次学习安排').click()
            expect(page).to_have_url(base + '/app/courses/ml_acceptance_demo?material=' + advance_request['id'])
            assert len(calls) == before_advance + 1, calls
            assert not errors, errors
            output = ROOT / "outputs/verification"
            output.mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(output / "tutor-dialog.png"), full_page=True)
            report = {"synthetic_model": True, "checks": ["onboarding conflict refresh preserves input and retry succeeds", "goal and background reach teaching context", "reply persists after refresh", "generated material opens in main area and survives refresh", "new draft survives in-flight request", "citations expand", "model failure preserves draft and history"], "browser_errors": errors}
            (output / "tutor-ui-report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
            print(json.dumps(report))
            browser.close()


if __name__ == "__main__":
    main()
