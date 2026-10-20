"""Real WSL chat -> local bridge -> graph diagnosis -> desktop/mobile UI."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile

from playwright.sync_api import expect, sync_playwright
from test_ui_documents import isolated_application

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'src'), str(ROOT / 'scripts')]
from build_linux_course import COURSE_ID, DEST
from install_course_draft import install
from pliac.linux_lab import linux_path
from learning_agent.course_catalog import resolve_course


def main():
    output = ROOT / 'outputs/verification/linux-dialogue'
    output.mkdir(parents=True, exist_ok=True)
    record = dict(temporary_store=True, page_errors=[])
    with tempfile.TemporaryDirectory() as temp, isolated_application(Path(temp)) as (base, store, _):
        install(DEST / 'course.json', store)
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            page = browser.new_page(viewport={'width': 1440, 'height': 1000})
            page.on('pageerror', lambda e: record['page_errors'].append(str(e)))
            page.goto(base + '/linux-lab?course_id=' + COURSE_ID + '&mode=preview&student_id=synthetic-chat-ui')
            expect(page.locator('#createRun')).to_be_enabled()
            page.locator('#createRun').click()
            expect(page.locator('#launchCommand')).not_to_be_empty()
            binding = page.locator('#runs').input_value()
            course = resolve_course(store, COURSE_ID)
            folder = course.output_dir / 'linuxlab/runs' / binding
            native = subprocess.run(['wsl', '-d', 'Ubuntu', '--', 'python3', linux_path(ROOT / 'tests/linuxlab_wsl_scenario.py'),
                                     '--lab', linux_path(Path.home() / 'Desktop/LinuxLab'), '--manifest', linux_path(folder / 'binding.json'), '--chat'],
                                    capture_output=True, text=True, encoding='utf-8', timeout=100)
            assert native.returncode == 0, native.stderr
            record['native'] = json.loads(native.stdout)
            page.locator('#sync').click()
            expect(page.locator('#dialogueSummary')).to_contain_text('1/1')
            expect(page.locator('#dialogueRecords>details')).to_have_count(1)
            case = page.locator('.case[data-case^="dialogue-"]')
            expect(case).to_have_count(1)
            expect(case).to_contain_text('为什么cp复制后多了一层目录')
            expect(case).to_contain_text('不计作错误次数')
            expect(case.locator('a[href*="node_id=cp"]').first).to_be_visible()
            case.locator('.tutor-context>summary').click()
            expect(case.locator('.speech')).to_contain_text('本地资料模式')
            expect(case).to_contain_text('待核验')
            expect(page.locator('.case[data-case="check-2"]')).to_contain_text('为什么cp复制后多了一层目录')
            page.screenshot(path=str(output / 'desktop.png'), full_page=True)
            page.locator('#sync').click()
            expect(page.locator('.case[data-case^="dialogue-"]')).to_have_count(1)
            with page.expect_download() as download:
                page.locator('#export').click()
            data = json.loads(Path(download.value.path()).read_text(encoding='utf-8'))
            assert data['raw_report']['dialogue_evidence'][0]['learner']['origin'] == 'learner_expression'
            assert data['raw_report']['dialogue_evidence'][0]['assistant']['origin'] == 'local_material'
            assert not (course.output_dir / 'learners').exists()
            page.set_viewport_size({'width': 390, 'height': 844})
            page.screenshot(path=str(output / 'mobile.png'), full_page=True)
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1')
            page.locator('#studentId').fill('synthetic-chat-ui-new')
            page.locator('#loadStudent').click()
            expect(page.locator('#dialogueRecords>details')).to_have_count(0)
            expect(page.locator('#diagnoses')).to_contain_text('创建周目')
            assert not record['page_errors'], record
            browser.close()
    record.update(passed=True, checks=['Real native chat exported', 'Graph nodes and original problem linked',
                                      'Learner and assistance visible separately', 'Repeated sync idempotent',
                                      'Raw dialogue exported', 'No preview learner mutation', 'Mobile width accepted'])
    (output / 'result.json').write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(record, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
