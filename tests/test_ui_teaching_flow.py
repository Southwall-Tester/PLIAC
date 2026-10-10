"""Browser evidence for automatic teaching triggers, not a real teaching trial."""
import asyncio
import json
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

from playwright.sync_api import expect, sync_playwright
from test_ui_documents import isolated_application
from learning_agent.acceptance_course import build_graph
from learning_agent.course_graph import CourseGraphError
from pliac.tutor import TeachingProposal
from pliac.learning_plan import PlanProposal

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "outputs/verification"


def main():
    calls = []
    plan_calls = []
    async def planner(context, config):
        plan_calls.append(context["goal"])
        await asyncio.sleep(1.5)
        node = build_graph()["nodes"][0]["id"]
        return PlanProposal(status="proposed", summary="合成测试学习范围", target_node_ids=[node],
            learning_order=[node], start_node_id=node, rationale="先核验目标知识", clarification=""), {"model": "synthetic-plan"}
    failed = False
    async def model(context, config):
        nonlocal failed
        reason = context["trigger"]["reason"]
        calls.append(reason)
        await asyncio.sleep(1.5)
        if reason == "reading_finished" and not failed:
            failed = True
            raise CourseGraphError("合成测试：模型暂时不可用", 502)
        action = "remediate" if reason == "assessment_evaluated" else "probe"
        if reason == "assessment_evaluated":
            assert context["diagnoses"][-1]["status"] == "needs_review"
        return TeachingProposal(response="合成补学活动" if action == "remediate" else "合成起点或复测活动",
            target_node_id=context["current_node_id"], action=action, rationale="结合已保存的真实测试输入安排",
            blocks=[], question="请根据任务继续学习", uncertainty="模拟模型仅验证工程"), {"model": "synthetic-flow-test"}

    OUTPUT.mkdir(parents=True, exist_ok=True)
    report = {"synthetic_model": True, "checks": [], "errors": []}
    with tempfile.TemporaryDirectory(prefix="pliac-flow-ui-") as folder:
        with isolated_application(Path(folder)) as (base, _, _), patch("pliac.tutor_api.configured_api", return_value=None), patch("pliac.tutor_api.generate_teaching", model), patch("pliac.learning_plan.generate_plan", planner), sync_playwright() as p:
            browser = p.chromium.launch(channel=os.environ.get("PLIAC_BROWSER_CHANNEL") or None)
            page = browser.new_page(viewport={"width": 1440, "height": 1100})
            page.on("pageerror", lambda error: report["errors"].append(str(error)))
            page.goto(base + "/app/courses/ml_acceptance_demo")
            page.get_by_role("button", name="设置学习起点").click()
            page.get_by_label("学习目标", exact=True).fill("合成测试：解释特征与标签")
            expect(page.get_by_label("由智能体接续安排学习")).to_be_checked()
            page.get_by_role("button", name="保存目标与起点").click()
            planning = page.get_by_role("region", name="学习范围规划")
            expect(planning.get_by_role("status")).to_contain_text("正在结合课程目标")
            page.reload()
            expect(planning.get_by_role("button", name="按这个范围开始学习")).to_be_visible(timeout=20000)
            assert len(plan_calls) == 1, plan_calls
            assert calls == [], "Planning must not start teaching before the learner adopts the scope"
            planning.get_by_role("button", name="按这个范围开始学习").click()
            flow = page.get_by_role("region", name="智能体学习进程")
            expect(flow.get_by_role("status")).to_contain_text("正在按采用的范围确认起点")
            page.reload()
            expect(flow.get_by_role("link", name="打开当前学习活动")).to_be_visible(timeout=20000)
            assert calls == ["plan_accepted"], calls
            flow.get_by_role("link", name="打开当前学习活动").click()
            expect(page.locator(".teaching-material")).to_contain_text("合成起点或复测活动")
            first_material = page.url
            report["checks"].append("Goal creates one persisted scope proposal across refresh; adopting it triggers one restored teaching activity")

            authored = build_graph()["nodes"][0]["check_task"]
            wrong = next(option["text"] for option in authored["options"] if option["id"] != authored["answer_key"])
            panel = page.get_by_role("region", name="理解核验")
            panel.get_by_label(wrong, exact=True).check()
            panel.get_by_role("button", name="保存作答并评价").click()
            expect(panel.get_by_role("heading", name="发现需要补学的内容")).to_be_visible(timeout=15000)
            expect(flow.get_by_role("status")).to_contain_text("正在根据核验结果调整")
            expect(flow).to_contain_text("新的活动已保存", timeout=15000)
            assert calls == ["plan_accepted", "assessment_evaluated"], calls
            assert page.url == first_material, "New activity must not replace the material under review"
            expect(panel.get_by_role("heading", name="发现需要补学的内容")).to_be_visible()
            flow.get_by_role("link", name="打开当前学习活动").click()
            expect(page.locator(".teaching-material")).to_contain_text("合成补学活动")
            report["checks"].append("Submitted answer is saved then evaluated; evidence schedules remediation without replacing old page")

            flow.get_by_role("button", name="本节已读，继续学习").click()
            expect(flow.get_by_role("alert")).to_contain_text("模型暂时不可用", timeout=15000)
            expect(page.locator(".teaching-material")).to_contain_text("合成补学活动")
            assert calls.count("reading_finished") == 1
            flow.get_by_role("button", name="按最新状态重试安排").click()
            expect(flow).to_contain_text("新的活动已保存", timeout=15000)
            flow.get_by_role("link", name="打开当前学习活动").click()
            expect(panel.get_by_role("button", name="保存作答并评价")).to_be_visible()
            assert calls.count("reading_finished") == 2
            student = page.evaluate("localStorage.getItem('pliac.local-learner')")
            state = page.request.get(base + f"/api/learning?course_id=ml_acceptance_demo&student_id={student}").json()
            assert len(state["learner"]["diagnoses"]) == 1
            assert len(state["workspace"]["learning_plans"]) == 1
            assert state["workspace"]["teaching_flow"]["active_plan_id"] == state["workspace"]["learning_plans"][0]["id"]
            assert len(state["workspace"]["assessments"]) == 2
            assert state["workspace"]["assessments"][-1]["exposed"] is False
            assert state["learner"]["states"][build_graph()["nodes"][0]["id"]]["status"] != "mastered"
            report["checks"].append("Reading finish cannot prove mastery; failed generation stops and explicit retry opens an unseen task")

            page.set_viewport_size({"width": 390, "height": 1200})
            if page.locator(".course-nav").is_visible():
                page.get_by_role("button", name="切换课程目录").click()
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            page.screenshot(path=str(OUTPUT / "guided-flow-mobile.png"), full_page=True)
            flow.get_by_role("button", name="暂停自动安排").click()
            expect(flow.get_by_role("button", name="恢复智能体安排")).to_be_visible()
            page.reload()
            expect(flow.get_by_role("button", name="恢复智能体安排")).to_be_visible()
            assert len(calls) == 4
            report["checks"].append("Pause persists after refresh and narrow layout has no page-level horizontal overflow")
            from learning_agent.api import resolve_course_store
            stored_task = resolve_course_store("ml_acceptance_demo").load_learner(student)["workspace"]["assessments"][-1]
            correct = next(option["text"] for option in stored_task["options"] if option["id"] == stored_task["answer_key"])
            panel.get_by_label(correct, exact=True).check()
            # Paused teaching still permits saving and evaluating the current task.
            panel.get_by_role("button", name="保存作答", exact=True).click()
            panel.get_by_role("button", name="按标准评价", exact=True).click()
            expect(planning.get_by_role("link", name="查看阶段总结")).to_be_visible(timeout=15000)
            planning.get_by_role("link", name="查看阶段总结").click()
            expect(page.locator(".stage-report")).to_be_visible()
            page.reload()
            expect(page.locator(".stage-report")).to_be_visible()
            assert len(calls) == 4, "Completed scope must not schedule another model call"
            final = page.request.get(base + f"/api/learning?course_id=ml_acceptance_demo&student_id={student}").json()
            assert len(final["workspace"]["stage_reports"]) == 1
            assert final["workspace"]["stage_reports"][0]["nodes"][build_graph()["nodes"][0]["id"]]["status"] == "mastered"
            report["checks"].append("Independent retest closes agreed scope, saves one report, survives refresh and stops automatic model calls")
            assert not report["errors"], report["errors"]
            browser.close()
    (OUTPUT / "guided-flow-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main()
