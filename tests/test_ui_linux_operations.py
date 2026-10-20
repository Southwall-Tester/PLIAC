"""Synthetic failure/reference/correction visible in the real browser UI."""
import json
from pathlib import Path
import tempfile

from playwright.sync_api import expect, sync_playwright
from test_ui_documents import isolated_application
from test_linux_lab import sample_report
from build_linux_course import COURSE_ID, DEST
from install_course_draft import install
from learning_agent.course_catalog import resolve_course
from learning_agent.course_graph import _atomic_json


def main():
    errors = []
    with tempfile.TemporaryDirectory() as temp, isolated_application(Path(temp)) as (base, store, _):
        install(DEST / 'course.json', store)
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            page = browser.new_page(viewport={'width': 1440, 'height': 1000})
            page.on('pageerror', lambda e: errors.append(str(e)))
            page.goto(base + '/linux-lab?course_id=' + COURSE_ID + '&mode=preview&student_id=synthetic-operations-ui')
            expect(page.locator('#createRun')).to_be_enabled()
            page.locator('#createRun').click()
            expect(page.locator('#launchCommand')).not_to_be_empty()
            folder = resolve_course(store, COURSE_ID).output_dir / 'linuxlab/runs' / page.locator('#runs').input_value()
            report = sample_report(json.loads((folder / 'binding.json').read_text(encoding='utf-8')))
            report['events'] = report['events'][:1] + [dict(id=2, phase=2, kind='passed', at='2026-10-10T00:01:00Z',
                                                          prompt_level=0, operation_cursor=2)]
            report['operations'][0].update(exit_code=1, flags=[])
            report['operations'].append(dict(report['operations'][0], sequence=2, exit_code=0, flags=['-a']))
            report.update(operation_total=2, phases_passed=2, reference_total=1,
                          reference_lookups=[dict(sequence=1, phase=2, source='notes', topic='cp',
                                                 at='2026-10-10T00:00:40Z', operation_cursor=1, after_completion=False)])
            _atomic_json(folder / 'telemetry.json', report)
            page.locator('#sync').click()
            case = page.locator('.case[data-case="operation-1"]')
            expect(case).to_have_count(1)
            expect(case).to_contain_text('1 次命令失败')
            expect(case).to_contain_text('查阅了相关资料')
            expect(case).to_contain_text('随后本关检查通过')
            expect(case.locator('a[href*="node_id=cp"]').first).to_be_visible()
            case.locator('details>summary').click()
            expect(case).to_contain_text('reference:1')
            expect(case).to_contain_text('证据可追溯：是')
            page.locator('#sync').click()
            expect(case).to_have_count(1)
            with page.expect_download() as downloaded:
                page.locator('#export').click()
            data = json.loads(Path(downloaded.value.path()).read_text(encoding='utf-8'))
            assert data['summary']['diagnosis']['cases'][0]['outcome'] == 'operation_corrected'
            page.set_viewport_size({'width': 390, 'height': 844})
            expect(case).to_be_visible()
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1')
            assert not errors, errors
            browser.close()
    print('PASS: operation diagnosis, graph links, reference evidence, repeat sync, export, desktop/mobile; no page errors')


if __name__ == '__main__':
    main()
