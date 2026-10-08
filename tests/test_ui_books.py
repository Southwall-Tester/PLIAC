"""Real-browser checks for book-informed review and action-follow-up UI.

Publication, teacher review and learners below are synthetic temporary fixtures.
Only screenshots and the JSON verification report persist under outputs.
"""
from __future__ import annotations

import json
import socket
import sys
import tempfile
import threading
import time
import traceback
from pathlib import Path
from unittest.mock import patch

import httpx
import uvicorn
from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from learning_agent import api
from learning_agent.course_graph import CourseGraphStore
from learning_agent.main import app

OUTPUT = ROOT / "outputs" / "verification"
STUDENT = "BOOKS_UI_SYNTHETIC_ONLY"


def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    report = {"synthetic_only": True, "real_learner_trial": False,
              "persistent_course_store_used": False, "checks": [],
              "page_errors": [], "console_errors": [], "screenshots": []}
    server = browser = playwright = page = thread = None

    def passed(name):
        report["checks"].append(name)
        print("PASS", name, flush=True)

    def screenshot(name):
        filename = f"books-{name}.png"
        page.screenshot(path=str(OUTPUT / filename), full_page=True)
        report["screenshots"].append(filename)

    try:
        with tempfile.TemporaryDirectory(prefix="books-ui-synthetic-") as temporary:
            store = CourseGraphStore(output_dir=temporary)
            initial_files = sorted(str(p.relative_to(temporary)) for p in Path(temporary).rglob("*"))
            with socket.socket() as listener:
                listener.bind(("127.0.0.1", 0))
                port = listener.getsockname()[1]
            url = f"http://127.0.0.1:{port}"
            server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port,
                                                   log_level="error", access_log=False))
            with patch.object(api, "store", store):
                thread = threading.Thread(target=server.run, daemon=True)
                thread.start()
                with httpx.Client(base_url=url, timeout=15) as client:
                    for _ in range(100):
                        try:
                            if client.get("/health").is_success:
                                break
                        except httpx.HTTPError:
                            pass
                        time.sleep(.1)
                    else:
                        raise AssertionError("Temporary server did not start")

                    def get(path="", **params):
                        response = client.get("/api/course-graph" + path, params=params)
                        response.raise_for_status()
                        return response.json()

                    def learner():
                        return get(student_id=STUDENT)["learner"]

                    playwright = sync_playwright().start()
                    browser = playwright.chromium.launch(headless=True)
                    context = browser.new_context(viewport={"width": 1600, "height": 1100}, device_scale_factor=1)
                    # Resource navigation is outside this UI test. Preserve the real
                    # anchor click and resource-use API while avoiding outside sites.
                    context.route("https://**/*", lambda route: route.fulfill(status=200,
                                  content_type="text/html", body="<p>Synthetic resource fixture</p>"))
                    page = context.new_page()
                    page.on("pageerror", lambda error: report["page_errors"].append(str(error)))
                    page.on("console", lambda message: report["console_errors"].append(message.text)
                            if message.type == "error" and "Failed to load resource" not in message.text else None)
                    page.goto(url + "/author")
                    expect(page.locator("#nodeCount")).to_have_text("40")
                    page.locator("#manageButton").click()
                    page.locator('[data-mode="audit"]').click()
                    expect(page.locator("#auditIssues > article")).to_have_count(2)
                    expect(page.locator("#bookReferences > article")).to_have_count(7)
                    expect(page.locator("#managerBody")).to_contain_text("2 项待核查提示")
                    expect(page.locator("#bookReferences")).to_contain_text("PDF 第")
                    expect(page.locator("#bookReferences")).to_contain_text("书内第")
                    screenshot("teacher-audit")
                    sources = page.locator("#managerBody details").filter(has=page.locator("summary", has_text="查看课程出处定位"))
                    sources.locator("summary").click()
                    expect(sources.locator("p")).to_have_count(8)
                    assert "待补具体定位" not in sources.inner_text()
                    sources.scroll_into_view_if_needed()
                    screenshot("source-locators")
                    page.locator("#bookReferences > article").first.scroll_into_view_if_needed()
                    screenshot("book-references")
                    passed("teacher audit: 2 review issues, 8 source locators, 7 books with PDF/printed pages")
                    current_files = sorted(str(p.relative_to(temporary)) for p in Path(temporary).rglob("*"))
                    assert current_files == initial_files, (initial_files, current_files)
                    passed("teacher audit and reference inspection do not write the course or learner store")

                    page.set_viewport_size({"width": 390, "height": 844})
                    page.locator("#bookReferences > article").first.scroll_into_view_if_needed()
                    dimensions = page.evaluate("""() => ({page:document.documentElement.scrollWidth,
                        viewport:innerWidth, dialog:document.querySelector('#manager').scrollWidth,
                        dialogClient:document.querySelector('#manager').clientWidth,
                        body:document.querySelector('#managerBody').scrollWidth,
                        bodyClient:document.querySelector('#managerBody').clientWidth})""")
                    assert dimensions["page"] <= dimensions["viewport"], dimensions
                    assert dimensions["dialog"] <= dimensions["dialogClient"] + 1, dimensions
                    assert dimensions["body"] <= dimensions["bodyClient"] + 1, dimensions
                    screenshot("teacher-mobile")
                    passed("teacher audit: 390px page, dialog and content have no horizontal overflow")

                    fixture = get(view="draft")["graph"]
                    fixture["resources"].append({**fixture["resources"][0],
                        "id": "books_ui_resource", "title": "BOOKS_UI_SYNTHETIC_ONLY 分类资料",
                        "node_ids": ["ml001"], "prerequisite_ids": [],
                        "applicable_segment": "Synthetic test lesson; not a real learning asset.",
                        "url": "https://example.test/books-ui-only"})
                    for item in [*fixture["nodes"], *fixture["edges"], *fixture["resources"]]:
                        item.update(review_status="reviewed", reviewer="BOOKS_UI_SYNTHETIC_ONLY",
                                    reviewed_at="2026-10-08T00:00:00Z",
                                    review_note="Synthetic automated fixture; not real teacher approval.")
                    response = client.put("/api/course-graph", json={"graph": fixture,
                                                                     "expected_version": fixture["version"]})
                    response.raise_for_status()
                    version = response.json()["graph"]["version"]
                    response = client.post("/api/course-graph/publish", json={"expected_version": version,
                        "published_by": "BOOKS_UI_SYNTHETIC_ONLY", "note": "Temporary synthetic UI fixture."})
                    response.raise_for_status()

                    page.set_viewport_size({"width": 1600, "height": 1100})
                    page.goto(url + "/")
                    expect(page.locator("#workbench")).to_be_visible()
                    page.locator("#studentId").fill(STUDENT)
                    page.locator('#studentForm button[type="submit"]').click()
                    expect(page.locator("#learnerNote")).to_contain_text(STUDENT)
                    page.locator('[data-node="ml001"]').click()
                    with page.expect_response(lambda r: "/recommendations?" in r.url) as pending:
                        page.locator('[data-tab="path"]').click()
                    recommendation = pending.value.json()
                    action_id = recommendation["actions"][0]["id"]
                    expect(page.locator("#recommendationTrace")).to_be_visible()
                    expect(page.locator("#recommendationTrace")).to_contain_text("推荐依据")
                    expect(page.locator("#actionHistory")).to_contain_text("待核验")
                    page.locator("#recommendationTrace details summary").click()
                    expect(page.locator("#recommendationTrace details")).to_contain_text("资源前置知识仍待核验")
                    page.locator("#recommendationTrace").scroll_into_view_if_needed()
                    screenshot("selection-and-pending")
                    assert recommendation["selection"]["frontier_node_ids"] == ["ml001"]
                    assert recommendation["action_history"][0]["outcome"] == "pending"
                    passed("student next step: actionable frontier, transparent exclusions and pending follow-up are visible")

                    before = learner()
                    with page.expect_response(lambda r: r.url.endswith("/resource-use") and r.request.method == "POST") as pending:
                        page.locator("#detailContent [data-resource]").first.click()
                    assert pending.value.status == 200, pending.value.text()
                    after = learner()
                    assert after["states"] == before["states"]
                    assert after["diagnoses"] == before["diagnoses"]
                    assert len(after["resource_uses"]) == len(before["resource_uses"]) + 1
                    assert after["states"]["ml001"]["status"] == "unknown"
                    passed("real resource anchor click persists selection without changing mastery or diagnoses")

                    page.locator('[data-tab="evidence"]').click()
                    page.locator("#evidenceOrigin").select_option("learner_expression")
                    page.locator("#evidenceType").select_option("quiz")
                    page.locator("#evidenceText").fill("BOOKS_UI_SYNTHETIC_ONLY：监督分类使用带有类别标签的样本学习，预测新样本属于哪个离散类别。")
                    page.locator("#promptLevel").select_option("0")
                    page.locator("#taskId").fill("BOOKS_UI_INDEPENDENT_TASK")
                    page.locator("#taskVersion").fill("1")
                    with page.expect_response(lambda r: r.url.endswith("/evidence") and r.request.method == "POST") as pending:
                        page.locator('#evidenceForm button[type="submit"]').click()
                    assert pending.value.status == 200, pending.value.text()
                    proof = pending.value.json()["record"]
                    expect(page.locator(f'input[name="proof"][value="{proof["id"]}"]')).to_be_visible()
                    page.locator(f'input[name="proof"][value="{proof["id"]}"]').check()
                    page.locator("#diagnosisStatus").select_option("mastered")
                    page.locator("#diagnosisBasis").fill("BOOKS_UI_SYNTHETIC_ONLY：新任务独立解释了标签和离散类别，经合成测试复核满足本题判据。")
                    page.locator("#diagnosisReviewer").fill("BOOKS_UI_SYNTHETIC_ONLY")
                    page.locator("#followUpAction").select_option(action_id)
                    screenshot("follow-up-form")
                    with page.expect_response(lambda r: r.url.endswith("/diagnoses") and r.request.method == "POST") as pending:
                        page.locator('#diagnosisForm button[type="submit"]').click()
                    assert pending.value.status == 200, pending.value.text()
                    diagnosis = pending.value.json()["record"]
                    assert diagnosis["follow_up_action_id"] == action_id
                    assert diagnosis["evidence_ids"] == [proof["id"]]
                    assert learner()["states"]["ml001"]["status"] == "mastered"
                    passed("UI saves a reviewed independent quiz diagnosis bound to the earlier teaching action")

                    with page.expect_response(lambda r: "/recommendations?" in r.url) as pending:
                        page.locator('[data-tab="path"]').click()
                    result = pending.value.json()
                    observation = next(a for a in result["action_history"] if a["action_id"] == action_id)
                    assert observation["outcome"] == "observed"
                    assert observation["observations"][0]["diagnosis_id"] == diagnosis["id"]
                    expect(page.locator("#actionHistory")).to_contain_text("已复核")
                    expect(page.locator("#actionHistory")).to_contain_text("本次判断")
                    observed_card = page.locator("#actionHistory article").filter(has_text="已复核")
                    observed_card.locator("details summary").click()
                    expect(observed_card).to_contain_text(action_id)
                    expect(observed_card).to_contain_text(proof["id"])
                    expect(observed_card).to_contain_text(diagnosis["id"])
                    observed_card.scroll_into_view_if_needed()
                    screenshot("observed-follow-up")
                    passed("action history shows observed outcome with persisted action, diagnosis and evidence links")

                    page.reload()
                    page.locator('[data-tab="path"]').click()
                    expect(page.locator("#actionHistory")).to_contain_text("已复核")
                    page.set_viewport_size({"width": 390, "height": 844})
                    page.locator("#actionHistory").scroll_into_view_if_needed()
                    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
                    screenshot("student-mobile-follow-up")
                    passed("follow-up survives reload; student next-step UI has no 390px horizontal overflow")
                    assert not report["page_errors"], report["page_errors"]
                    assert not report["console_errors"], report["console_errors"]
                    passed("no uncaught JavaScript or graph console errors")
        report["passed"] = True
    except Exception:
        report["passed"] = False
        report["failure"] = traceback.format_exc()
        print(report["failure"], flush=True)
        try:
            if page and not page.is_closed():
                screenshot("failure")
        except Exception:
            pass
    finally:
        if browser:
            browser.close()
        if playwright:
            playwright.stop()
        if server:
            server.should_exit = True
        if thread:
            thread.join(timeout=5)
        (OUTPUT / "books-ui-results.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0 if report.get("passed") else 1


if __name__ == "__main__":
    raise SystemExit(main())
