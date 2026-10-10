"""Real isolated graph API; relation direction and read-only UI semantics."""
import tempfile
from pathlib import Path

from playwright.sync_api import expect, sync_playwright
from test_ui_documents import isolated_application
from test_learning_workspace import platform_fixture, publish_synthetic


def main():
    with tempfile.TemporaryDirectory(prefix='pliac-relations-') as folder, isolated_application(Path(folder)) as (base, store, _), sync_playwright() as p:
        graph = platform_fixture()
        graph['edges'].extend([{'id': 'related_bd', 'source': 'b', 'target': 'd', 'type': 'related', 'reason': 'synthetic related', 'source_ids': ['book'], 'review_status': 'draft'},
                              {'id': 'contains_ab', 'source': 'a', 'target': 'b', 'type': 'contains', 'reason': 'synthetic containment', 'source_ids': ['book'], 'review_status': 'draft'}])
        publish_synthetic(store, graph)
        browser = p.chromium.launch()
        page = browser.new_page(viewport={'width': 1360, 'height': 960})
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.goto(base + '/app/courses/ml_classification?node=a')
        expect(page.locator('.lesson h1')).to_have_text('a')
        student = page.evaluate("localStorage.getItem('pliac.local-learner')")
        before = store._read_learner(student)
        opener = page.get_by_role('button', name='查看知识关系')
        opener.click()
        dialog = page.get_by_role('dialog', name='当前知识关系')
        expect(dialog.get_by_role('region', name='理解此点所需的先修')).to_have_count(0)
        expect(dialog.get_by_role('region', name='以此点为先修的知识').get_by_role('button', name='c', exact=True)).to_be_visible()
        expect(dialog.get_by_role('region', name='容易混淆的知识').get_by_role('button', name='d', exact=True)).to_be_visible()
        expect(dialog.get_by_role('region', name='包含的知识').get_by_role('button', name='b', exact=True)).to_be_visible()
        dialog.get_by_label('预览知识点').select_option('c')
        expect(dialog.get_by_role('region', name='理解此点所需的先修').get_by_role('button')).to_have_count(2)
        expect(page.locator('.lesson h1')).to_have_text('a')
        dialog.get_by_label('预览知识点').select_option('d')
        expect(dialog.get_by_role('region', name='相关知识').get_by_role('button', name='b', exact=True)).to_be_visible()
        page.keyboard.press('Escape')
        expect(opener).to_be_focused()
        expect(page.locator('.lesson h1')).to_have_text('a')
        opener.click()
        dialog.get_by_label('预览知识点').select_option('c')
        dialog.get_by_role('button', name='在工作台查看此知识点').click()
        expect(page.locator('.lesson h1')).to_have_text('c')
        assert store._read_learner(student) == before
        page.set_viewport_size({'width': 390, 'height': 844})
        opener.click()
        expect(dialog).to_be_visible()
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        output = Path(__file__).resolve().parents[1] / 'outputs/verification/knowledge-relations-mobile.png'
        page.screenshot(path=str(output), full_page=True)
        assert not errors, errors
        browser.close()
    print('PASS: prerequisite direction, symmetric relation categories, containment, read-only preview, explicit browse, focus return, mobile; real isolated graph API')


if __name__ == '__main__':
    main()
