"""Course creation and graph editing in temporary stores, using real browser actions."""
from pathlib import Path
import json
import re
import tempfile
import traceback
from urllib.parse import parse_qs, urlparse

import httpx
from playwright.sync_api import sync_playwright, expect

from test_ui_documents import isolated_application, SOURCE

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / 'outputs/verification'


def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    report = {'checks': [], 'errors': [], 'temporary_stores': True}
    try:
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            material = directory / 'knowledge.md'
            material.write_text(SOURCE, encoding='utf-8')
            with isolated_application(directory) as (base, default_store, documents):
                original = default_store.load_graph('draft')
                with httpx.Client(base_url=base, timeout=15) as client, sync_playwright() as p:
                    browser = p.chromium.launch()
                    page = browser.new_page(viewport={'width':1440, 'height':900})
                    page.on('pageerror', lambda error: report['errors'].append(str(error)))
                    page.add_init_script("""Object.defineProperty(window,'NetworkView',{
                      get(){return this.__View},set(View){this.__View=class extends View{
                        constructor(...args){super(...args);window.__network=this;}
                      }}});""")

                    def draft(ident):
                        response = client.get('/api/course-graph', params={'course_id':ident, 'view':'draft'})
                        response.raise_for_status()
                        return response.json()['graph']

                    def create(title, method):
                        page.goto(base + '/courses')
                        page.locator('#newCourseButton').click()
                        page.locator('#newCourseTitle').fill(title)
                        page.locator(f'input[name="createMethod"][value="{method}"]').check()
                        page.locator('#createCourseSubmit').click()
                        page.wait_for_url(re.compile(r'.*course_id=.+'))
                        return parse_qs(urlparse(page.url).query)['course_id'][0]

                    def theme(dark):
                        if page.evaluate("document.body.classList.contains('network-dark')") != dark:
                            page.locator('#themeButton').click()
                        page.wait_for_timeout(350)

                    page.goto(base + '/courses')
                    expect(page.locator('[data-course-id]')).to_have_count(1)
                    assert not default_store.output_dir.exists()
                    report['checks'].append('Course list exposes the existing course without writing data')

                    course_a = create('生物基础 · 手工图谱', 'manual')
                    expect(page.locator('#emptyCourse')).to_be_visible()
                    assert not draft(course_a)['nodes']
                    expect(page.locator('#studentView')).to_be_hidden()
                    empty_publish = client.post('/api/course-graph/publish', params={'course_id':course_a},
                                                json={'expected_version':1, 'published_by':'synthetic-check', 'note':'empty draft check'})
                    assert empty_publish.status_code in (400, 409)
                    report['checks'].append('Manual creation opens a real empty course and cannot publish empty content')

                    page.locator('#emptyAddNode').click()
                    expect(page.locator('#nodeEditor')).to_be_visible()
                    assert page.locator('#editId').input_value(), 'A new point should have a generated ID'
                    page.locator('#editTitle').fill('光合作用')
                    page.locator('#editDescription').fill('植物通过光能合成有机物的过程。')
                    page.locator('#nodeEditor button[value="draft"]').click()
                    page.wait_for_function('window.__network?.data?.nodes.length >= 3 && !window.__network.busy')
                    first = draft(course_a)['nodes'][0]['id']
                    page.locator('#manager .close-dialog').click()
                    expect(page.locator('#emptyCourse')).to_be_hidden()
                    page.locator('#addNodeButton').click()
                    page.locator('#editTitle').fill('叶绿体')
                    page.locator('#editDescription').fill('植物细胞中完成光合作用的结构。')
                    page.locator('#nodeEditor button[value="draft"]').click()
                    expect(page.locator('#editPick option')).to_have_count(3)
                    second = next(n['id'] for n in draft(course_a)['nodes'] if n['id'] != first)
                    page.locator('#manager .close-dialog').click()
                    page.locator('#addEdgeButton').click()
                    page.locator('#edgeSource').select_option(first)
                    page.locator('#edgeTarget').select_option(second)
                    page.locator('#edgeType').select_option('related')
                    page.locator('#edgeReason').fill('叶绿体是光合作用的主要场所。')
                    page.locator('#edgeEditor button[value="draft"]').click()
                    page.wait_for_function("__network.data.edges.some(e=>e.data.type==='related') && !__network.busy")
                    page.locator('#manager .close-dialog').click()
                    saved_a = draft(course_a)
                    assert len(saved_a['nodes']) == 2 and len(saved_a['edges']) == 1
                    assert all(n['review_status'] == 'draft' for n in saved_a['nodes'])
                    page.reload()
                    page.wait_for_function('window.__network?.data?.nodes.length >= 4 && !window.__network.busy')
                    report['checks'].append('Two knowledge points and their relation can be created through visible UI and survive reload')

                    for dark in (False, True, False):
                        theme(dark)
                        labels = page.evaluate("""() => __network.graph.getEdgeData().filter(e=>e.style.labelText).map(e=>{
                          const label=__network.graph.context.element.getElement(e.id).getShape('label');
                          const background=label.getShape('background');
                          return {text:label.getShape('text').attributes.text,background:!!background,fill:background?.attributes.fill};
                        })""")
                        assert labels and all(label['text'] for label in labels)
                        assert all(label['background'] != dark for label in labels), labels
                        if not dark:
                            assert all(label['fill'] == '#fcfbf9' for label in labels), labels
                    theme(True)
                    page.screenshot(path=str(OUTPUT / 'course-manual-dark.png'))
                    report['checks'].append('Rendered relation labels remove their background in dark mode and restore it on returning to light')

                    page.locator('#coursesLink').click()
                    expect(page.locator(f'[data-course-id="{course_a}"]')).to_be_visible()
                    page.reload()
                    expect(page.locator(f'[data-course-id="{course_a}"]')).to_contain_text('生物基础')
                    course_b = create('资料建图 · 独立课程', 'book')
                    assert course_b != course_a
                    expect(page.locator('#libraryPanel')).to_be_visible()
                    page.locator('#fileInput').set_input_files(material)
                    page.wait_for_function('window.__network?.data?.nodes.length > 2 && !window.__network.busy', timeout=60000)
                    page.locator('#importButton').click()
                    expect(page.locator('#targetCourse')).to_have_value(course_b)
                    page.locator('#confirmImport').click()
                    expect(page.locator('#importDialog')).not_to_be_visible()
                    assert draft(course_b)['nodes']
                    assert draft(course_a) == saved_a
                    assert default_store.load_graph('draft') == original
                    report['checks'].append('Book extraction imports into the selected new course and preserves both another course and the original seed')

                    # Returning to the library must retain a bordered navigation control in both themes.
                    course_link = page.locator('.toolbar a[href="/courses"]')
                    for dark in (True, False):
                        theme(dark)
                        assert course_link.evaluate("e=>parseFloat(getComputedStyle(e).borderTopWidth)") >= 1
                    course_link.click()
                    expect(page.locator('[data-course-id]')).to_have_count(3)
                    page.set_viewport_size({'width':390, 'height':844})
                    theme(True)
                    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                    page.screenshot(path=str(OUTPUT / 'courses-dark-mobile.png'))
                    page.set_viewport_size({'width':1440, 'height':900})
                    page.screenshot(path=str(OUTPUT / 'courses-desktop.png'))
                    report['checks'].append('Course cards persist, navigation has a border in both themes, and the mobile course list remains usable')
                    assert not report['errors'], report['errors']
                    browser.close()
        report['passed'] = True
    except Exception:
        report['failure'] = traceback.format_exc()
        raise
    finally:
        (OUTPUT / 'courses-ui-report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
