"""Reproducible local UI timings, not production latency or Web Vitals certification."""
import json
import platform
import statistics
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

from playwright.sync_api import expect, sync_playwright
from learning_agent.acceptance_course import AcceptanceCourseStore, DEMO_ID
from pliac.workspace import empty_workspace
from test_ui_documents import isolated_application
from test_personal_export import sample_material


def main():
    output = Path(__file__).resolve().parents[1] / 'outputs/verification'
    output.mkdir(parents=True, exist_ok=True)
    report = {'synthetic_only': True, 'created_at': datetime.now(timezone.utc).isoformat(),
              'environment': {'os': platform.system(), 'python': platform.python_version(),
                              'network': 'loopback, no throttling', 'viewport': [1440, 960]},
              'fixture': {'courses': 1, 'saved_materials': 200, 'provider_calls': 0},
              'measurement': 'Wall time from automation action through visible-state assertion and two animation frames; includes automation overhead. Not INP or server latency.',
              'samples_ms': {}, 'errors': []}
    with tempfile.TemporaryDirectory() as folder, isolated_application(Path(folder)) as (base, root, _), sync_playwright() as runtime:
        store = AcceptanceCourseStore(root)
        learner = store._read_learner('synthetic-performance')
        learner['workspace'] = empty_workspace()
        node = store.load_graph()['nodes'][0]['id']
        for index in range(200):
            turn = sample_material()
            turn.update(request_id=f'perf-{index:03d}', node_id=node, message=f'Synthetic question {index}', course_version=1)
            turn['proposal']['target_node_id'] = node
            turn['proposal']['response'] = f'Synthetic explanation {index}. ' * 40
            learner['workspace'].setdefault('tutor_turns', []).append(turn)
        store._commit(learner)
        browser = runtime.chromium.launch()
        report['environment']['browser'] = browser.version
        page = browser.new_page(viewport={'width': 1440, 'height': 960})
        page.add_init_script("""localStorage.setItem('pliac.local-learner', 'synthetic-performance');
            window.baselineLongTasks = [];
            if (PerformanceObserver.supportedEntryTypes.includes('longtask')) {
                new PerformanceObserver(list => window.baselineLongTasks.push(...list.getEntries().map(e => e.duration)))
                    .observe({type:'longtask', buffered:true});
            }""")
        page.on('pageerror', lambda error: report['errors'].append(str(error)))

        def measure(name, action, verify):
            start = time.perf_counter()
            action()
            verify()
            page.evaluate('() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))')
            report['samples_ms'].setdefault(name, []).append(round((time.perf_counter() - start) * 1000, 1))

        try:
            measure('initial_archive', lambda: page.goto(base + '/app/archive'),
                    lambda: expect(page.locator('.archive-entry')).to_have_count(20))
            for index in range(3):
                measure('archive_next_page', lambda: page.get_by_role('button', name='下一页档案').click(),
                        lambda: expect(page.get_by_role('status')).to_contain_text(f'第 {index + 2} / 10 页'))
                expect(page.locator('.archive-entry')).to_have_count(20)
            measure('open_saved_material', lambda: page.locator('.archive-entry').first.get_by_role('link').click(),
                    lambda: expect(page.locator('.teaching-material')).to_be_visible())
            page.get_by_role('button', name='切换教学对话').click()
            draft = page.get_by_label('当前课程的问题草稿')
            draft.fill('Keep this draft during theme changes')
            for theme in ('neutral', 'dark', 'paper'):
                measure('theme_' + theme, lambda: page.get_by_label('外观主题').select_option(theme),
                        lambda: expect(page.locator('html')).to_have_attribute('data-theme', theme))
                expect(draft).to_have_value('Keep this draft during theme changes')
            page.get_by_role('button', name='收起对话').click()
            for width in (1440, 768, 390):
                page.set_viewport_size({'width': width, 'height': 960})
                if width < 900 and page.locator('.course-nav').is_visible():
                    page.get_by_role('button', name='切换课程目录').click()
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), f'Overflow at {width}'
            page.screenshot(path=str(output / 'performance-material-mobile.png'), full_page=True)
            report['long_tasks_ms'] = page.evaluate('window.baselineLongTasks')
            report['workspace_response_bytes'] = len(page.request.get(base + f'/api/learning?course_id={DEMO_ID}&student_id=synthetic-performance').body())
            report['summary'] = {name: {'count': len(values), 'median_ms': statistics.median(values), 'max_ms': max(values)}
                                 for name, values in report['samples_ms'].items()}
            assert not report['errors'], report['errors']
        finally:
            browser.close()
    (output / 'ui-performance-baseline.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=True, indent=2))


if __name__ == '__main__':
    main()
