"""Material chooser UX; synthetic resource response and real workspace."""
import tempfile
from pathlib import Path
from playwright.sync_api import expect, sync_playwright
from test_ui_documents import isolated_application


def main():
    with tempfile.TemporaryDirectory() as folder, isolated_application(Path(folder)) as (base, _, _), sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={'width': 390, 'height': 844})
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        rows = [dict(id='video', title='合成视频材料', format='video', url='https://example.test/video', applicable_segment='第 2 节', for_current=True, reason='关联当前知识点', missing_prerequisites=[{'id': 'a', 'title': '合成基础'}]),
                dict(id='unsafe', title='不安全链接样本', format='lesson', url='javascript:alert(1)', applicable_segment='', for_current=True, reason='安全渲染测试', missing_prerequisites=[])]
        page.route('**/api/tutor/resources?*', lambda route: route.fulfill(json={'course_version': 1, 'resources': rows, 'notice': '明确模拟的资源响应'}))
        page.goto(base + '/app/courses/ml_acceptance_demo')
        opener = page.get_by_role('button', name='选择学习材料', exact=True)
        opener.click()
        dialog = page.get_by_role('dialog', name='选择学习材料')
        expect(dialog.get_by_text('前置仍待核验：合成基础。可以先查看并向智能体求助。')).to_be_visible()
        expect(dialog.locator('a')).to_have_count(1)
        expect(dialog.locator('a')).to_have_attribute('rel', 'noopener noreferrer')
        expect(dialog.get_by_text('该资源没有可安全打开的链接。')).to_be_visible()
        dialog.get_by_label('材料形式').select_option('video')
        expect(dialog.get_by_role('heading', name='不安全链接样本')).to_have_count(0)
        expect(dialog.get_by_role('heading', name='合成视频材料')).to_be_visible()
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        page.keyboard.press('Escape')
        expect(dialog).to_have_count(0)
        expect(opener).to_be_focused()
        assert not errors, errors
        browser.close()
    print('PASS resource chooser: format filter, prerequisite guidance, unsafe URL blocked, focus return/mobile; mocked resources')


if __name__ == '__main__':
    main()
