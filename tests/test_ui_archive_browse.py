"""Archive search/paging/back navigation against a real isolated API."""
import tempfile
from pathlib import Path
from playwright.sync_api import expect, sync_playwright
from test_ui_documents import isolated_application
from learning_agent.acceptance_course import AcceptanceCourseStore, DEMO_ID
from pliac.workspace import empty_workspace
from test_personal_export import sample_material


def main():
    with tempfile.TemporaryDirectory() as folder, isolated_application(Path(folder)) as (base, root, _), sync_playwright() as p:
        store = AcceptanceCourseStore(root)
        learner = store._read_learner('synthetic-archive')
        learner['workspace'] = empty_workspace()
        learner['workspace']['stage_reports'] = [dict(id=f'report-{i:02d}', request_id=f'request-{i}',
            title=f'合成阶段成果 {i:02d}', created_at='2026-10-10T00:00:00Z', course_version=1,
            goals='Synthetic scope', scope='Synthetic engineering fixture', limitations='Not a real learner result',
            nodes={}, counts={}, diagnoses=[], evidence=[], notes=[], material_ids=[], learner_version=0) for i in range(25)]
        material = sample_material()
        material['proposal']['target_node_id'] = store.load_graph()['nodes'][0]['id']
        learner['workspace']['tutor_turns'] = [material]
        learner['workspace']['stage_reports'][20]['material_ids'] = [material['request_id']]
        store._commit(learner)
        browser = p.chromium.launch()
        page = browser.new_page(viewport={'width': 390, 'height': 844})
        page.add_init_script("localStorage.setItem('pliac.local-learner', 'synthetic-archive')")
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.goto(base + '/app/archive')
        expect(page.locator('.archive-entry')).to_have_count(20)
        page.get_by_role('button', name='下一页档案').click()
        expect(page.locator('.archive-entry')).to_have_count(6)
        expect(page.get_by_role('status')).to_be_focused()
        page.reload()
        expect(page.locator('.archive-entry')).to_have_count(6)
        page.locator('.archive-entry').filter(has_text='合成阶段成果 20').get_by_role('link').click()
        expect(page.locator('.stage-report h1')).to_have_text('合成阶段成果 20')
        page.route('**/api/tutor/export/pdf?*', lambda route: route.fulfill(
            status=429, content_type='application/json', body='{"detail":"Synthetic export busy; retry later"}'))
        page.get_by_role('button', name='导出 PDF', exact=True).click()
        expect(page.get_by_role('alert')).to_contain_text('Synthetic export busy')
        expect(page.get_by_role('button', name='导出 PDF', exact=True)).to_be_enabled()
        expect(page.locator('.stage-report h1')).to_have_text('合成阶段成果 20')
        page.unroute('**/api/tutor/export/pdf?*')
        pending = []
        page.route('**/api/tutor/export/pdf?*', lambda route: pending.append(route))
        page.get_by_role('button', name='导出 PDF', exact=True).click()
        expect(page.get_by_role('button', name='取消下载等待')).to_be_visible()
        page.get_by_role('button', name='取消下载等待').click()
        expect(page.get_by_role('button', name='导出 PDF', exact=True)).to_be_enabled()
        expect(page.get_by_role('alert')).to_contain_text('学习成果仍保留')
        for route in pending:
            route.abort()
        page.unroute('**/api/tutor/export/pdf?*')
        with page.expect_download() as download:
            page.get_by_role('button', name='导出 PDF', exact=True).click()
        assert Path(download.value.path()).read_bytes().startswith(b'%PDF')
        expect(page.get_by_role('alert')).to_have_count(0)
        page.get_by_role('button', name='查看本阶段教材汇编').click()
        book = page.locator('.personal-textbook')
        expect(book.get_by_role('heading', name='1. 泛化误差与数据划分', exact=True)).to_be_visible()
        expect(book.get_by_role('link', name='泛化误差与数据划分', exact=True)).to_have_count(1)
        with page.expect_download() as textbook_download:
            book.get_by_role('button', name='导出 PDF', exact=True).click()
        assert Path(textbook_download.value.path()).read_bytes().startswith(b'%PDF')
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        page.get_by_role('button', name='收起教材汇编').click()
        page.go_back()
        expect(page.locator('.archive-entry')).to_have_count(6)
        page.get_by_label('搜索档案').fill('成果 07')
        expect(page.locator('.archive-entry')).to_have_count(1)
        expect(page.get_by_role('status')).to_contain_text('第 1 / 1 页')
        page.reload()
        expect(page.get_by_label('搜索档案')).to_have_value('成果 07')
        page.get_by_label('查看内容').select_option('note')
        expect(page.get_by_text('没有符合条件的记录。', exact=False)).to_be_visible()
        page.get_by_role('button', name='清除筛选').click()
        expect(page.locator('.archive-entry')).to_have_count(20)
        page.get_by_label('筛选课程').select_option(DEMO_ID)
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        page.get_by_label('搜索档案').fill('成果 07')
        expect(page.locator('.archive-entry')).to_have_count(1)
        output = Path(__file__).resolve().parents[1] / 'outputs/verification/archive-browse-mobile.png'
        page.screenshot(path=str(output), full_page=True)
        assert not errors, errors
        browser.close()
    print('PASS real archive API: paging, search, filter, reload, report deep link/back, mobile width')


if __name__ == '__main__':
    main()
