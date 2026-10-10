"""Synthetic saved material and explicitly mocked source text for dialog UX."""
import json
import tempfile
from pathlib import Path

from playwright.sync_api import sync_playwright, expect
from test_ui_documents import isolated_application
from learning_agent.acceptance_course import AcceptanceCourseStore, DEMO_ID
from pliac.workspace import empty_workspace


def main():
    with tempfile.TemporaryDirectory(prefix='pliac-source-preview-') as directory, isolated_application(Path(directory)) as (base, root, _), sync_playwright() as p:
        store = AcceptanceCourseStore(root)
        graph = store.load_graph()
        student = 'synthetic-preview'
        learner = store._read_learner(student)
        learner['workspace'] = empty_workspace()
        url = '/api/documents/' + 'a' * 32 + '/source'
        sources = [{'id': f'source-{page}', 'title': '合成资料', 'origin': 'uploaded_document', 'page': page, 'url': url + f'#page={page}'} for page in (2, 4)]
        learner['workspace']['tutor_turns'] = [{'request_id': 'saved-preview', 'course_version': graph['version'], 'node_id': graph['nodes'][0]['id'],
            'created_at': '2026-10-10T00:00:00Z', 'source_catalog': sources, 'proposal': {'response': '合成讲解', 'target_node_id': graph['nodes'][0]['id'], 'rationale': '合成依据', 'question': '',
            'blocks': [{'heading': '合成原文预览测试', 'text': '只用于界面验证。', 'citations': [{'source_id': 'source-2', 'quote': '保存的引文'}]}]}}]
        store._commit(learner)
        browser = p.chromium.launch()
        page = browser.new_page(viewport={'width': 1360, 'height': 960})
        page.add_init_script("localStorage.setItem('pliac.local-learner', " + json.dumps(student) + ")")
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        def preview(route):
            from urllib.parse import urlparse, parse_qs
            selected = parse_qs(urlparse(route.request.url).query)['source_id'][0]
            route.fulfill(json={'title': '合成资料', 'page': 2 if selected == 'source-2' else 4,
                'text': '<script>window.untrustedExecuted=true</script>\n合成原文段落。\n' * 12,
                'changed': selected == 'source-4', 'notice': '合成接口：文本预览不是 PDF 原版式。'})
        page.route('**/api/tutor/source-preview?*', preview)
        bookmark = {'revision': 0, 'position': None}
        def source_position(route):
            if route.request.method == 'POST':
                body = route.request.post_data_json
                bookmark.update(revision=bookmark['revision'] + 1, position={key: body[key] for key in ('source_id', 'mode', 'zoom')})
                bookmark['position']['page'] = 4 if body['source_id'] == 'source-4' else 2
            route.fulfill(json=bookmark)
        page.route('**/api/tutor/source-position?*', source_position)
        import fitz
        with fitz.open() as pdf:
            sheet = pdf.new_page(width=500, height=350)
            sheet.insert_text((35, 45), 'Synthetic course source - page 4', fontsize=18)
            sheet.draw_rect(fitz.Rect(35, 70, 450, 270))
            sheet.insert_text((55, 110), 'Original diagram and layout remain visible.', fontsize=14)
            picture = sheet.get_pixmap(matrix=fitz.Matrix(2, 2)).tobytes('png')
        page.route('**/api/tutor/source-page-image?*', lambda route: route.fulfill(body=picture, content_type='image/png'))
        page.goto(base + f'/app/courses/{DEMO_ID}?material=saved-preview')
        page.locator('.teaching-material').get_by_text('来源与依据', exact=True).click()
        opener = page.get_by_role('button', name='在工作台预览原文')
        opener.scroll_into_view_if_needed()
        previous = page.locator('.lesson-pane').evaluate('(element)=>element.scrollTop')
        opener.click()
        dialog = page.get_by_role('dialog', name='课程原文预览')
        expect(dialog).to_be_visible()
        expect(dialog).to_contain_text('合成原文段落')
        assert page.evaluate('window.untrustedExecuted') is None
        dialog.get_by_label('本次讲解关联的原文页').select_option('source-4')
        expect(dialog).to_contain_text('原文已与生成讲解时不同')
        dialog.get_by_role('button', name='PDF 原版式').click()
        expect(dialog.get_by_role('img', name='课程原文第 4 页')).to_be_visible()
        page.wait_for_function("document.querySelector('.source-preview img')?.naturalWidth > 0")
        page.screenshot(path=str(Path(__file__).resolve().parents[1] / 'outputs/verification/source-page-layout.png'), full_page=True)
        dialog.get_by_text('跨次原文续读', exact=True).click()
        dialog.get_by_role('button', name='保存当前原文页').click()
        expect(dialog).to_contain_text('引用页与显示模式已保存到学习档案')
        dialog.get_by_role('button', name='文字模式', exact=True).click()
        expect(dialog).to_contain_text('原文已与生成讲解时不同')
        page.keyboard.press('Escape')
        expect(dialog).to_have_count(0)
        expect(opener).to_be_focused()
        assert abs(page.locator('.lesson-pane').evaluate('(element)=>element.scrollTop') - previous) < 2
        page.set_viewport_size({'width': 390, 'height': 844})
        if page.locator('.course-nav').is_visible():
            page.get_by_role('button', name='切换课程目录').click()
        opener.click()
        expect(dialog).to_be_visible()
        dialog.get_by_text('跨次原文续读', exact=True).click()
        dialog.get_by_role('button', name='恢复原文续读').click()
        expect(dialog.get_by_label('本次讲解关联的原文页')).to_have_value('source-4')
        expect(dialog.get_by_role('button', name='PDF 原版式')).to_have_attribute('aria-pressed', 'true')
        box = dialog.bounding_box()
        assert box['x'] >= 0 and box['x'] + box['width'] <= 391
        dialog.get_by_role('button', name='PDF 原版式').click()
        expect(dialog.get_by_role('img')).to_be_visible()
        dialog.get_by_label('原版式大小').select_option('200')
        region = dialog.get_by_label('原版式阅读区域')
        assert region.evaluate('(el)=>el.scrollWidth > el.clientWidth')
        assert dialog.evaluate('(el)=>el.scrollWidth <= el.clientWidth + 1')
        output = Path(__file__).resolve().parents[1] / 'outputs/verification/source-preview-mobile.png'
        page.screenshot(path=str(output), full_page=True)
        dialog.get_by_role('button', name='关闭原文预览').click()
        assert not errors, errors
        browser.close()
    print('PASS: source dialog, mapped page switch, revision warning, escaped source text, focus/scroll return and mobile width; mocked source API')


if __name__ == '__main__':
    main()
