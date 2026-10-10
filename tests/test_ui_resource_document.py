"""Protected PDF reading with a real synthetic file and actual bookmark API."""
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import fitz
from playwright.sync_api import expect, sync_playwright
from test_resource_document import prepare_pdf
from test_ui_access import enter_created
from test_ui_documents import isolated_application, OUTPUT


def main():
    with tempfile.TemporaryDirectory(prefix='pliac-pdf-reader-') as folder, patch.dict(os.environ, {'PLIAC_REQUIRE_AUTH': '1'}):
        with isolated_application(Path(folder)) as (base, store, documents), sync_playwright() as p:
            ident, graph = prepare_pdf(store, documents)
            browser = p.chromium.launch()
            context = browser.new_context(viewport={'width': 390, 'height': 844})
            page = context.new_page()
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.goto(base + '/app/courses/' + graph['id'])
            page.get_by_role('button', name='创建匿名学习档案').click()
            enter_created(page)
            opener = page.get_by_role('button', name='选择学习材料', exact=True)
            opener.click()
            page.get_by_role('button', name='在工作台阅读原文件（PDF）').click()
            reader = page.get_by_role('region', name='课程 PDF 阅读器')
            expect(reader.get_by_label('原文件页码')).to_have_value('2')
            image = reader.get_by_role('img', name='原文件第 2 页')
            expect(image).to_be_visible()
            page.wait_for_function("document.querySelector('[aria-label=\"PDF 页面阅读区域\"] img')?.naturalWidth > 0")
            reader.get_by_role('button', name='下一页', exact=True).click()
            expect(reader.get_by_label('原文件页码')).to_have_value('3')
            expect(reader.get_by_role('button', name='下一页', exact=True)).to_be_disabled()
            reader.get_by_label('显示模式').select_option('text')
            expect(reader.locator('.source-text')).to_contain_text('Synthetic source page 3')
            expect(reader.locator('.source-text')).to_contain_text('<script>not executable</script>')
            assert reader.locator('.source-text script').count() == 0
            reader.get_by_role('button', name='保存文件阅读位置').click()
            expect(reader).to_contain_text('第 3 页与显示模式已保存。')
            student = page.evaluate("localStorage.getItem('pliac.local-learner')")
            assert not store._read_learner(student)['evidence']
            page.get_by_role('button', name='关闭材料选择').click()
            expect(opener).to_be_focused()
            page.goto(base + '/app/')
            page.get_by_role('region', name='继续学习').get_by_role('link').filter(has_text='合成 PDF 课件').click()
            expect(page.get_by_role('dialog', name='选择学习材料')).to_be_visible()
            page.get_by_role('button', name='在工作台阅读原文件（PDF）').click()
            expect(reader.get_by_label('原文件页码')).to_have_value('3')
            expect(reader.get_by_label('显示模式')).to_have_value('text')
            expect(reader.locator('.source-text')).to_contain_text('Synthetic source page 3')
            reader.get_by_label('显示模式').select_option('page')
            reader.get_by_label('页面大小').select_option('200')
            expect(reader.get_by_role('img')).to_be_visible()
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            OUTPUT.mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(OUTPUT / 'resource-document-mobile.png'), full_page=True)
            with fitz.open(documents.source(ident)) as pdf:
                pdf[0].insert_text((40, 160), 'Updated source')
                pdf.saveIncr()
            reader.get_by_role('button', name='上一页', exact=True).click()
            expect(reader.get_by_role('alert')).to_contain_text('课程资源或原文件已更新')
            reader.get_by_role('button', name='重新读取文件与位置').click()
            expect(reader).to_contain_text('旧阅读位置未套用')
            expect(reader.get_by_label('原文件页码')).to_have_value('2')
            expect(reader.get_by_role('img', name='原文件第 2 页')).to_be_visible()
            reader.get_by_role('button', name='返回材料列表').click()
            expect(reader).to_have_count(0)
            expect(page.get_by_role('button', name='在工作台阅读原文件（PDF）')).to_be_focused()
            page.keyboard.press('Escape')
            expect(opener).to_be_focused()
            assert 'resource=' not in page.url
            assert not errors, errors
            browser.close()
    print('PASS protected PDF full-page navigation, image decode, text escaping, bookmark/reload, changed file guard, mobile width/focus; synthetic file only')


if __name__ == '__main__':
    main()
