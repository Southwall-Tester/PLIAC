"""Scoped generation, practice and contextual PDF UI; synthetic model outputs."""
import asyncio
import json
from pathlib import Path
import tempfile
import threading
from unittest.mock import patch

from playwright.sync_api import sync_playwright, expect
from test_ui_documents import isolated_application, app
from learning_agent.acceptance_course import AcceptanceCourseStore
from learnmargin.demo import demo_lesson
from learnmargin.models import APIConfig
from learnmargin.provider import ProviderError
from pliac import margin, choice_generation
from pliac.margin_graph import overview_map

OUT = Path(__file__).resolve().parents[1] / "outputs/verification"


class SyntheticProvider:
    usage = []
    async def __aenter__(self): return self
    async def __aexit__(self, *args): pass


async def synthetic_lesson(request, docs, *args):
    # Delayed completion also checks that a newly generated version replaces
    # an already visible older one when polling notices completion.
    await asyncio.sleep(.2)
    lesson = demo_lesson()
    lesson.title = "Synthetic scoped lesson"
    refs = [f"{d.id}:{u.index}" for d in docs for u in d.units]
    for section in lesson.sections:
        section.source_refs = refs[:1]
    lesson.sources = [lesson.sources[0]]
    lesson.sources[0].ref = refs[0]
    return lesson


async def synthetic_map(lesson, provider, progress=None):
    return overview_map(lesson)


async def synthetic_choices(items):
    """The legacy artifact remains unchanged; only its answer cache is upgraded."""
    result = []
    for item in items:
        texts = (["P(R|S)=2/5，R与S独立。", "P(R|S)=1/10，R与S不独立。", "P(R|S)=1/4，R与S独立。"]
                 if "40" in item["prompt"] else
                 ["P(A|B)以戴眼镜的10人为分母，P(B|A)以社团成员12人为分母。",
                  "两个条件概率都以全班30人为分母。", "两个条件概率都以同时满足条件的6人为分母。"])
        result.append({"item_id": item["item_id"],
                       "options": [{"id": chr(65 + i), "text": text} for i, text in enumerate(texts)],
                       "answer_key": "A"})
    return choice_generation.ChoiceReply(items=result)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    with patch.dict(app.state._state, {"auth_required": False}), \
         tempfile.TemporaryDirectory() as tmp, isolated_application(Path(tmp)) as (base, default, _), \
         patch.object(margin, "configured_api", return_value=APIConfig(base_url="http://localhost", model="synthetic")), \
         patch.object(margin, "Provider", return_value=SyntheticProvider()), \
         patch.object(margin, "generate_lesson", side_effect=synthetic_lesson), \
         patch.object(margin, "generate_map", side_effect=synthetic_map), \
         patch.object(choice_generation.ChoiceProvider, "choices", side_effect=synthetic_choices):
        course = AcceptanceCourseStore(default)
        graph = course.load_graph()
        chapter = graph["chapters"][0]["id"]
        node = next(n for n in graph["nodes"] if n["chapter_id"] == chapter)
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page(viewport={"width": 1440, "height": 1000})
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto(base + "/course-reader?mode=author&course_id=ml_acceptance_demo")
            expect(page.locator("#scopeEmpty")).to_be_visible()
            expect(page.locator("body > header #pdfDownload")).to_have_count(0)
            expect(page.locator("#pdfDownload")).to_be_hidden()
            page.locator("#chapter").select_option(chapter)
            expect(page.locator("#chapter")).to_have_value(chapter)
            def generate():
                with page.expect_response(lambda r: r.request.method == "POST" and "/api/handouts?" in r.url) as response:
                    page.locator("#generate").click()
                job = response.value.json()
                assert response.value.status == 200, job
                page.wait_for_function("id=>new URL(location.href).searchParams.get('job_id')===id", arg=job["id"], timeout=60000)
                # A job URL is available as soon as its first readable prefix appears.
                expect(page.locator("#graphScreen")).to_be_visible(timeout=60000)
                return job
            release_stage = threading.Event()
            async def staged_lesson(*args):
                progress = args[-1]
                progress("整理内容总览与学习路线", 24)
                progress.detail({"task_id": "plan:outline", "phase": "planning", "status": "running",
                                 "label": "逐项安排概念与学习顺序"})
                progress.model_event({"request_id": "synthetic-plan", "phase": "request_started",
                                      "attempt": 1, "transport": "sse"})
                progress.model_event({"request_id": "synthetic-plan", "phase": "receiving",
                                      "response_chars": 1200, "reasoning_chars": 240, "attempt": 1,
                                      "transport": "sse"})
                while not release_stage.is_set():
                    await asyncio.sleep(.05)
                progress.model_event({"request_id": "synthetic-plan", "phase": "completed",
                                      "response_chars": 1200, "attempt": 1})
                progress.detail({"task_id": "plan:outline", "phase": "planning", "status": "completed",
                                 "label": "逐项安排概念与学习顺序"})
                return await synthetic_lesson(*args)
            with patch.object(margin, "generate_lesson", side_effect=staged_lesson):
                try:
                    with page.expect_response(lambda r: r.request.method == "POST" and "/api/handouts?" in r.url) as response:
                        page.locator("#generate").click()
                    chapter_job = response.value.json()
                    assert response.value.status == 200, chapter_job
                    def assert_generating():
                        expect(page.locator("#jobProgressDetail .hp-task")).to_have_text("逐项安排概念与学习顺序")
                        expect(page.locator("#jobProgressDetail .hp-step")).to_have_count(5)
                        expect(page.locator("#jobProgressDetail .hp-step[aria-current=step]")).to_contain_text("安排讲解")
                        expect(page.locator("#jobProgressDetail .hp-response")).to_contain_text("已接收 1,200 字符")
                        expect(page.locator("#jobProgressDetail .hp-response")).to_contain_text("思考输出 240 字符")
                        expect(page.locator("#jobProgressDetail .hp-sections")).to_be_hidden()
                        expect(page.locator("#generate")).to_be_hidden()
                        expect(page.locator("#scopeEmpty")).to_be_hidden()
                        expect(page.locator("#cancelJob")).to_be_visible()
                        expect(page.locator("#jobProgress")).to_have_attribute("value", "24")
                        expect(page.locator("#generationNotice")).to_contain_text("完成后会自动打开")
                    assert_generating()
                    before = page.locator("#jobProgressDetail .hp-elapsed").inner_text()
                    page.wait_for_function("text=>document.querySelector('#jobProgressDetail .hp-elapsed').textContent!==text", arg=before)
                    expect(page.locator("#jobProgress")).to_have_attribute("value", "24")
                    page.reload()
                    assert_generating()
                    assert page.locator("#jobProgressDetail .hp-elapsed").inner_text() != "已用时 0 秒"
                    page.route("**/api/handouts?*", lambda route: route.fulfill(
                        status=503, json={"detail": "合成进度查询暂时中断"}), times=1)
                    expect(page.locator("#error")).to_have_text("合成进度查询暂时中断", timeout=10000)
                    expect(page.locator("#error")).to_be_hidden(timeout=15000)
                    assert_generating()
                    page.locator("#parentScope").click()
                    expect(page.locator("#scopeEmpty")).to_be_visible()
                    expect(page.locator("#generate")).to_be_enabled()
                    page.locator("#chapter").select_option(chapter)
                    assert_generating()
                    page.screenshot(path=str(OUT / "scoped-unit-generating.png"), full_page=True)
                    page.set_viewport_size({"width": 390, "height": 844})
                    page.locator("#themeButton").click()
                    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1")
                    page.screenshot(path=str(OUT / "scoped-unit-generating-mobile-dark.png"), full_page=True)
                    page.locator("#themeButton").click()
                    page.set_viewport_size({"width": 1440, "height": 1000})
                finally:
                    release_stage.set()
                page.wait_for_function("id=>new URL(location.href).searchParams.get('job_id')===id", arg=chapter_job["id"], timeout=60000)
                expect(page.locator("#graphScreen")).to_be_visible(timeout=60000)
                expect(page.locator("#generationNotice")).to_be_hidden()
                expect(page.locator("#jobProgress")).to_be_hidden()
                expect(page.locator("#cancelJob")).to_be_hidden()
                expect(page.locator("#generate")).to_be_enabled()
            page.locator("#scopeNode").select_option(node["id"])
            expect(page.locator("#scopeEmpty")).to_be_visible()
            expect(page.locator("#graphScreen")).to_be_hidden()
            node_job = generate()
            assert node_job["scope"]["kind"] == "node"
            page.locator("#readMode").click()
            expect(page.locator("#readingScreen #pdfDownload")).to_be_visible()
            expect(page.locator("#lessonFrame")).to_have_attribute("data-ready", "true", timeout=30000)
            with page.expect_download() as downloaded:
                page.locator("#pdfDownload").click()
            assert Path(downloaded.value.path()).read_bytes().startswith(b"%PDF")
            page.locator("#exerciseMode").click()
            expect(page.locator("#pdfDownload")).to_be_hidden()
            card = page.locator(".practice-card").first
            expect(card).to_be_visible()
            student = page.locator("#practiceStudent").input_value()
            expect(card.locator("input[type=radio]")).to_have_count(3)
            card.locator("input[type=radio]").first.check()
            card.locator(".practice-supplement > summary").click()
            card.locator("textarea").fill("Synthetic saved draft")
            card.locator('[data-action="draft"]').click()
            expect(page.locator("#practiceStatus")).to_have_text("草稿已保存。")
            page.reload()
            expect(page.locator("#graphScreen")).to_be_visible()
            page.locator("#exerciseMode").click()
            expect(card.locator("textarea")).to_have_value("Synthetic saved draft")
            expect(card.locator("input[type=radio]").first).to_be_checked()
            card.locator(".practice-supplement > summary").click()
            card.locator("textarea").fill("")
            card.locator('[data-action="hint"]').click()
            expect(card.locator(".practice-hint")).to_be_visible()
            expect(card.locator(".practice-solution")).to_have_count(0)
            card.locator('[data-action="answer"]').click()
            expect(page.locator("#practiceProgress")).to_contain_text("已作答 1")
            card.locator('[data-action="solution"]').click()
            expect(card.locator(".practice-solution")).to_be_visible()
            page.screenshot(path=str(OUT / "scoped-unit-practice.png"), full_page=True)
            card.locator("[data-section]").click()
            expect(page.locator("#pdfDownload")).to_be_visible()
            page.locator("#mapMode").click()
            page.locator("#conceptList button").first.click()
            page.locator("#studyConcept").click()
            expect(page.locator("#scopeEmpty")).to_be_visible()
            concept_job = generate()
            assert concept_job["scope"]["source_job_id"] == node_job["id"]
            assert concept_job["scope"]["kind"] == "concept"
            page.locator("#exerciseMode").click()
            expect(page.locator("#practiceProgress")).to_contain_text("已作答 0")
            page.locator("#parentScope").click()
            page.wait_for_function("id=>new URL(location.href).searchParams.get('job_id')===id", arg=node_job["id"])
            page.locator("#exerciseMode").click()
            expect(page.locator("#practiceProgress")).to_contain_text("已作答 1")
            # Generate a new version without replacing the older version's attempts.
            newer = generate()
            expect(page.locator("#versionChoice")).to_be_visible()
            page.locator("#unitVersion").select_option(node_job["id"])
            page.wait_for_function("id=>new URL(location.href).searchParams.get('job_id')===id", arg=node_job["id"])
            page.set_viewport_size({"width": 390, "height": 844})
            page.locator("#exerciseMode").click()
            expect(page.locator(".practice-options").first).to_be_visible()
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), "Mobile choices overflow"
            page.screenshot(path=str(OUT / "scoped-unit-practice-mobile.png"), full_page=True)
            page.locator("#readMode").click()
            expect(page.locator("#pdfDownload")).to_be_visible()
            expect(page.locator("#lessonFrame")).to_have_attribute("data-ready", "true", timeout=30000)
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), "Mobile horizontal overflow"
            page.screenshot(path=str(OUT / "scoped-unit-mobile.png"), full_page=True)
            raw = course._read_learner(student)
            assert len(raw["evidence"]) == 1 and raw["evidence"][0]["prompt_level"] == 1
            assert raw["evidence"][0]["context"]["answer_mode"] == "recognition"
            assert raw["evidence"][0]["context"]["supplement"] == ""
            assert raw["evidence"][0]["context"]["selected_option"]["id"]
            assert raw["diagnoses"] == []
            # A new scope failure must show the original stage in the actual reader.
            other = next(n for n in graph["nodes"] if n["id"] != node["id"])
            page.goto(base + "/course-reader?mode=author&course_id=ml_acceptance_demo&node_id=" + other["id"])
            expect(page.locator("#scopeEmpty")).to_be_visible()
            async def failed_lesson(*args):
                args[-1]("整理内容总览与学习路线", 24)
                raise ProviderError("合成模型响应超时（单次请求限时 180 秒）")
            with patch.object(margin, "generate_lesson", side_effect=failed_lesson):
                page.locator("#generate").click()
                expect(page.locator("#jobStatus")).to_contain_text(
                    "整理内容总览与学习路线：合成模型响应超时", timeout=20000)
            failed = next(j for j in margin.storage(course).jobs() if j["status"] == "failed")
            assert failed["failed_stage"] == "整理内容总览与学习路线"
            expect(page.locator("#generate")).to_have_text("重新生成图谱、讲义与习题")
            expect(page.locator("#scopeEmpty")).to_contain_text("重试")
            expect(page.locator("#cancelJob")).to_be_hidden()
            expect(page.locator("#jobProgress")).to_be_hidden()
            page.screenshot(path=str(OUT / "scoped-unit-failed-stage.png"), full_page=True)
            release_stage.clear()
            with patch.object(margin, "generate_lesson", side_effect=staged_lesson):
                try:
                    page.locator("#generate").click()
                    assert_generating()
                    page.locator("#cancelJob").click()
                    expect(page.locator("#jobStatus")).to_have_text("已取消")
                    expect(page.locator("#generate")).to_be_enabled()
                    expect(page.locator("#scopeEmpty")).to_contain_text("生成已取消")
                    expect(page.locator("#generationNotice")).to_be_hidden()
                    expect(page.locator("#jobProgress")).to_be_hidden()
                    elapsed = page.locator("#jobProgressDetail .hp-elapsed").inner_text()
                    page.wait_for_timeout(1200)
                    expect(page.locator("#jobProgressDetail .hp-elapsed")).to_have_text(elapsed)
                finally:
                    release_stage.set()
            # Student flow prepares the current fragment automatically and opens
            # linear reading. Generation controls stay in the author workspace.
            page.set_viewport_size({"width": 1440, "height": 1000})
            student_url = base + "/course-reader?course_id=ml_acceptance_demo&student_id=auto-student&node_id=" + node["id"] + "&view=read"
            release_stage.clear()
            with patch.object(margin, "generate_lesson", side_effect=staged_lesson):
                try:
                    with page.expect_response(lambda r: r.request.method == "POST" and "/api/handouts/prepare?" in r.url) as automatic:
                        page.goto(student_url)
                    automatic_job = automatic.value.json()
                    assert automatic.value.status == 200, automatic_job
                    expect(page.locator("#sourceLesson")).to_be_visible()
                    expect(page.locator("#generate")).to_be_hidden()
                    expect(page.locator("#chapter")).to_be_hidden()
                    expect(page.locator("#scopeNode")).to_be_hidden()
                    expect(page.locator("#generationNotice")).to_contain_text("正在为你准备")
                    expect(page.locator("#parentScope")).to_have_attribute("href", "/learn?course_id=ml_acceptance_demo&student_id=auto-student")
                    page.screenshot(path=str(OUT / "automatic-fragment-preparing.png"), full_page=True)
                    with page.expect_response(lambda r: r.request.method == "POST" and "/api/handouts/prepare?" in r.url) as resumed:
                        page.reload()
                    assert resumed.value.json()["id"] == automatic_job["id"]
                finally:
                    release_stage.set()
                expect(page.locator("#readingScreen")).to_be_visible(timeout=60000)
                expect(page.locator("#lessonFrame")).to_have_attribute("data-ready", "true", timeout=30000)
                expect(page.locator("#sourceLesson")).to_be_hidden()
                expect(page.locator("#regenerate")).to_be_visible()
                expect(page.locator("#courseOutline")).to_be_visible()
                page.locator("#mapMode").click()
                expect(page.locator("#graphScreen")).to_be_visible()
                page.locator("#readMode").click()
                page.locator("#regenerate").click()
                page.locator("#learningMode").select_option("exam_review")
                page.locator("#regenerationFeedback").fill("集中讲解易混点")
                with page.expect_response(lambda r: r.request.method == "POST" and "/api/handouts/prepare?" in r.url) as regenerated:
                    page.locator("#submitRegeneration").click()
                reviewed_job = regenerated.value.json()
                assert reviewed_job["learning_mode"] == "exam_review"
                assert reviewed_job["id"] != automatic_job["id"]
                page.wait_for_function("id=>new URL(location.href).searchParams.get('job_id')===id", arg=reviewed_job["id"], timeout=60000)
                expect(page.locator("#versionChoice")).to_be_visible()
                expect(page.locator("#readingScreen")).to_be_visible()
                page.screenshot(path=str(OUT / "automatic-fragment-reading.png"), full_page=True)
                assert margin.storage(course).job(automatic_job["id"])["status"] == "completed"
            assert errors == [], errors
            browser.close()
        report = {"scopes": [chapter_job["scope"]["kind"], node_job["scope"]["kind"], concept_job["scope"]["kind"]],
                  "versions": 2, "saved_attempts": 1, "failed_stage": failed["failed_stage"],
                  "generation_states": ["running", "resumed", "completed", "failed", "cancelled"],
                  "detailed_progress": ["task", "steps", "elapsed", "received_characters", "reasoning_count",
                                        "refresh_continuity", "poll_recovery", "cancelled_timer_stopped", "mobile_dark"],
                  "student_flow": ["automatic_prepare", "resume", "linear_reading", "graph", "regenerate_exam_review"],
                  "live_model_calls": 0, "page_errors": errors}
        (OUT / "learning-scopes.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(json.dumps(report))


if __name__ == "__main__": main()
