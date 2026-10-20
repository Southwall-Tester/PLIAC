"""Real browser: local accounts, entry calibration and an autonomous study route."""
import json
import asyncio
from contextlib import contextmanager
from pathlib import Path
import tempfile
import threading
from unittest.mock import patch

from playwright.sync_api import expect, sync_playwright

from test_ui_documents import isolated_application
from test_learning_workspace import platform_fixture, publish_synthetic
from test_journey import CONFIG
from learning_agent.course_graph import CourseGraphError
from learnmargin.demo import demo_lesson
from learnmargin.rendering import build_html
from pliac import journey, margin

OUTPUT = Path(__file__).resolve().parents[1] / "outputs/verification/journey"


@contextmanager
def algorithmic_journey():
    with patch.object(journey, "configured_api", side_effect=CourseGraphError("课程模型尚未配置。", 503)), \
         patch.object(margin, "configured_api", side_effect=CourseGraphError("课程模型尚未配置。", 503)):
        yield


def complete_baseline(page):
    """Finish selected prior-knowledge questions, or await a beginner's route."""
    page.wait_for_function("""() => ['baselinePanel','personalRoute'].some(id=>{
        const el=document.getElementById(id);return el&&!el.hidden&&el.getClientRects().length;
    })""", timeout=30000)
    if page.locator("#baselinePanel").is_visible():
        for question in page.locator(".baseline-question").all():
            question.locator("[data-baseline-choice]").first.check()
        page.locator("#baselineForm button[type=submit]").click()
    expect(page.locator("#personalRoute")).to_be_visible(timeout=15000)
    page.locator("#beginRoute").click()
    expect(page.locator("#readingWorkspace")).to_be_visible()


def mark_known(page, node_id, confidence="confident"):
    """Use the real chapter expander and checkbox before adjusting confidence."""
    field = page.locator(f'[data-known="{node_id}"]')
    group = field.locator("xpath=ancestor::details[1]")
    if not group.evaluate("element => element.open"):
        group.locator("summary").first.click()
    field.check()
    page.locator(f'[data-confidence="{node_id}"]').select_option(confidence)


def expect_beginner_defaults(page, count):
    expect(page.locator("#onboarding")).to_be_visible()
    expect(page.locator("#goals")).to_have_count(0)
    assert not page.locator("#profileDetails").evaluate("el=>el.open")
    expect(page.locator("#allNew")).to_have_count(0)
    expect(page.locator("[data-known]")).to_have_count(count)
    expect(page.locator("[data-known]:checked")).to_have_count(0)
    assert page.locator("[data-assess]").evaluate_all(
        "fields=>fields.length>0&&fields.every(field=>field.value==='new')")
    expect(page.locator("#onboardContinue")).to_contain_text("开始安排学习路线")


def expect_student_learning_only(page):
    """Internal diagnostic lists stay empty in the learner's document."""
    for panel, body in (("reportsPanel", "chapterReports"), ("handbookPanel", "handbook"),
                        ("selectedEvidence", "selectedEvidenceBody")):
        expect(page.locator("#" + panel)).to_be_hidden()
        expect(page.locator("#" + body)).to_be_empty()
    expect(page.locator("#reportsLink, #handbookLink")).to_have_count(0)
    content = page.locator("#studentWorkspace").text_content()
    for label in ("待核验", "原始证据", "诊断"):
        assert label not in content, (label, content)


def completed_handout(course_store, body, personalization=None):
    """Persist a real, portable LearnMargin HTML artifact from synthetic content."""
    graph, source_view = margin.graph_for(course_store)
    handouts = margin.storage(course_store)
    scope = margin.learning_scope.resolve(graph, body["scope"], handouts)
    lesson = demo_lesson()
    lesson.title = "合成个性化讲义 · 路径定位"
    job = dict(id=margin.new_id(), status="completed", stage="讲义已完成", progress=100,
               created_at=margin.now(), course_id=graph["id"], course_version=graph["version"],
               source_view=source_view, chapter_id=scope["chapter_id"], scope=scope,
               title=lesson.title, error=None, **(personalization or {}))
    directory = handouts.directory("jobs", job["id"])
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "lesson.html").write_text(build_html(lesson), encoding="utf-8")
    (directory / "lesson.json").write_text(lesson.model_dump_json(), encoding="utf-8")
    handouts.save_job(job)
    return job


def expect_planning_progress(page):
    expect(page.locator("#journeyProgress")).to_be_visible()
    expect(page.locator("#journeyProgressBar")).to_have_attribute("role", "progressbar")
    assert page.locator("#journeyProgressBar").get_attribute("aria-valuenow") is None
    expect(page.locator("#journeyStatus")).to_contain_text("规划路线", timeout=10000)
    expect(page.locator("#journeyElapsed")).to_contain_text("已用时")
    before = page.locator("#journeyElapsed").inner_text()
    page.wait_for_function("before=>document.getElementById('journeyElapsed').textContent!==before", arg=before)


def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    report = {"synthetic_only": True, "checks": [], "page_errors": [], "model_calls": 0}
    contexts, prepares, assessments = [], [], []
    model_gate = threading.Event()

    async def model(context):
        contexts.append(context)
        while not model_gate.is_set():
            await asyncio.sleep(.025)
        if context.get("assessment_mode") == "profile_only":
            return journey.RouteReply(summary="从路径定位起步，逐步练习文本搜索与 Shell 自动化。",
                                      teaching_approach="按基础概念、演示与独立练习推进。",
                                      priorities=[dict(node_id="a", reason="从目标涉及的路径定位基础开始。",
                                                       focus="认识当前目录与文件路径。", pace="slow")],
                                      diagnosis=[])
        return journey.RouteReply(
            summary="围绕命令行目标，先校正路径定位，再练习文本搜索。",
            teaching_approach="先对比 ls 与 cd，再做独立操作。",
            priorities=[dict(node_id="a", reason="本次核验发现目录切换概念需要补强。",
                             focus="对比 ls 与 cd 的作用。", pace="slow")],
            diagnosis=[
                dict(node_id="a", quote="ls会切换目录", signal="needs_support", reason="列出目录与切换目录需要区分。"),
                dict(node_id="b", quote="搜索使用grep", signal="ready_to_practice", reason="已能指出合适的搜索命令。"),
            ])

    def register(page, username):
        page.locator("#registerTab").click()
        page.locator("#username").fill(username)
        page.locator("#displayName").fill("合成浏览器学习者")
        page.locator("#password").fill("Synthetic-pass-2026")
        page.locator("#submitAccount").click()
        expect(page.locator("#courseList")).to_be_visible()

    try:
        with tempfile.TemporaryDirectory(prefix="pliac-journey-ui-") as temporary, \
             patch.object(journey, "configured_api", return_value=CONFIG), \
             patch.object(journey.JourneyProvider, "plan", side_effect=model), \
             patch.object(margin, "configured_api", side_effect=CourseGraphError("课程模型尚未配置。", 503)), \
             isolated_application(Path(temporary), auth_required=True) as (base, store, _), \
             sync_playwright() as p:
            graph = platform_fixture()
            graph["title"] = "Linux 起点 · 合成验证课程"
            for node, title in zip(graph["nodes"], ["路径定位", "文本搜索", "管道组合", "Shell自动化"]):
                node["title"] = title
            graph["nodes"][0].update(check_question="ls 和 cd 分别做什么？", expected_answer="ls列出目录，cd改变当前目录。")
            graph["nodes"][1].update(check_question="搜索文本内容可以使用哪个命令？", expected_answer="grep")
            graph["nodes"][0]["check_task"]["options"] = [
                dict(id="A", text="ls会切换目录"), dict(id="B", text="ls列出目录，cd切换目录")]
            graph["nodes"][1]["check_task"]["options"] = [
                dict(id="A", text="搜索使用grep"), dict(id="B", text="搜索使用cd")]
            seed = Path(temporary) / "seed.json"
            seed.write_text(json.dumps(graph, ensure_ascii=False), encoding="utf-8")
            store.seed_path = seed
            publish_synthetic(store)
            browser = p.chromium.launch()
            page = browser.new_page(viewport={"width": 1440, "height": 1000})
            page.on("pageerror", lambda error: report["page_errors"].append(str(error)))
            page.on("request", lambda request: prepares.append(request.post_data_json)
                    if request.method == "POST" and "/api/handouts/prepare" in request.url else None)
            page.on("request", lambda request: assessments.append(request.post_data_json)
                    if request.method == "POST" and "/api/learning/journey/assessment" in request.url else None)
            page.goto(base + "/")
            expect(page.locator("#accountForm")).to_be_visible()
            page.screenshot(path=str(OUTPUT / "login-desktop.png"))
            register(page, "journey-one")
            first_user = page.request.get(base + "/api/account/me").json()["user"]
            card = page.locator(f'[data-course-id="{graph["id"]}"]')
            expect(card.locator(".handout-course")).to_have_count(0)
            expect(card.locator(".learning-course")).to_have_text("进入课程")
            card.locator(".learning-course").click()
            expect(page.locator("#journeyPanel")).to_be_visible()
            expect_beginner_defaults(page, len(graph["nodes"]))
            expect(page.locator("#identityForm")).to_be_hidden()
            page.set_viewport_size({"width": 390, "height": 844})
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1")
            page.screenshot(path=str(OUTPUT / "onboarding-mobile.png"), full_page=True)
            page.set_viewport_size({"width": 1440, "height": 1000})
            mark_known(page, "a", "confident")
            mark_known(page, "b", "unsure")
            expect(page.locator('[data-assess="c"]')).to_have_value("new")
            expect(page.locator('[data-assess="d"]')).to_have_value("new")
            expect(page.locator("#onboardContinue")).to_contain_text("核验已有基础")
            page.screenshot(path=str(OUTPUT / "course-self-assessment.png"), full_page=True)
            page.locator("#onboardForm button[type=submit]").click()
            expect(page.locator("#baselinePanel")).to_be_visible()
            expect(page.locator("[data-baseline]")).to_have_count(2)
            expect(page.locator('[data-baseline="c"]')).to_have_count(0)
            expect(page.locator('[data-baseline="d"]')).to_have_count(0)
            expect(page.locator(".baseline-question").filter(has=page.locator('[data-baseline="a"]'))).to_contain_text("我认为已经会了")
            page.locator('[data-baseline-choice="a"][value="A"]').check()
            page.locator('[data-baseline-choice="b"][value="A"]').check()
            assert page.locator("[data-baseline]").evaluate_all("fields=>fields.every(field=>field.value==='')")
            page.reload()
            expect(page.locator('[data-baseline-choice="a"][value="A"]')).to_be_checked()
            expect(page.locator('[data-baseline-choice="b"][value="A"]')).to_be_checked()
            page.locator("#baselineForm button[type=submit]").click()
            expect_planning_progress(page)
            page.screenshot(path=str(OUTPUT / "route-planning.png"), full_page=True)
            pending_reloads = []
            page.route("**/api/learning?*", lambda route: pending_reloads.append(route))
            model_gate.set()
            expect(page.locator("#personalRoute")).to_be_visible(timeout=15000)
            expect(page.locator("#beginRoute")).to_be_disabled()
            page.wait_for_timeout(100)
            assert pending_reloads
            for reload_request in pending_reloads:
                reload_request.continue_()
            page.unroute("**/api/learning?*")
            expect(page.locator("#beginRoute")).to_be_enabled()
            expect(page.locator("#journeyProgress")).to_be_hidden()
            expect(page.locator("#routeSummary")).to_contain_text("校正路径定位")
            page.locator("#entryCalibration summary").click()
            expect(page.locator("#entryCalibration")).to_contain_text("发现了需要补强的环节")
            expect(page.locator("#entryCalibration")).to_contain_text("表现比自评更熟练")
            expect(page.locator("#entryCalibration")).to_contain_text("ls会切换目录")
            page.screenshot(path=str(OUTPUT / "calibrated-route.png"), full_page=True)
            report["checks"].append("Initial defaults are new; two selected learned topics produce exactly two calibration questions")
            report["checks"].append("Planning shows the real model stage and increasing elapsed time without a fabricated percentage")
            report["checks"].append("A ready route waits for the updated learner snapshot before enabling lesson entry")
            assert contexts[0]["self_assessments"]["a"] == "confident"
            assert contexts[0]["self_assessments"]["b"] == "unsure"
            assert {question["node_id"] for question in contexts[0]["questions"]} == {"a", "b"}
            assert all(answer["choice_id"] == "A" and answer.get("text", "") == ""
                       for answer in assessments[0]["answers"])
            first_record = store.load_learner(first_user["student_id"])
            assert all(state["status"] != "mastered" for state in first_record["states"].values())
            assert not first_record["diagnoses"]
            assert first_record["workspace"]["journey"]["active"]["model_diagnosis"]
            page.locator("#beginRoute").click()
            expect(page.locator("#readingWorkspace")).to_be_visible()
            expect(page.locator("#lessonContent h3").first).to_contain_text("路径定位")
            expect(page.locator("#autoLessonStatus")).to_contain_text("课程讲解和练习已就绪", timeout=15000)
            assert prepares and prepares[-1]["scope"] == {"node_id": "a"}
            assert prepares[-1]["student_id"] == first_user["student_id"]
            assert prepares[-1]["assistant_owner"] == first_user["assistant_owner"]
            expect_student_learning_only(page)
            page.screenshot(path=str(OUTPUT / "current-learning.png"), full_page=True)
            assert page.locator("#readingWorkspace").evaluate("el=>getComputedStyle(el).gridTemplateColumns.split(' ').length") == 1
            lesson_box = page.locator("#lessonPanel").bounding_box()
            practice_box = page.locator("#taskPanel").bounding_box()
            assert practice_box["y"] >= lesson_box["y"] + lesson_box["height"]
            page.screenshot(path=str(OUTPUT / "initial-reading-desktop.png"), full_page=True)
            page.set_viewport_size({"width": 390, "height": 844})
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1")
            page.screenshot(path=str(OUTPUT / "initial-reading-mobile.png"), full_page=True)
            page.locator('[name=answerChoice][value="B"]').check()
            page.locator("#answerConfidence").select_option("unsure")
            page.locator("#answerForm button[type=submit]").click()
            expect(page.locator("#responses")).to_contain_text("ls列出目录，cd切换目录")
            response = store.load_learner(first_user["student_id"])["workspace"]["lessons"][-1]["responses"][-1]
            assert response["context"]["choice_id"] == "B"
            assert response["context"]["free_text"] == ""
            assert response["context"]["selection"]["option_text"] == "ls列出目录，cd切换目录"
            page.set_viewport_size({"width": 1440, "height": 1000})
            report["checks"].append("Begin route starts a lesson and prepares scoped personalized content automatically")
            report["checks"].append("Onboarding, baseline and lesson practice complete with clicks only; pre-generation content and practice form one column on desktop/mobile")
            with patch.object(margin, "start_generation", side_effect=completed_handout):
                page.reload()
                expect(page.locator("#personalizedLessonFrame")).to_have_attribute("data-ready", "true", timeout=30000)
            frame = page.frame_locator("#personalizedLessonFrame")
            expect(frame.locator("h1").first).to_have_text("合成个性化讲义 · 路径定位")
            expect(frame.locator(".sheet").first).to_be_visible()
            assert page.locator("#personalizedLessonFrame").evaluate("el => !!el.contentWindow.learnmarginReport")
            expect(page.locator("#lessonContent")).to_be_hidden()
            expect(page.locator("#questionText")).not_to_be_empty()
            expect(page.locator("pliac-assistant").get_by_role("textbox", name="向学习助手提问")).to_be_visible()
            expect_student_learning_only(page)
            page.screenshot(path=str(OUTPUT / "learnmargin-main-desktop.png"), full_page=True)
            page.set_viewport_size({"width": 390, "height": 844})
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1")
            assert page.locator("#personalizedLessonFrame").evaluate(
                "el => el.contentDocument.documentElement.scrollWidth <= el.clientWidth + 1")
            page.screenshot(path=str(OUTPUT / "learnmargin-main-mobile.png"), full_page=True)
            page.set_viewport_size({"width": 1440, "height": 1000})
            page.reload()
            expect(page.locator("#personalizedLessonFrame")).to_have_attribute("data-ready", "true", timeout=30000)
            expect(page.locator("#lessonContent")).to_be_hidden()
            report["checks"].append("Completed real LearnMargin artifact replaces the static lesson on desktop and mobile; practice and right-side AI remain")
            page.locator("#overviewTab").click()
            expect(page.locator("#courseOverview")).to_be_visible()
            expect(page.locator("#courseMap")).to_have_attribute("data-ready", "true")
            expect(page.locator('[data-node="a"]')).to_be_visible()
            page.locator("#journeyTab").click()
            expect(page.locator('[data-route-node="a"]')).to_contain_text("当前学习")
            page.reload()
            expect(page.locator("#personalRoute")).to_be_visible()
            expect(page.locator("#routeSummary")).to_contain_text("校正路径定位")
            page.set_viewport_size({"width": 390, "height": 844})
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1")
            page.screenshot(path=str(OUTPUT / "route-mobile.png"), full_page=True)
            report["checks"].append("Course overview and route reflect the saved lesson; refresh and mobile layout retain it")
            page.set_viewport_size({"width": 1440, "height": 1000})
            page.locator("#logoutButton").click()
            expect(page.locator("#accountForm")).to_be_visible()
            register(page, "journey-two")
            second_user = page.request.get(base + "/api/account/me").json()["user"]
            assert first_user["student_id"] != second_user["student_id"]
            assert first_user["assistant_owner"] != second_user["assistant_owner"]
            page.locator(f'[data-course-id="{graph["id"]}"] .learning-course').click()
            expect_beginner_defaults(page, len(graph["nodes"]))
            expect(page.locator("#personalRoute")).to_be_hidden()
            expect(page.locator("#goals")).to_have_count(0)
            expect(page.locator("#background")).to_have_value("")
            forbidden = page.request.get(base + "/api/learning/journey",
                                         params={"student_id": first_user["student_id"], "course_id": graph["id"]})
            assert forbidden.status == 403
            assert not store.load_learner(second_user["student_id"]).get("workspace", {}).get("journey")
            assert store.load_learner(first_user["student_id"])["workspace"]["journey"]["active"]["route"]
            report["checks"].append("Switching account isolates the profile, route, evidence and assistant owner")
            model_gate.clear()
            page.locator("#onboardContinue").click()
            expect_planning_progress(page)
            expect(page.locator("#baselinePanel")).to_be_hidden()
            expect(page.locator("[data-baseline]")).to_have_count(0)
            second_requests = [item for item in assessments if item["student_id"] == second_user["student_id"]]
            assert len(second_requests) == 1 and second_requests[0]["answers"] == []
            assert contexts[-1]["assessment_mode"] == "profile_only"
            assert contexts[-1]["questions"] == []
            assert contexts[-1]["baseline"] == []
            page.reload()
            expect_planning_progress(page)
            assert len([item for item in assessments if item["student_id"] == second_user["student_id"]]) == 1
            model_gate.set()
            expect(page.locator("#personalRoute")).to_be_visible(timeout=15000)
            expect(page.locator("#routeSummary")).to_contain_text("从路径定位起步")
            second_record = store.load_learner(second_user["student_id"])
            assert not second_record["diagnoses"]
            assert not second_record["workspace"]["journey"]["active"]["model_diagnosis"]
            assert all(state["status"] != "mastered" for state in second_record["states"].values())
            page.reload()
            expect(page.locator("#personalRoute")).to_be_visible()
            assert len([item for item in assessments if item["student_id"] == second_user["student_id"]]) == 1
            report["checks"].append("A new beginner account skips questions, submits empty answers once and receives a saved route directly")
            assert not report["page_errors"], report["page_errors"]
            report.update(passed=True, model_calls=len(contexts))
            browser.close()
    finally:
        model_gate.set()
        (OUTPUT / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
