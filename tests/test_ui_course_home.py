"""Course overview -> reading -> lab -> same lesson, in an isolated app."""
import json
import tempfile
from pathlib import Path

from playwright.sync_api import expect, sync_playwright
from test_ui_documents import isolated_application

OUTPUT = Path(__file__).resolve().parents[1] / 'outputs/verification'


def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    report = {'synthetic_only': True, 'checks': [], 'page_errors': []}

    def passed(message):
        report['checks'].append(message)
        print('PASS', message, flush=True)

    try:
        with tempfile.TemporaryDirectory() as tmp:
            with isolated_application(Path(tmp)) as (base, _, _), sync_playwright() as p:
                browser = p.chromium.launch()
                page = browser.new_page(viewport={'width': 1440, 'height': 1000})
                page.on('pageerror', lambda e: report['page_errors'].append(str(e)))
                page.add_init_script("""Object.defineProperty(window,'NetworkView',{
                  get(){return this.__View},set(View){this.__View=class extends View{
                    constructor(...args){super(...args);window.__network=this;}
                  }}});""")
                page.goto(base + '/')
                expect(page.locator('#courseOverview')).to_be_visible()
                expect(page.locator('#courseMap')).to_have_attribute('data-ready', 'true')
                expect(page.locator('#readingWorkspace')).to_be_hidden()
                student = page.locator('#studentId').input_value()
                assert student.startswith('learner-')
                def state():
                    return page.request.get(base + '/api/learning', params={
                        'course_id': 'ml_acceptance_demo', 'student_id': student}).json()
                initial = state()
                assert len(page.evaluate('__network.data.nodes')) == 30
                assert len(initial['course']['nodes']) == 10
                assert not set(page.evaluate('__network.data.nodes.map(n=>n.id)')) & {n['id'] for n in initial['course']['nodes']}
                assert page.evaluate(r'__network.data.nodes.every(n=>n.data.kind==="concept" && !/^\d/.test(n.data.title))')
                assert page.evaluate('__network.data.edges.some(e=>e.source==="concept_train" && e.target==="concept_tree" && e.data.label==="用于拟合")')
                assert page.evaluate('__network.data.nodes.filter(n=>["训练集","验证集","测试集"].includes(n.data.title)).length === 3')
                at=page.evaluate('__network.graph.getViewportByCanvas(__network.graph.getElementPosition("concept_train"))')
                page.locator('#courseMap').click(position={'x':at[0],'y':at[1]})
                expect(page.locator('#selectedTitle')).to_have_text('训练集')
                expect(page.locator('[data-lesson]')).to_have_count(3)
                page.locator('[data-node="underfit"]').click()
                page.locator('[data-relation="concept_relation_28"]').click()
                expect(page.locator('#relationDetail')).to_contain_text('表达能力不足')
                expect(page.locator('#relationDetail a')).to_have_count(1)
                before_positions = page.evaluate('__network.force.positions()')
                page.locator('#mapColorMode').select_option('active')
                page.wait_for_function('__network.data.nodes.every(n=>n.style.fill === "#c4c8cc") && !__network.busy')
                assert before_positions == page.evaluate('__network.force.positions()')
                page.locator('#mapColorMode').select_option('family')
                assert all(v['status'] == 'unknown' for v in initial['learner']['states'].values())
                page.locator('#overviewChapter').select_option('data')
                allowed={n['id'] for n in initial['course']['nodes'] if n['chapter_id']=='data'}
                expected=sum(bool(allowed & set(n['lesson_ids'])) for n in initial['concept_map']['nodes'])
                page.wait_for_function(f'__network.data.nodes.length === {expected} && !__network.busy')
                assert page.evaluate('__network.data.edges.every(e=>__network.data.nodes.some(n=>n.id===e.source)&&__network.data.nodes.some(n=>n.id===e.target))')
                page.locator('#overviewChapter').select_option('')
                page.wait_for_function('__network.data.nodes.length === 30 && !__network.busy')
                page.locator('[data-node="partition"]').click()
                expect(page.locator('#selectedTitle')).to_contain_text('划分')
                assert state()['current_lesson'] is None
                page.screenshot(path=str(OUTPUT / 'course-home-desktop.png'), full_page=True)
                passed('Root opens real course graph; chapter selection and browsing do not create lessons')
                page.locator('#goals').fill('理解数据划分，并能用实验说明选择模型的依据。')
                page.locator('#onboardForm button[type=submit]').click()
                page.locator('#nextLesson').click()
                expect(page.locator('#readingWorkspace')).to_be_visible()
                current = state()['current_lesson']['id']
                page.locator('#discussionText').fill('可以举一个例子吗？')
                page.locator('#discussionForm button').click()
                expect(page.locator('#discussionHistory')).to_contain_text('课程讲解')
                assert state()['current_lesson']['discussions'][0]['response_origin'] == 'course_material'
                assert state()['learner']['states']['sample']['status'] != 'mastered'
                assert not state()['learner']['diagnoses']
                page.locator('#answerText').fill('我的实验前思考')
                page.locator('#lessonLabLink').click()
                expect(page.locator('#studentId')).to_have_value(student)
                expect(page.locator('#setup')).to_be_visible()
                page.locator('#goal').fill('用一次实验检验样本与标签的区分。')
                page.locator('#startForm button').click()
                expect(page.locator('#progress')).to_have_text('0 / 5')
                page.locator('#learnLink').click()
                expect(page.locator('#readingWorkspace')).to_be_visible()
                expect(page.locator('#labReturnSummary')).to_contain_text('0 / 5')
                expect(page.locator('#answerText')).to_have_value('我的实验前思考')
                assert state()['current_lesson']['id'] == current
                expect(page.locator('#discussionHistory')).to_contain_text('举一个例子')
                page.screenshot(path=str(OUTPUT / 'course-reading-desktop.png'), full_page=True)
                passed('Question provenance, draft, learner identity and lesson survive contextual lab round trip')
                page.locator('[name=answerChoice][value="A"]').check()
                page.locator('#answerForm button[type=submit]').click()
                expect(page.locator('#responses')).to_contain_text('需要再想一想')
                # A still-unreviewed question keeps the aggregate state uncertain,
                # even though this separate objective answer was wrong.
                expect(page.locator('[data-node="sample"] .state-dot')).to_have_class('state-dot uncertain')
                assert state()['learner']['diagnoses'][-1]['status'] == 'needs_review'
                page.locator('#overviewTab').click()
                expect(page.locator('#selectedReason')).to_contain_text('小节学习状态：待核验')
                page.locator('#selectedEvidence summary').click()
                expect(page.locator('#selectedEvidenceBody')).to_contain_text('我的实验前思考')
                page.locator('#continueLesson').click()
                assert state()['current_lesson']['id'] == current
                page.reload()
                expect(page.locator('#readingWorkspace')).to_be_visible()
                assert state()['current_lesson']['id'] == current
                passed('Overview status traces actual evidence; resume and reload retain the active lesson')
                page.locator('[data-node="partition"]').click()
                expect(page.locator('#lessonContent h3').first).to_contain_text('划分')
                later = state()['current_lesson']['id']
                page.reload()
                expect(page.locator('#lessonContent h3').first).to_contain_text('划分')
                assert state()['current_lesson']['id'] == later
                page.locator('#overviewTab').click()
                page.set_viewport_size({'width': 390, 'height': 844})
                page.locator('#themeButton').click()
                page.wait_for_function('document.getAnimations().every(a=>a.playState!=="running")')
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                page.screenshot(path=str(OUTPUT / 'course-home-mobile-dark.png'), full_page=True)
                page.locator('#studyTab').click()
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                page.screenshot(path=str(OUTPUT / 'course-reading-mobile-dark.png'), full_page=True)
                page.goto(base + '/courses')
                expect(page.locator('#newCourseButton')).to_be_hidden()
                expect(page.locator('.edit-course')).to_have_count(0)
                page.locator('#manageLink').click()
                expect(page.locator('#newCourseButton')).to_be_visible()
                passed('Mobile light/dark layouts fit; course authoring has its own management entry')
                page.set_viewport_size({'width':1440,'height':1000})
                page.goto(base + '/author')
                page.wait_for_function('window.__network?.data?.nodes.some(n=>n.id==="course_root") && !__network.busy')
                def centered_root():
                    return page.evaluate('''() => {
                        const n=__network,p=n.graph.getViewportByCanvas(n.graph.getElementPosition('course_root'));
                        return Math.hypot(p[0]-n.element.clientWidth/2,p[1]-n.element.clientHeight/2)<2;
                    }''')
                assert centered_root()
                point = page.evaluate('__network.force.points.get("course_root")')
                assert abs(point['x']) < 1 and abs(point['y']) < 1
                page.locator('#stabilizeButton').click()
                page.wait_for_function('!__network.arranging && !__network.busy')
                assert centered_root()
                page.screenshot(path=str(OUTPUT / 'course-graph-centered-root.png'))
                passed('Original full graph anchors its course root at the center on initial layout and explicit rearrange')
                assert not report['page_errors'], report['page_errors']
                browser.close()
    finally:
        (OUTPUT / 'course-home-report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()
