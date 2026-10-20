"""Chromium + real WSL Bash + sanitized export + course diagnosis, all isolated."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile

from playwright.sync_api import expect, sync_playwright
from test_ui_documents import isolated_application

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "scripts")]
from build_linux_course import COURSE_ID, DEST
from install_course_draft import install
from pliac.linux_lab import linux_path
from learning_agent.course_catalog import resolve_course


def main():
    output = ROOT / "outputs/verification/linuxlab"
    output.mkdir(parents=True, exist_ok=True)
    report = {"page_errors": [], "temporary_stores": True, "checks": []}
    with tempfile.TemporaryDirectory() as temp, isolated_application(Path(temp)) as (base, store, documents):
        install(DEST / "course.json", store)
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page(viewport={"width": 1440, "height": 1100})
            page.on("pageerror", lambda e: report["page_errors"].append(str(e)))
            page.goto(base + "/manage/courses")
            page.locator(f'[data-course-id="{COURSE_ID}"] .activity-course').click()
            expect(page.locator("#modeNotice")).to_contain_text("草稿试跑")
            expect(page.locator(".stage")).to_have_count(9)
            expect(page.locator("#createRun")).to_be_enabled()
            page.locator("#createRun").click()
            expect(page.locator("#launchCommand")).not_to_be_empty()
            binding_id = page.locator("#runs").input_value()
            course = resolve_course(store, COURSE_ID)
            folder = course.output_dir / "linuxlab/runs" / binding_id
            args = ["wsl", "-d", "Ubuntu", "--", "python3", linux_path(ROOT / "tests/linuxlab_wsl_scenario.py"),
                    "--lab", linux_path(Path.home() / "Desktop/LinuxLab"), "--manifest", linux_path(folder / "binding.json")]
            result = subprocess.run(args, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=100)
            assert result.returncode == 0, result.stderr
            report["native"] = json.loads(result.stdout)
            page.locator("#sync").click()
            expect(page.locator("#progress")).to_contain_text("1/9")
            expect(page.locator(".case")).to_have_count(2)
            backup = page.locator('.case[data-case="check-2"]')
            expect(backup).to_contain_text("额外嵌套")
            expect(backup.locator('a[href*="node_id=cp"]').first).to_be_visible()
            expect(backup).to_contain_text("待核验")
            page.screenshot(path=str(output / "diagnosis.png"), full_page=True)
            backup.locator(".optional-reflection > summary").click()
            assert not backup.locator('textarea').evaluate("element => element.required")
            before = len(page.request.get(base + "/api/linux-lab/runs/" + binding_id, params={
                "course_id": COURSE_ID, "student_id": page.locator("#studentId").input_value(), "mode": "preview"
            }).json()["summary"]["diagnosis"]["cases"][0]["learner_explanations"])
            backup.locator("[data-skip-reflection]").click()
            expect(page.locator("main > #status")).to_contain_text("已跳过")
            expect(backup.locator("blockquote")).to_have_count(before)
            backup.locator(".optional-reflection > summary").click()
            backup.locator('select[name="node_id"]').select_option("cp")
            backup.locator('textarea').fill("测试解释：目标目录预先存在，复制目录本身使它成为目标的子目录；需要先核对目录层级。")
            backup.locator('button[type="submit"]').click()
            expect(backup.locator("blockquote")).to_contain_text("测试解释")
            page.locator("#sync").click()
            expect(page.locator("main > #status")).to_contain_text("已同步")
            expect(backup.locator("blockquote")).to_have_count(1)
            with page.expect_download() as download:
                page.locator("#export").click()
            downloaded = json.loads(Path(download.value.path()).read_text(encoding="utf-8"))
            assert downloaded["summary"]["diagnosis"]["review_status"] == "draft"
            cp_assessment = downloaded['summary']['assessment']['nodes']['cp']
            assert len(cp_assessment['references']) == 2
            assert cp_assessment['outcome'] == 'difficulty'
            assert not (course.output_dir / "learners").exists()
            page.set_viewport_size({"width": 390, "height": 844})
            page.screenshot(path=str(output / "mobile.png"), full_page=True)
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1")
            report["checks"] += ["Management activity opens nine-stage native lab", "Real mid-operation typo and backup error map to concepts",
                                 "Evidence, hypotheses and questions are separately visible", "Learner explanation survives sync",
                                 "Diagnostic draft exports; preview creates no learner records", "Mobile page has no horizontal overflow"]
            browser.close()
    assert not report["page_errors"], report
    report["passed"] = True
    (output / "ui-native-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
