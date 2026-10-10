"""Scoped generation, practice and contextual PDF UI; synthetic model outputs."""
import asyncio
import json
from pathlib import Path
import tempfile
from unittest.mock import patch

from playwright.sync_api import sync_playwright, expect
from test_ui_documents import isolated_application
from learning_agent.acceptance_course import AcceptanceCourseStore
from learnmargin.demo import demo_lesson
from learnmargin.models import APIConfig
from learnmargin.provider import ProviderError
from pliac import margin
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


async def synthetic_map(lesson, provider):
    return overview_map(lesson)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp, isolated_application(Path(tmp)) as (base, default, _), \
         patch.object(margin, "configured_api", return_value=APIConfig(base_url="http://localhost", model="synthetic")), \
         patch.object(margin, "Provider", return_value=SyntheticProvider()), \
         patch.object(margin, "generate_lesson", side_effect=synthetic_lesson), \
         patch.object(margin, "generate_map", side_effect=synthetic_map):
        course = AcceptanceCourseStore(default)
        graph = course.load_graph()
        chapter = graph["chapters"][0]["id"]
        node = next(n for n in graph["nodes"] if n["chapter_id"] == chapter)
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page(viewport={"width": 1440, "height": 1000})
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto(base + "/course-reader?course_id=ml_acceptance_demo")
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
                expect(page.locator("#graphScreen")).to_be_visible()
                return job
            chapter_job = generate()
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
            card.locator("textarea").fill("Synthetic saved draft")
            card.locator('[data-action="draft"]').click()
            expect(page.locator("#practiceStatus")).to_have_text("草稿已保存。")
            page.reload()
            expect(page.locator("#graphScreen")).to_be_visible()
            page.locator("#exerciseMode").click()
            expect(card.locator("textarea")).to_have_value("Synthetic saved draft")
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
            page.locator("#readMode").click()
            expect(page.locator("#pdfDownload")).to_be_visible()
            expect(page.locator("#lessonFrame")).to_have_attribute("data-ready", "true", timeout=30000)
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), "Mobile horizontal overflow"
            page.screenshot(path=str(OUT / "scoped-unit-mobile.png"), full_page=True)
            raw = course._read_learner(student)
            assert len(raw["evidence"]) == 1 and raw["evidence"][0]["prompt_level"] == 1
            assert raw["diagnoses"] == []
            # A new scope failure must show the original stage in the actual reader.
            other = next(n for n in graph["nodes"] if n["id"] != node["id"])
            page.goto(base + "/course-reader?course_id=ml_acceptance_demo&node_id=" + other["id"])
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
            page.screenshot(path=str(OUT / "scoped-unit-failed-stage.png"), full_page=True)
            assert errors == [], errors
            browser.close()
        report = {"scopes": [chapter_job["scope"]["kind"], node_job["scope"]["kind"], concept_job["scope"]["kind"]],
                  "versions": 2, "saved_attempts": 1, "failed_stage": failed["failed_stage"],
                  "live_model_calls": 0, "page_errors": errors}
        (OUT / "learning-scopes.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(json.dumps(report))


if __name__ == "__main__": main()
