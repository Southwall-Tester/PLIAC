"""Real browser progress while a synthetic choice provider is awaiting output."""
import asyncio
import json
from pathlib import Path
import sys
import tempfile
import threading
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from playwright.sync_api import expect, sync_playwright
from pliac import choice_generation
from test_ui_documents import isolated_application
from test_ui_journey import algorithmic_journey, mark_known
from test_learning_workspace import platform_fixture, publish_synthetic

OUTPUT = ROOT / "outputs/verification/journey"


def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    report = {"synthetic_only": True, "page_errors": [], "checks": [], "choice_calls": 0}
    gate = threading.Event()
    try:
        with tempfile.TemporaryDirectory(prefix="pliac-choice-wait-ui-") as temporary, \
             isolated_application(Path(temporary)) as (base, store, _), \
             algorithmic_journey(), sync_playwright() as p:
            seed = Path(temporary) / "seed.json"
            seed.write_text(json.dumps(platform_fixture(), ensure_ascii=False), encoding="utf-8")
            store.seed_path = seed
            graph = publish_synthetic(store)
            synthetic_choices = choice_generation.ChoiceProvider.choices

            async def blocked_choices(items):
                report["choice_calls"] += 1
                while not gate.is_set():
                    await asyncio.sleep(.025)
                return await synthetic_choices(items)

            with patch.object(choice_generation.ChoiceProvider, "choices", side_effect=blocked_choices):
                browser = p.chromium.launch()
                page = browser.new_page(viewport={"width": 1440, "height": 1000})
                page.on("pageerror", lambda error: report["page_errors"].append(str(error)))
                page.goto(base + "/learn?course_id=" + graph["id"])
                expect(page.locator("#onboarding")).to_be_visible()
                mark_known(page, "b", "unsure")
                page.locator("#onboardContinue").click()
                expect(page.locator("#journeyStatus")).to_have_text("正在准备基础核验题选项…")
                expect(page.locator("#journeyProgress")).to_be_visible()
                before = page.locator("#journeyElapsed").inner_text()
                page.wait_for_function(
                    "text=>document.getElementById('journeyElapsed').textContent!==text", arg=before)
                assert page.locator("#journeyProgressBar").get_attribute("aria-valuenow") is None
                page.screenshot(path=str(OUTPUT / "baseline-options-preparing.png"), full_page=True)
                gate.set()
                expect(page.locator("#baselinePanel")).to_be_visible(timeout=15000)
                expect(page.locator("[data-baseline-choice]")).to_have_count(3)
                assert report["choice_calls"] == 1
                page.reload()
                expect(page.locator("#baselinePanel")).to_be_visible()
                assert report["choice_calls"] == 1
                page.locator("[data-baseline-choice]").first.check()
                gate.clear()
                page.locator("#baselineForm button[type=submit]").click()
                expect(page.locator("#personalRoute")).to_be_visible(timeout=15000)
                page.locator("#beginRoute").click()
                expect(page.locator("#learningRequest")).to_be_visible()
                expect(page.locator("#learningRequestLabel")).to_have_text("正在准备本节练习…")
                assert page.locator("#learningRequest progress").get_attribute("value") is None
                before = page.locator("#learningRequestElapsed").inner_text()
                page.wait_for_function(
                    "text=>document.getElementById('learningRequestElapsed').textContent!==text", arg=before)
                assert report["choice_calls"] == 2
                page.screenshot(path=str(OUTPUT / "lesson-options-preparing.png"), full_page=True)
                gate.set()
                expect(page.locator("#readingWorkspace")).to_be_visible(timeout=15000)
                expect(page.locator("#learningRequest")).to_be_hidden()
                expect(page.locator("#answerChoices input")).to_have_count(3)
                page.reload()
                expect(page.locator("#readingWorkspace")).to_be_visible()
                assert report["choice_calls"] == 2
                assert not report["page_errors"]
                report["checks"] = [
                    "Baseline preparation shows an indeterminate progress bar and real elapsed time",
                    "Lesson preparation shows real waiting feedback before the next response returns",
                    "Refreshing prepared questions and lessons reuses the saved option sets",
                ]
                report["passed"] = True
                browser.close()
    finally:
        gate.set()
        (OUTPUT / "choice-waiting-report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
