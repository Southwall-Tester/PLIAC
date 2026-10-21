"""Guest preview -> registration -> learning -> account-bound resume, in Chromium."""
import json
from pathlib import Path
import re
import tempfile

from playwright.sync_api import expect, sync_playwright
from test_ui_documents import isolated_application
from test_ui_journey import algorithmic_journey, complete_baseline

OUTPUT = Path(__file__).resolve().parents[1] / "outputs/verification/home"


def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    report = {"synthetic_only": True, "checks": [], "page_errors": []}
    def passed(text):
        report["checks"].append(text)
        print("PASS", text, flush=True)
    try:
        with tempfile.TemporaryDirectory() as tmp, isolated_application(Path(tmp), auth_required=True) as (base, store, _), algorithmic_journey(), sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page(viewport={"width": 1440, "height": 1000})
            page.on("pageerror", lambda error: report["page_errors"].append(str(error)))
            page.route("**/api/account/me", lambda route: route.fulfill(status=503, content_type="application/json", body="{}"))
            page.goto(base + "/")
            expect(page.locator(".course-card")).to_have_count(2)
            expect(page.locator("#pageError")).to_be_visible()
            page.unroute("**/api/account/me")
            page.locator("#retryLoad").click()
            expect(page.locator("#pageError")).to_be_hidden()
            expect(page.locator("#accountLink")).to_be_visible()
            expect(page.locator("pliac-assistant")).to_have_count(0)
            assert not store.output_dir.exists()
            page.screenshot(path=str(OUTPUT / "guest-desktop.png"), full_page=True)
            page.locator("#courseSearch").fill("机器学习")
            expect(page.locator(".course-card")).to_have_count(1)
            page.locator(".preview-course").click()
            expect(page.locator("#lessonTitle")).to_contain_text("样本")
            next_title = page.locator("#previewChapters button").nth(1).inner_text()
            page.locator("#previewChapters button").nth(1).click()
            expect(page.locator("#lessonTitle")).to_have_text(next_title)
            page.reload()
            expect(page.locator("#lessonTitle")).to_have_text(next_title)
            preview_url = page.url
            page.locator("#accountLink").click()
            expect(page.locator("#accountForm")).to_be_visible()
            from urllib.parse import parse_qs, urlsplit
            self_return = parse_qs(urlsplit(page.url).query)["next"][0]
            assert self_return == urlsplit(preview_url).path + "?" + urlsplit(preview_url).query
            page.go_back()
            expect(page.locator("#lessonTitle")).to_have_text(next_title)
            assert not store.output_dir.exists()
            page.screenshot(path=str(OUTPUT / "preview-desktop.png"), full_page=True)
            passed("Guest course search, chapter preview and refresh create no learner records")
            page.goto(base + "/preview?course_id=computer_organization_demo")
            expect(page.locator("#previewContent .katex").first).to_be_visible()
            page.set_viewport_size({"width": 390, "height": 844})
            page.locator("#themeButton").click()
            expect(page.locator("html")).to_have_class(re.compile("network-dark"))
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1")
            page.screenshot(path=str(OUTPUT / "preview-mobile-dark.png"), full_page=True)
            page.goto(base + "/courses")
            expect(page.locator(".course-card")).to_have_count(2)
            expect(page.locator("html")).to_have_class(re.compile("network-dark"))
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1")
            page.screenshot(path=str(OUTPUT / "guest-mobile-dark.png"), full_page=True)
            passed("Offline formulas, mobile layout and cross-page dark theme work")
            page.set_viewport_size({"width": 1440, "height": 1000})
            page.locator("#themeButton").click()
            page.locator('[data-course-id="ml_acceptance_demo"] .learning-course').click()
            page.wait_for_url(re.compile("/login\\?next="))
            assert "ml_acceptance_demo" in page.url
            page.screenshot(path=str(OUTPUT / "login.png"), full_page=True)
            page.set_viewport_size({"width": 390, "height": 844})
            page.locator("#themeButton").click()
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1")
            page.wait_for_function("document.getAnimations().every(a=>a.playState!=='running')")
            page.screenshot(path=str(OUTPUT / "login-mobile-dark.png"), full_page=True)
            page.locator("#themeButton").click()
            page.set_viewport_size({"width": 1440, "height": 1000})
            page.locator("#registerTab").click()
            page.locator("#username").fill("home-test-user")
            page.locator("#password").fill("synthetic-password")
            page.locator("#submitAccount").click()
            page.wait_for_url(re.compile("/learn\\?course_id=ml_acceptance_demo"))
            expect(page.locator("#onboarding")).to_be_visible()
            expect(page.locator("[data-known]:checked")).to_have_count(0)
            page.locator("#onboardContinue").click()
            complete_baseline(page)
            expect(page.locator("#readingWorkspace")).to_be_visible()
            page.goto(base + "/courses")
            expect(page.locator("#resumeLearning")).to_contain_text("继续学习")
            expect(page.locator("#resumePanel")).to_contain_text("1 节已学")
            expect(page.locator("#resumePanel")).to_contain_text("0 / 10 节已通过")
            expect(page.locator("pliac-assistant")).to_be_attached()
            page.screenshot(path=str(OUTPUT / "account-desktop.png"), full_page=True)
            page.locator("#resumeLearning").click()
            expect(page.locator("#readingWorkspace")).to_be_visible()
            passed("Start prompts login, registration returns to selected course, resume keeps real progress")
            page.goto(base + "/courses")
            page.locator("#accountLogout").click()
            expect(page.locator("#accountLink")).to_be_visible()
            expect(page.locator(".course-progress")).to_have_count(0)
            expect(page.locator("pliac-assistant")).to_have_count(0)
            assert page.request.get(base + "/api/home/progress").status == 401
            passed("Logout returns to browsing and removes personal progress and assistant")
            browser.close()
        assert not report["page_errors"], report["page_errors"]
        report["passed"] = True
    finally:
        (OUTPUT / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
