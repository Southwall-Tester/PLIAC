"""Browser check of authored demo questions, not a real learning-effect trial."""
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

from playwright.sync_api import expect, sync_playwright
from test_ui_documents import isolated_application, ROOT
from learning_agent.acceptance_course import build_graph
from pliac.tutor import TeachingProposal


def main():
    with tempfile.TemporaryDirectory(prefix="assessment-ui-") as temp:
        with isolated_application(Path(temp)) as (base, _, _), sync_playwright() as p:
            browser = p.chromium.launch(channel=os.environ.get("PLIAC_BROWSER_CHANNEL") or None)
            page = browser.new_page(viewport={"width": 1440, "height": 960})
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.goto(base + "/app/courses/ml_acceptance_demo")
            panel = page.get_by_role("region", name="理解核验")
            panel.get_by_role("button", name="开始核验").click()
            expect(panel).to_contain_text("作答前仍可求助")
            task = build_graph()["nodes"][0]["check_task"]
            choice = next(option["text"] for option in task["options"] if option["id"] == task["answer_key"])
            panel.get_by_label(choice, exact=True).check()
            page.reload()
            expect(panel.get_by_label(choice, exact=True)).to_be_checked()
            panel.get_by_role("button", name="保存作答").click()
            expect(panel.get_by_text("作答已保存，尚未形成评价。")).to_be_visible()
            page.reload()
            panel.get_by_role("button", name="按标准评价").click()
            expect(panel.get_by_role("heading", name="本任务证据支持掌握")).to_be_visible()
            memory = page.get_by_role("region", name="学习记忆")
            memory.locator('summary').click()
            expect(memory).to_contain_text("保存了 1 条过程证据、1 次诊断")
            panel.get_by_text("查看评价依据").click()
            expect(panel.locator("blockquote")).to_be_visible()
            learner = page.evaluate("localStorage.getItem('pliac.local-learner')")
            response = page.request.get(base + f"/api/course-graph/learner/export?course_id=ml_acceptance_demo&student_id={learner}")
            assert response.ok, response.text()
            exported = response.json()
            assert "answer_key" not in str(exported)
            assert "reference_answer" not in str(exported)
            assert len(exported["diagnoses"]) == 1
            async def teaching(context, config):
                assert context["intent"] == "advance"
                assert context["diagnoses"][-1]["status"] == "mastered"
                assert context["learning_memory"]["nodes"][context["current_node_id"]]["status"] == "mastered"
                assert context["evidence"][-1]["text"] == task["answer_key"]
                return TeachingProposal(response="合成测试：接下来核验能否迁移解释。", target_node_id=context["current_node_id"],
                    action="probe", rationale="已有本题独立作答证据，还需迁移核验", blocks=[],
                    question="换一种预测任务，如何区分特征与标签？", uncertainty="不代表完整能力已经验证"), {"model": "synthetic"}
            with patch("pliac.tutor_api.configured_api", return_value=None), patch("pliac.tutor_api.generate_teaching", teaching):
                page.get_by_role("button", name="安排下一步学习").click()
                expect(page.locator(".teaching-material")).to_contain_text("合成测试：接下来核验能否迁移解释。")
            page.reload()
            expect(page.locator(".teaching-material")).to_contain_text("已有本题独立作答证据，还需迁移核验")
            notes = page.get_by_role("region", name="学习笔记")
            notes.locator('summary').first.click()
            note_text = "合成笔记：先区分预测时可得的特征与预测目标。"
            notes.get_by_role("textbox").fill(note_text)
            notes.get_by_role("button", name="保存笔记").click()
            expect(notes.get_by_role("status")).to_have_text("已保存到学习档案")
            page.reload()
            notes.locator('summary').first.click()
            expect(notes.get_by_role("textbox")).to_have_value(note_text)
            expect(panel.get_by_role("button", name="保存作答")).to_be_visible()
            expect(panel.get_by_role("radio")).to_have_count(4)
            output = ROOT / "outputs/verification"
            output.mkdir(parents=True, exist_ok=True)
            panel.screenshot(path=str(output / "assessment-panel.png"))
            async def lab_teaching(context, config):
                assert context["lab_available"]
                assert context["learner_notes"][0]["text"] == note_text
                return TeachingProposal(response="合成测试：用实验观察数据划分。", target_node_id=context["current_node_id"],
                    action="lab", rationale="通过真实训练观察结果", blocks=[], question="", uncertainty="实验完成不等于理解"), {"model": "synthetic"}
            with patch("pliac.tutor_api.configured_api", return_value=None), patch("pliac.tutor_api.generate_teaching", lab_teaching):
                page.get_by_role("button", name="安排下一步学习").click()
                expect(page.get_by_role("link", name="进入或继续 ML Lab")).to_be_visible()
            return_url = page.url
            page.get_by_role("link", name="进入或继续 ML Lab").click()
            expect(page.get_by_role("button", name="开始实验", exact=True)).to_be_visible()
            page.get_by_role("button", name="开始实验", exact=True).click()
            expect(page.locator(".ml-lab")).to_contain_text("已完成 0 / 5 步")
            page.get_by_role("button", name="获取提示", exact=True).click()
            expect(page.locator(".ml-lab")).to_contain_text("提示 1：")
            page.get_by_role("link", name="返回学习材料").click()
            expect(page).to_have_url(return_url)
            page.get_by_role("link", name="进入或继续 ML Lab").click()
            expect(page.locator(".ml-lab")).to_contain_text("第 1 轮")
            page.get_by_role("link", name="返回学习材料").click()
            page.set_viewport_size({"width": 390, "height": 844})
            if page.get_by_role("button", name="切换课程目录").get_attribute("aria-expanded") == "true":
                page.get_by_role("button", name="切换课程目录").click()
            panel.get_by_role("radio").first.check()
            panel.get_by_role("button", name="保存作答", exact=True).click()
            expect(panel).to_contain_text("条课程辅导记录，已纳入受助判断")
            expect(panel).to_contain_text("任务开启后的保存顺序")
            expect(panel).to_contain_text("1 条相关实验提示记录，已纳入受助判断")
            page.reload()
            expect(panel).to_contain_text("1 条相关实验提示记录，已纳入受助判断")
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            page.goto(base + "/app/archive")
            expect(page.locator('.archive-entry')).not_to_have_count(0)
            page.get_by_label("查看内容").select_option("note")
            page.get_by_text("查看第 1 版笔记").click()
            expect(page.get_by_text(note_text, exact=True)).to_be_visible()
            page.get_by_role("link", name="回到该知识点").click()
            expect(page.locator('.lesson h1')).to_have_text("01 样本、特征与标签")
            page.get_by_role("button", name="保存阶段学习总结").click()
            expect(page.locator('.stage-report h1')).to_contain_text("阶段学习总结")
            expect(page.locator('.stage-report')).to_contain_text(note_text)
            report_url = page.url
            page.reload()
            expect(page.locator('.stage-report')).to_contain_text("本报告不会随之后的学习更新")
            page.goto(base + '/app/archive')
            page.get_by_label('查看内容').select_option('report')
            page.get_by_role('link', name='打开保存的内容').click()
            expect(page.locator('.stage-report')).to_contain_text(note_text)
            assert page.url.split('report=')[-1] == report_url.split('report=')[-1]
            with page.expect_download() as pending_download:
                page.get_by_role('button', name='导出 PDF', exact=True).click()
            download = pending_download.value
            assert download.failure() is None
            download.save_as(str(output / 'synthetic-stage-report.pdf'))
            assert (output / 'synthetic-stage-report.pdf').read_bytes().startswith(b'%PDF')
            page.screenshot(path=str(output / 'stage-report-mobile.png'), full_page=True)
            assert not errors, errors
            print("PASS authored objective assessment, draft refresh, raw submission recovery, result, private answer filtering, mobile width")
            browser.close()


if __name__ == "__main__":
    main()
