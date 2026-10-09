"""Complete the real sklearn lab in Chromium with temporary synthetic records."""
import json
import tempfile
from pathlib import Path

from playwright.sync_api import expect, sync_playwright
from test_ui_documents import isolated_application

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "outputs/verification"


def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    report = {"synthetic_only": True, "checks": [], "page_errors": []}

    def passed(message):
        print("PASS", message, flush=True)
        report["checks"].append(message)

    try:
        with tempfile.TemporaryDirectory(prefix="pliac-ml-ui-") as tmp:
            with isolated_application(Path(tmp)) as (base, _, _), sync_playwright() as p:
                browser = p.chromium.launch()
                page = browser.new_page(viewport={"width": 1440, "height": 1000})
                page.on("pageerror", lambda e: report["page_errors"].append(str(e)))
                page.goto(base + "/ml-lab")
                page.locator("#studentId").fill("synthetic-ml-ui")
                page.locator("#identityForm button").click()
                expect(page.locator("#setup")).to_be_visible()
                page.locator("#scene").select_option("space")
                page.locator("#goal").fill("通过实际训练比较模型，理解数据划分与泛化表现。")
                page.locator("#startForm button").click()
                expect(page.locator("#sceneTitle")).to_have_text("轨道站 · 设备预警")
                page.locator("#target").select_option("target")
                page.locator("#inputChoice").select_option("receipt")
                page.locator("#timing").select_option("after")
                page.locator("#checkButton").click()
                expect(page.locator("#hints")).to_contain_text("提示 1")
                expect(page.locator("#progress")).to_have_text("0 / 5")
                expect(page.locator("#hints")).not_to_contain_text("用 x1、x2")
                page.reload()
                page.locator("#identityForm button").click()
                expect(page.locator("#hints")).to_contain_text("提示 1")
                passed("Failed artifact check gives staged help and persists through reload")
                page.locator("#target").select_option("target")
                page.locator("#inputChoice").select_option("sensors")
                page.locator("#timing").select_option("after")
                page.locator("#checkButton").click()
                expect(page.locator("#progress")).to_have_text("1 / 5")

                def experiment(depth, count, features="sensors", split="separate"):
                    page.locator("#depth").fill(str(depth))
                    page.locator("#features").select_option(features)
                    page.locator("#split").select_option(split)
                    page.locator("#runButton").click()
                    expect(page.locator("#runs tr")).to_have_count(count)
                    expect(page.locator("#runButton")).to_be_enabled()

                experiment(1, 1, split="reuse")
                page.locator("#chosenRun").select_option(index=1)
                page.locator("#checkButton").click()
                expect(page.locator("#progress")).to_have_text("1 / 5")
                experiment(1, 2)
                page.locator("#chosenRun").select_option(index=2)
                page.locator("#checkButton").click()
                expect(page.locator("#progress")).to_have_text("2 / 5")
                experiment(0, 3)
                page.locator("#chosenRun").select_option(index=3)
                page.locator("#interpretation").select_option("gap")
                page.locator("#checkButton").click()
                expect(page.locator("#progress")).to_have_text("3 / 5")
                expect(page.locator(".lab-grid > aside #labRest")).to_be_visible()
                assert page.locator("#recallToggle, #mixedPanel, #answerConfidence").count() == 0
                assert not page.locator("#runButton").is_disabled()
                page.screenshot(path=str(OUTPUT / "ml-lab-rhythm-sidebar.png"), full_page=True)
                page.locator("#dismissLabRest").click()
                expect(page.locator("#labRest")).to_be_hidden()
                page.reload()
                expect(page.locator("#labRest")).to_be_hidden()
                passed("Workload-planned sidebar pause is optional and stays dismissed; Lab has no recall or mixed-practice branch")
                experiment(4, 4)
                data = page.request.get(base + "/api/ml-lab?student_id=synthetic-ml-ui").json()
                valid = [r for r in data["active"]["runs"] if r["config"]["split"] == "separate"]
                best = max(valid, key=lambda r: r["result"]["validation_accuracy"])
                page.locator("#chosenRun").select_option(best["id"])
                page.locator("#basis").select_option("validation")
                page.locator("#note").fill("比较三种深度在同一份验证集上的表现，选择验证准确率最高的模型。")
                page.screenshot(path=str(OUTPUT / "ml-lab-desktop.png"), full_page=True)
                page.locator("#checkButton").click()
                expect(page.locator("#progress")).to_have_text("4 / 5")
                expect(page.locator("#runButton")).to_be_disabled()
                passed("Real experiments expose overlap, compare depth and freeze the selected model before test")
                page.locator("#testRole").select_option("report")
                page.locator("#note").fill("测试集用于报告封存模型对新数据的表现，后续模型选择需要另备测试数据。")
                page.locator("#checkButton").click()
                expect(page.locator("#progress")).to_have_text("5 / 5")
                expect(page.locator("#report")).to_contain_text("测试准确率")
                with page.expect_download() as download:
                    page.locator("#exportLab").click()
                exported = json.loads(Path(download.value.path()).read_text(encoding="utf-8"))
                assert exported["assessment"]["practice_complete"]
                assert len(exported["scripts"]) == 4
                assert exported["sessions"][0]["final"]["run_id"] == best["id"]
                passed("Report exports real metrics, evidence references, hints and reproducible Python scripts")
                page.set_viewport_size({"width": 390, "height": 844})
                page.locator("#themeButton").click()
                expect(page.locator("html")).to_have_class("network-dark")
                page.wait_for_function("document.getAnimations().every(a => a.playState !== 'running')")
                assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
                page.screenshot(path=str(OUTPUT / "ml-lab-mobile-dark.png"), full_page=True)
                page.locator("#transferButton").click()
                expect(page.locator("#progress")).to_have_text("0 / 5")
                expect(page.locator("#mode")).to_contain_text("迁移复测")
                expect(page.locator("#hints")).to_be_empty()
                page.reload()
                page.locator("#identityForm button").click()
                expect(page.locator("#mode")).to_contain_text("第 2 轮")
                passed("Mobile dark theme fits viewport; a fresh transfer round resumes with old records preserved")
                page.locator("#knowledge details summary").first.click()
                page.locator("#knowledge details a").first.click()
                expect(page.locator("#studentId")).to_have_value("synthetic-ml-ui")
                page.locator("#identityForm button[type=submit]").click()
                expect(page.locator("#handbook")).to_contain_text("已收录多次作答")
                expect(page.locator("#goals")).to_have_value("通过实际训练比较模型，理解数据划分与泛化表现。")
                page.locator("#onboardForm button[type=submit]").click()
                expect(page.locator('[data-node="roles"]')).to_have_class("node-button active")
                passed("Course remediation preserves identity, goal and lab evidence, opening the relevant knowledge node")
                assert not report["page_errors"], report["page_errors"]
                browser.close()
    finally:
        (OUTPUT / "ml-lab-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
