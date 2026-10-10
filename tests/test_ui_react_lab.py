"""Real bounded sklearn experiment in the React workspace; synthetic data only."""
import json
import tempfile
from pathlib import Path
from unittest.mock import patch

from playwright.sync_api import expect, sync_playwright
from test_ui_documents import isolated_application
from pliac.tutor import TeachingProposal


def main():
    errors = []
    with tempfile.TemporaryDirectory(prefix="pliac-react-lab-") as folder, isolated_application(Path(folder)) as (base, _, _), sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1360, "height": 1000})
        page.on("pageerror", lambda failure: errors.append(str(failure)))
        page.on("console", lambda message: errors.append(message.text) if message.type == "error" else None)
        page.goto(base + "/app/courses/ml_acceptance_demo?lab=1")
        lab = page.get_by_role("article", name="机器学习实验")
        lab.get_by_role("button", name="开始实验", exact=True).click()
        expect(lab).to_contain_text("已完成 0 / 5 步")
        lab.get_by_label("预测目标", exact=True).select_option("target")
        lab.get_by_label("预测输入", exact=True).select_option("sensors")
        lab.get_by_label("回执产生时间").select_option("after")
        lab.get_by_label("最大树深度").fill("4")
        page.reload()
        expect(lab.get_by_label("预测目标", exact=True)).to_have_value("target")
        expect(lab.get_by_label("最大树深度")).to_have_value("4")
        lab.get_by_label("最大树深度").fill("1")
        lab.get_by_role("button", name="检查本步成果").click()
        expect(lab).to_contain_text("已完成 1 / 5 步")
        lab.get_by_role("button", name="训练并验证").click()
        expect(lab.get_by_label("引用实验记录").locator("option")).to_have_count(2)
        async def tutoring(context, config):
            assert context["lab_help"]
            assert context["lab"]["active"]["task"]["id"] == "split"
            assert context["lab"]["active"]["runs"][0]["config"]["depth"] == 1
            assert context["lab"]["active"]["final"] is None
            return TeachingProposal(response="合成辅导：本轮实验没有训练验证样本重叠。", action="probe",
                target_node_id=context["current_node_id"], rationale="解释实际结果", blocks=[], question="为什么要分开这些样本？",
                uncertainty="合成模型测试"), {"model": "synthetic-lab-help"}
        with patch("pliac.tutor_api.configured_api", return_value=None), patch("pliac.tutor_api.generate_teaching", tutoring):
            page.get_by_role("button", name="切换教学对话").click()
            page.get_by_label("当前课程的问题草稿").fill("解释当前实验结果")
            page.get_by_role("button", name="发送学习问题").click()
            expect(page.locator(".conversation")).to_contain_text("合成辅导：本轮实验没有训练验证样本重叠。", timeout=15000)
            page.get_by_role("button", name="切换教学对话").click()
        lab.get_by_label("引用实验记录").select_option(index=1)
        lab.get_by_role("button", name="检查本步成果").click()
        expect(lab).to_contain_text("已完成 2 / 5 步")
        lab.get_by_label("最大树深度").fill("0")
        lab.get_by_role("button", name="训练并验证").click()
        expect(lab.get_by_label("引用实验记录").locator("option")).to_have_count(3)
        lab.get_by_label("引用实验记录").select_option(index=2)
        lab.get_by_label("训练表现高而验证表现下降说明什么").select_option("gap")
        lab.get_by_role("button", name="检查本步成果").click()
        expect(lab).to_contain_text("已完成 3 / 5 步")
        lab.get_by_label("最大树深度").fill("4")
        lab.get_by_role("button", name="训练并验证").click()
        expect(lab.get_by_label("引用实验记录").locator("option")).to_have_count(4)
        student = page.evaluate("localStorage.getItem('pliac.local-learner')")
        url = base + f"/api/ml-lab?course_id=ml_acceptance_demo&student_id={student}"
        state = page.request.get(url).json()
        assert state["active"]["hints"]["split"] >= 1
        assert len(state["active"]["tutor_help"]) == 1
        best = max(state["active"]["runs"], key=lambda run: run["result"]["validation_accuracy"])
        lab.get_by_label("引用实验记录").select_option(best["id"])
        lab.get_by_label("选择依据").select_option("validation")
        lab.get_by_label("解释你的依据").fill("依据相同划分的验证表现比较三个方案，选择验证准确率最高的模型。")
        lab.get_by_role("button", name="检查本步成果").click()
        expect(lab).to_contain_text("已完成 4 / 5 步")
        expect(lab.get_by_role("button", name="训练并验证")).to_have_count(0)
        lab.get_by_label("测试结果的用途").select_option("report")
        lab.get_by_label("解释你的依据").fill("测试集只报告此前根据验证集选定并封存的模型表现，不用于继续调整参数。")
        lab.get_by_role("button", name="封存方案并完成测试").click()
        expect(lab.get_by_role("heading", name="本轮实验已完成")).to_be_visible()
        page.reload()
        expect(lab).to_contain_text("已完成 5 / 5 步")
        with page.expect_download() as downloading:
            lab.get_by_role("button", name="导出实验与复现代码").click()
        exported = json.loads(Path(downloading.value.path()).read_text(encoding="utf-8"))
        assert exported["scripts"]
        page.goto(base + '/app/archive?kind=lab')
        page.get_by_text('查看本轮实验记录', exact=True).click()
        expect(page.locator('.archive-entry')).to_contain_text('本轮已封存')
        expect(page.locator('.archive-entry')).to_contain_text('封存方案测试准确率')
        expect(page.locator('.archive-entry').locator('tbody tr')).to_have_count(3)
        page.get_by_role('link', name='打开当前实验（不切换历史轮次）').click()
        expect(lab).to_contain_text('已完成 5 / 5 步')
        page.set_viewport_size({"width": 390, "height": 1100})
        if page.locator(".course-nav").is_visible():
            page.get_by_role("button", name="切换课程目录").click()
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        output = Path(__file__).resolve().parents[1] / "outputs/verification/react-lab-mobile.png"
        output.parent.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(output), full_page=True)
        lab.get_by_role("button", name="换一批数据进行迁移复测").click()
        expect(lab).to_contain_text("已完成 0 / 5 步")
        old_sessions = page.request.get(url).json()["lab"]["sessions"]
        with patch("pliac.ml_lab.VERSION", "synthetic-updated-contract"):
            page.reload()
            expect(lab.get_by_role("heading", name="实验版本已更新")).to_be_visible()
            expect(lab.get_by_role("button", name="训练并验证")).to_have_count(0)
            lab.get_by_role("button", name="保留旧轮次并开始新版实验").click()
            expect(lab).to_contain_text("实操练习")
            expect(lab).to_contain_text("已完成 0 / 5 步")
            current = page.request.get(url).json()
            assert current["lab"]["sessions"][:-1] == old_sessions
            assert not current["restart_required"]
        lab.get_by_role("link", name="返回学习材料").click()
        expect(lab).to_have_count(0)
        assert not errors, errors
        browser.close()
    print("PASS: five real experiment steps, draft/reload recovery, frozen test, export, mobile and return navigation; no browser errors")


if __name__ == "__main__":
    main()
