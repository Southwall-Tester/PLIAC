"""Browser verification against an isolated synthetic course publication.

Run: python tests/test_ui_v7.py
All learner data and publication writes use TemporaryDirectory. Screenshots and
the machine-readable report are the only persisted verification outputs.
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


def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    report = {"synthetic_only": True, "real_learner_trial": False,
              "persistent_course_store_used": False, "checks": [],
              "page_errors": [], "console_errors": [], "screenshots": []}
    server = None
    page = None
    browser = None
    playwright = None

    def passed(name):
        report["checks"].append(name)
        print("PASS", name, flush=True)

    def screenshot(label):
        filename = f"v7-{label}.png"
        page.screenshot(path=str(OUTPUT / filename), full_page=True)
        report["screenshots"].append(filename)

    try:
        with tempfile.TemporaryDirectory(prefix="learning-agent-ui-") as temporary:
            store = CourseGraphStore(output_dir=temporary)
            listener = socket.socket()
            listener.bind(("127.0.0.1", 0))
            port = listener.getsockname()[1]
            listener.close()
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
                        time.sleep(0.1)
                    else:
                        raise AssertionError("Temporary server did not start")

                    def get(path="", **params):
                        response = client.get("/api/course-graph" + path, params=params)
                        response.raise_for_status()
                        return response.json()

                    def student_record():
                        return get(student_id="UI_TEST_ONLY")["learner"]

                    playwright = sync_playwright().start()
                    if playwright:
                        browser = playwright.chromium.launch(headless=True)
                        context = browser.new_context(viewport={"width": 1600, "height": 1000},
                                                      device_scale_factor=1)
                        page = context.new_page()
                        page.on("pageerror", lambda error: report["page_errors"].append(str(error)))
                        page.on("console", lambda message: report["console_errors"].append(message.text)
                                if message.type == "error" and "Failed to load resource" not in message.text else None)
                        page.goto(url + "/author")
                        expect(page.locator("#nodeCount")).to_have_text("40")
                        expect(page.locator("#edgeCount")).to_have_text("68")
                        expect(page.locator("#graph canvas").first).to_be_visible()
                        expect(page.locator("#graphMessage")).to_be_hidden()
                        page.locator("#filtersButton").click()
                        page.locator('[data-chapter="all"]').click()
                        expect(page.locator("#listCount")).to_have_text("40")
                        for relation in ("prerequisite", "contains", "related", "confusable", "all"):
                            page.locator("#relationFilter").select_option(relation)
                            expect(page.locator("#relationFilter")).to_have_value(relation)
                            expect(page.locator("#graphMessage")).to_be_hidden()
                        page.locator("#fitButton").click()
                        screenshot("author-draft")
                        passed("author: 40 nodes, 68 relations, graph canvas and all four relation filters")

                        page.locator("#manageButton").click()
                        page.locator('[data-mode="blueprints"]').click()
                        expect(page.locator("#managerBody .judgment-card")).to_have_count(3)
                        page.locator("#managerBody .judgment-card details").first.locator("summary").click()
                        screenshot("training-blueprints")
                        passed("author: three draft training blueprints show steps and objective judge specifications")
                        page.locator('[data-mode="publish"]').click()
                        page.locator("#publishedBy").fill("UI_TEST_ONLY")
                        page.locator("#publishNote").fill("Synthetic UI test: this is not teacher approval.")
                        page.locator("#publishConfirm").check()
                        with page.expect_response(lambda r: r.url.endswith("/publish") and r.request.method == "POST") as pending:
                            page.locator('#publishForm button[type="submit"]').click()
                        assert pending.value.status == 409
                        expect(page.locator("#toast")).to_contain_text("未人工审核")
                        passed("author: unreviewed publication rejected through UI")

                        page.goto(url + "/knowledge")
                        expect(page.locator("#unpublished")).to_be_visible()
                        expect(page.locator("#workbench")).to_be_hidden()
                        screenshot("unpublished")
                        passed("student: unpublished course has no official learning graph")

                        fixture = get(view="draft")["graph"]
                        for item in [*fixture["nodes"], *fixture["edges"], *fixture["resources"]]:
                            item.update(review_status="reviewed", reviewer="UI_TEST_ONLY",
                                        reviewed_at="2026-10-08T00:00:00Z",
                                        review_note="Synthetic automated fixture; not actual teacher approval.")
                        response = client.put("/api/course-graph", json={"graph": fixture,
                                                                         "expected_version": fixture["version"]})
                        response.raise_for_status()
                        version = response.json()["graph"]["version"]
                        response = client.post("/api/course-graph/publish", json={"expected_version": version,
                            "published_by": "UI_TEST_ONLY", "note": "Synthetic temporary UI fixture, no real publication."})
                        response.raise_for_status()
                        public_graph = get()["graph"]
                        assert all("expected_answer" not in n for n in public_graph["nodes"])
                        passed("synthetic API publication: reviewed fixture only; student answers omitted")

                        page.reload()
                        expect(page.locator("#workbench")).to_be_visible()
                        expect(page.locator("#manageButton")).to_be_hidden()
                        page.locator("#filtersButton").click()
                        page.locator("#studentId").fill("UI_TEST_ONLY")
                        page.locator('#studentForm button[type="submit"]').click()
                        expect(page.locator("#learnerNote")).to_contain_text("UI_TEST_ONLY")
                        page.locator('[data-node="ml002"]').click()
                        expect(page.locator("#detailContent h2")).to_have_text("样本、特征与标签")
                        page.wait_for_function("document.querySelector('#resumeButton').hidden === false")
                        assert student_record()["profile"]["current_position"]["node_id"] == "ml002"
                        page.reload()
                        expect(page.locator("#detailContent h2")).to_have_text("样本、特征与标签")
                        passed("student: anonymous profile and selected node resume after reload")

                        page.locator("#filtersButton").click()
                        page.locator('[data-node="ml001"]').click()
                        page.locator('[data-tab="evidence"]').click()

                        def evidence(text, hint=0, source="quiz", relation=None):
                            page.locator("#evidenceOrigin").select_option("learner_expression")
                            page.locator("#evidenceType").select_option(source)
                            page.locator("#evidenceText").fill(text)
                            page.locator("#promptLevel").select_option(str(hint))
                            page.locator("#taskId").fill("UI_TASK_ONLY")
                            page.locator("#taskVersion").fill("1")
                            if relation:
                                page.locator("#evidenceForm details").filter(has=page.locator("#expressionRelation")).locator("summary").click()
                                page.locator("#expressionSource").select_option(relation["source"])
                                page.locator("#expressionTarget").select_option(relation["target"])
                                page.locator("#expressionRelation").fill(relation["relation"])
                                page.locator("#expressionQuote").fill(relation["quote"])
                            with page.expect_response(lambda r: r.url.endswith("/evidence") and r.request.method == "POST") as response:
                                page.locator('#evidenceForm button[type="submit"]').click()
                            assert response.value.status == 200, response.value.text()
                            value = response.value.json()["record"]
                            expect(page.locator(f'input[name="proof"][value="{value["id"]}"]')).to_be_visible()
                            return value

                        def diagnosis(proofs, status="mastered", expect_status=200):
                            for checkbox in page.locator('input[name="proof"]').all():
                                checkbox.uncheck()
                            for proof in proofs:
                                page.locator(f'input[name="proof"][value="{proof["id"]}"]').check()
                            page.locator("#diagnosisStatus").select_option(status)
                            page.locator("#diagnosisBasis").fill("UI_TEST_ONLY: synthetic adjudication; no real learner or teacher.")
                            page.locator("#diagnosisReviewer").fill("UI_TEST_ONLY")
                            with page.expect_response(lambda r: r.url.endswith("/diagnoses") and r.request.method == "POST") as response:
                                page.locator('#diagnosisForm button[type="submit"]').click()
                            assert response.value.status == expect_status, response.value.text()
                            return response.value.json()

                        guided = evidence("UI_TEST_ONLY low hint expression", hint=1)
                        assert student_record()["states"]["ml001"]["status"] == "uncertain"
                        diagnosis([guided], expect_status=400)
                        expect(page.locator("#toast")).to_contain_text("独立")
                        strong_hint = evidence("UI_TEST_ONLY high hint expression", hint=4)
                        diagnosis([strong_hint], expect_status=400)
                        self_report = evidence("UI_TEST_ONLY self assessment", source="self_assessment")
                        diagnosis([self_report], expect_status=400)
                        passed("student: raw expression becomes uncertain; hint 1/4 and self-assessment cannot prove mastery")

                        independent_text = "UI_TEST_ONLY：分类任务使用带有类别标签的样本进行学习。"
                        independent = evidence(independent_text, relation={
                            "source": "ml001", "target": "ml002", "relation": "使用带类别标签的样本",
                            "quote": independent_text})
                        result = diagnosis([guided, strong_hint, self_report, independent])
                        assert result["learner"]["states"]["ml001"]["status"] == "mastered"
                        expect(page.locator("#detailContent > .state-badge")).to_contain_text("已掌握")
                        record = result["record"]
                        assert set(record["evidence_ids"]) == {guided["id"], strong_hint["id"], self_report["id"], independent["id"]}
                        assert independent["id"] in page.locator("#detailContent").inner_text()
                        assert record["id"] in page.locator("#detailContent").text_content()
                        page.locator("#detailContent").evaluate("element => { element.scrollTop = 0; }")
                        screenshot("student-evidence")
                        history = page.locator(".detail-section").filter(has=page.locator("h3", has_text="诊断历史"))
                        history.locator("details summary").click()
                        history.scroll_into_view_if_needed()
                        screenshot("student-diagnosis-links")
                        passed("student: task-versioned independent evidence and reviewed diagnosis support mastery with visible references")

                        page.locator("#profileButton").click()
                        page.locator("#profileInterests").fill("科幻，动漫")
                        page.locator('#profileForm button[type="submit"]').click()
                        expect(page.locator("#toast")).to_contain_text("画像信息已保存")
                        assert student_record()["states"]["ml001"]["status"] == "mastered"
                        assert student_record()["profile"]["interests"] == ["科幻", "动漫"]
                        page.locator("#closeProfile").click()
                        passed("student: interests persist without changing knowledge judgment")

                        page.locator('[data-node="ml005"]').click()
                        page.locator('[data-tab="path"]').click()
                        expect(page.locator(".action-card")).to_be_visible()
                        expect(page.locator(".action-card")).to_contain_text("后续核验")
                        assert student_record()["actions"]
                        screenshot("student-next-step")
                        page.locator('[data-tab="detail"]').click()
                        link = page.locator('[data-resource="res_split"]')
                        expect(link).to_be_visible()
                        # Verify the actual selection and record, not external page availability.
                        context.route("https://**/*", lambda route: route.fulfill(status=200, body="Synthetic UI test destination"))
                        with page.expect_response(lambda r: r.url.endswith("/resource-use") and r.request.method == "POST") as used:
                            with page.expect_popup() as opened:
                                link.click()
                        assert used.value.status == 200, used.value.text()
                        opened.value.close()
                        assert student_record()["resource_uses"][-1]["resource_id"] == "res_split"
                        assert student_record()["states"]["ml001"]["status"] == "mastered"
                        passed("student: explained next step persisted; actual resource selection recorded without mastery credit")

                        # Inspect the active renderer through a read-only wrapper,
                        # preserving its existing setData behavior.
                        for origin, source_node, target_node, quote in (
                            ("system_completion", "ml003", "ml002", "UI_TEST_ONLY：模型使用样本输出预测。"),
                            ("model_inference", "ml004", "ml003", "UI_TEST_ONLY：模型拟合需要确定参数。"),
                        ):
                            response = client.post("/api/course-graph/evidence", json={
                                "student_id": "UI_TEST_ONLY", "course_version": version,
                                "node_id": source_node, "origin": origin, "source_type": "manual",
                                "prompt_level": None, "text": quote,
                                "context": {"task_id": "UI_STRUCTURE_ONLY", "task_version": 1},
                                "expressed_relations": [{"source": source_node, "target": target_node,
                                                         "relation": "合成结构核验", "quote": quote}],
                            })
                            response.raise_for_status()
                        page.reload()
                        expect(page.locator("#nodeCount")).to_have_text("40")
                        page.locator("#filtersButton").click()
                        page.evaluate("""() => {
                            const Graph = window.PIXI && window.CoursePixiGraph ? CoursePixiGraph : G6.Graph;
                            const original = Graph.prototype.setData;
                            Graph.prototype.setData = function(data) {
                                window.__uiRenderedData = structuredClone(data);
                                return original.call(this, data);
                            };
                        }""")
                        page.locator('[data-chapter="all"]').click()
                        page.locator("#relationFilter").select_option("all")
                        page.locator("#structureView").select_option("expressions")
                        expect(page.locator("#relationFilter")).to_be_disabled()
                        expect(page.locator("#listCount")).to_have_text("4")
                        page.wait_for_function("window.__uiRenderedData?.nodes.length === 4 && window.__uiRenderedData?.edges.length === 3")
                        expression_data = page.evaluate("window.__uiRenderedData")
                        assert {e["data"]["origin"] for e in expression_data["edges"]} == {
                            "learner_expression", "system_completion", "model_inference"}
                        for edge in expression_data["edges"]:
                            assert edge["data"]["type"] == "expressed"
                            assert edge["data"]["evidence_id"]
                            assert edge["style"]["endArrow"] is False
                            assert bool(edge["style"].get("lineDash")) == (edge["data"]["origin"] != "learner_expression")
                        inferred_nodes = [n for n in expression_data["nodes"] if n["style"].get("lineDash")]
                        assert {n["id"] for n in inferred_nodes} == {"ml003", "ml004"}
                        assert all("补全" in n["data"]["title"] or "推断" in n["data"]["title"] for n in inferred_nodes)
                        assert student_record()["states"]["ml001"]["status"] == "mastered"
                        screenshot("expression-structure")
                        page.locator("#structureView").select_option("course")
                        expect(page.locator("#relationFilter")).to_be_enabled()
                        expect(page.locator("#listCount")).to_have_text("40")
                        page.wait_for_function("window.__uiRenderedData?.nodes.length === 43 && window.__uiRenderedData?.edges.filter(e=>e.data.type!=='hierarchy').length === 68")
                        passed("two structures: actual 4-node/3-edge expression graph keeps provenance and inferred dashes; course restores 40/68")

                        page.goto(url + "/author")
                        expect(page.locator("#nodeCount")).to_have_text("40")
                        page.locator("#manageButton").click()
                        page.locator('[data-mode="node"]').click()
                        page.locator("#editPick").select_option("ml001")
                        original_title = public_graph["nodes"][0]["title"]
                        page.locator("#editTitle").fill(original_title + " UI draft only")
                        with page.expect_response(lambda r: r.url.endswith("/api/course-graph") and r.request.method == "PUT") as edited:
                            page.locator('#nodeEditor button[value="draft"]').click()
                        assert edited.value.status == 200, edited.value.text()
                        assert get(view="draft")["graph"]["nodes"][0]["title"] != original_title
                        assert get()["graph"]["nodes"][0]["title"] == original_title
                        assert get()["graph"]["version"] == version
                        passed("author: edited draft preserves published course and version")

                        page.goto(url + "/knowledge")
                        page.set_viewport_size({"width": 390, "height": 844})
                        expect(page.locator("#workbench")).to_be_visible()
                        expect(page.locator("#manageButton")).to_be_hidden()
                        page.locator("#filtersButton").click()
                        expect(page.locator("#profileInlineButton")).to_be_visible()
                        page.locator("#profileInlineButton").click()
                        expect(page.locator("#profileInterests")).to_have_value("科幻，动漫")
                        page.locator("#closeProfile").click()
                        page.wait_for_timeout(300)
                        dimensions = page.evaluate("({scroll:document.documentElement.scrollWidth,width:innerWidth})")
                        assert dimensions["scroll"] <= dimensions["width"], dimensions
                        screenshot("mobile")
                        passed("mobile: 390px page has no horizontal overflow and profile remains accessible")
                        assert not report["page_errors"], report["page_errors"]
                        assert not report["console_errors"], report["console_errors"]
                        passed("browser: no uncaught JavaScript or graph-rendering console errors")
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
        (OUTPUT / "ui-v7-results.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0 if report.get("passed") else 1


if __name__ == "__main__":
    raise SystemExit(main())
