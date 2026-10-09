"""Course handout reader in Chromium; synthetic snapshots, no paid model calls."""
import asyncio
import json
import tempfile
from pathlib import Path
from playwright.sync_api import sync_playwright, expect
from test_ui_documents import isolated_application
from learning_agent.acceptance_course import AcceptanceCourseStore
from learnmargin.demo import demo_lesson
from learnmargin.models import Document, SourceUnit
from learnmargin.rendering import render_lesson
from learnmargin.storage import Store, atomic_json
from pliac.margin_graph import overview_map


def assert_stable_details(page, output, name):
    buttons=page.locator('#conceptList button')
    buttons.nth(1).click()
    def geometry():
        return page.evaluate('''() => ({
            boxes:['#graphScreen','.graph-panel','#graph','#conceptList','#detail'].map(selector=>{
                const r=document.querySelector(selector).getBoundingClientRect();return [r.x,r.y,r.width,r.height];
            }),height:document.documentElement.scrollHeight,scroll:window.scrollY,
            positions:marginNetwork.force.positions(),zoom:marginNetwork.graph.getZoom()
        })''')
    before=geometry()
    buttons.first.click()
    assert geometry()==before, 'Long node details changed the main layout'
    detail=page.locator('#detail')
    assert detail.evaluate('(e)=>e.scrollHeight>e.clientHeight'), 'Long text must scroll inside the detail panel'
    page.locator('#evidence summary').click()
    # Browser may scroll the outer page to bring the summary into view on mobile;
    # the expansion itself must not resize either panel or the document.
    expanded=geometry()
    assert [r[2:] for r in expanded['boxes']]==[r[2:] for r in before['boxes']]
    assert expanded['height']==before['height']
    detail.evaluate('(e)=>e.scrollTop=e.scrollHeight')
    detail.hover()
    scroll=page.evaluate('window.scrollY')
    page.mouse.wheel(0,700)
    page.wait_for_timeout(250)
    assert page.evaluate('window.scrollY')==scroll, 'Detail scrolling leaked into the page'
    buttons.nth(1).click()
    assert detail.evaluate('(e)=>e.scrollTop===0')
    buttons.first.click()
    assert detail.evaluate('(e)=>e.scrollTop===0')
    page.screenshot(path=str(output/name),full_page=True)


def main():
    with tempfile.TemporaryDirectory() as tmp:
        with isolated_application(Path(tmp)) as (base, course, _):
            store=Store(AcceptanceCourseStore(course).output_dir/'handouts')
            ident='a'*32;job_id='b'*32
            lesson=demo_lesson()
            for index,section in enumerate(lesson.sections,1): section.source_refs=[f'{ident}:{index}']
            for index,source in enumerate(lesson.sources,1): source.ref=f'{ident}:{index}'
            folder=store.directory('jobs',job_id)
            result=asyncio.run(render_lesson(lesson,folder))
            graph=overview_map(lesson)
            graph['nodes'][0]['definition']='合成的长说明，用于检查右栏的独立滚动与布局稳定。\n'*100
            graph['nodes'][0]['quote']='合成依据段落，用于检查展开后不撑高主视图。\n'*80
            atomic_json(folder/'knowledge-map.json',graph)
            doc=Document(id=ident,name='合成课程材料',kind='course_material',unit_label='节',
                units=[SourceUnit(index=i,label=s.title,text=s.explanation) for i,s in enumerate(lesson.sections,1)])
            atomic_json(folder/'materials.json',{'documents':[doc.model_dump()],'origins':{}})
            store.save_job({'id':job_id,'course_id':'ml_acceptance_demo','course_version':1,'chapter_id':'','source_view':'published',
                'status':'completed','created_at':'2026-10-09','page_count':result['page_count'],'title':lesson.title})
            with sync_playwright() as p:
                browser=p.chromium.launch();page=browser.new_page(viewport={'width':1440,'height':1000})
                errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
                page.goto(base+'/')
                expect(page.locator('[data-course-id=ml_acceptance_demo] .handout-course')).to_be_visible()
                page.locator('[data-course-id=ml_acceptance_demo] .handout-course').click()
                expect(page.locator('#graph')).to_have_attribute('data-ready','true')
                expect(page.locator('input[type=file]')).to_have_count(0)
                buttons=page.locator('#conceptList button')
                first=buttons.first.get_attribute('data-concept')
                second=buttons.nth(1).get_attribute('data-concept')
                positions=page.evaluate('marginNetwork.force.positions()')
                zoom=page.evaluate('marginNetwork.graph.getZoom()')
                buttons.first.click()
                expect(buttons.first).to_have_attribute('aria-pressed','true')
                page.wait_for_function('(id)=>marginNetwork.graph.nodeViews.get(id).style.lineWidth===3',arg=first)
                buttons.nth(1).click()
                expect(buttons.first).to_have_attribute('aria-pressed','false')
                expect(buttons.nth(1)).to_have_attribute('aria-pressed','true')
                page.wait_for_function('(id)=>marginNetwork.graph.nodeViews.get(id).style.lineWidth===1',arg=first)
                page.wait_for_function('(id)=>marginNetwork.graph.nodeViews.get(id).style.lineWidth===3',arg=second)
                assert page.evaluate('marginNetwork.force.positions()')==positions
                assert page.evaluate('marginNetwork.graph.getZoom()')==zoom
                # Real canvas click must select the corresponding button as well.
                point=page.evaluate('(id)=>marginNetwork.graph.getViewportByCanvas(marginNetwork.graph.getElementPosition(id))',first)
                box=page.locator('#graph').bounding_box()
                page.mouse.click(box['x']+point[0],box['y']+point[1])
                page.mouse.move(0,0)
                expect(buttons.first).to_have_attribute('aria-pressed','true')
                expect(buttons.nth(1)).to_have_attribute('aria-pressed','false')
                page.wait_for_function('(id)=>marginNetwork.graph.nodeViews.get(id).style.lineWidth===3 && !marginNetwork.transition',arg=first)
                assert page.evaluate('[...marginNetwork.graph.nodeViews.values()].every(n=>n.style.opacity===1)')
                output=Path(__file__).resolve().parents[1]/'outputs'/'verification'
                output.mkdir(parents=True,exist_ok=True)
                page.screenshot(path=str(output/'margin-selection-light.png'),full_page=True)
                assert_stable_details(page,output,'margin-details-long-light.png')
                page.locator('#sectionLinks a').first.click()
                expect(page.locator('#lessonFrame')).to_have_attribute('data-ready','true',timeout=30000)
                expect(page.locator('#outline button').first).to_have_attribute('aria-current','location')
                frame=page.frame_locator('#lessonFrame')
                expect(frame.locator('#pages .web-source-button').first).to_be_visible()
                frame.locator('#pages .web-source-button').first.click()
                expect(page.locator('#sourceDialog')).to_be_visible()
                expect(page.locator('#sourceContent pre')).to_contain_text('已知')
                page.locator('#closeSource').click()
                expect(page.locator('#sourceDialog')).to_be_hidden()
                page.locator('#outline button').nth(1).click()
                expect(page.locator('#outline button').nth(1)).to_have_attribute('aria-current','location')
                expect(page.locator('#readingScreen nav [aria-current]')).to_have_count(1)
                # Scrolling the actual embedded lesson keeps the outline current.
                frame.locator('#pages #section-1').evaluate('(e)=>e.scrollIntoView({block:"start"})')
                expect(page.locator('#outline button').first).to_have_attribute('aria-current','location')
                page.locator('#readingScreen nav [data-section="answers"]').click()
                expect(page.locator('#readingScreen nav [data-section="answers"]')).to_have_attribute('aria-current','location')
                frame.locator('body').evaluate('()=>window.scrollTo(0,document.documentElement.scrollHeight)')
                expect(page.locator('#readingScreen nav [data-section="review"]')).to_have_attribute('aria-current','location')
                page.locator('#outline button').nth(1).focus()
                page.keyboard.press('Enter')
                expect(page.locator('#outline button').nth(1)).to_have_attribute('aria-current','location')
                page.screenshot(path=str(output/'margin-outline-light.png'),full_page=True)
                page.locator('#mapMode').click()
                expect(buttons.first).to_have_attribute('aria-pressed','true')
                page.reload()
                expect(page.locator('#graph')).to_have_attribute('data-ready','true')
                page.set_viewport_size({'width':390,'height':844})
                page.locator('#themeButton').click()
                assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
                assert_stable_details(page,output,'margin-details-long-mobile-dark.png')
                page.locator('#readMode').click()
                expect(page.locator('#lessonFrame')).to_have_attribute('data-ready','true',timeout=30000)
                expect(page.locator('#outline button').nth(1)).to_have_attribute('aria-current','location')
                page.screenshot(path=str(output/'margin-outline-mobile-dark.png'),full_page=True)
                assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
                assert not errors,errors
                # A valid job identifier in a different course never exposes its files.
                wrong=page.request.get(base+f'/api/handouts/{job_id}/artifacts/lesson.json?course_id=')
                assert wrong.status==404,wrong.status
                assert page.request.get(base+'/margin/api/documents').status==404
                # Overflow is tested with synthetic concepts, not user course data.
                large=overview_map(lesson)
                template=large['nodes'][0]
                large['nodes'] += [{**template,'id':f'overflow-{i}','title':f'合成知识点 {i:03d}'} for i in range(120)]
                atomic_json(folder/'knowledge-map.json',large)
                page.reload()
                expect(page.locator('#graph')).to_have_attribute('data-ready','true')
                assert page.locator('#conceptList').evaluate('(e)=>e.scrollHeight>e.clientHeight && e.clientHeight<=150')
                last=page.locator('[data-concept="overflow-119"]')
                last.click()
                expect(last).to_have_attribute('aria-pressed','true')
                page.wait_for_function("marginNetwork.graph.nodeViews.get('overflow-119').style.lineWidth===3")
                page.locator('#search').fill('119')
                expect(page.locator('#conceptList button:visible')).to_have_count(1)
                expect(page.locator('#conceptCount')).to_contain_text('匹配 1 /')
                page.locator('#graph').scroll_into_view_if_needed()
                point=page.evaluate('(id)=>marginNetwork.graph.getViewportByCanvas(marginNetwork.graph.getElementPosition(id))',first)
                box=page.locator('#graph').bounding_box()
                page.mouse.click(box['x']+point[0],box['y']+point[1])
                page.mouse.move(0,0)
                expect(page.locator('#search')).to_have_value('')
                expect(buttons.first).to_have_attribute('aria-pressed','true')
                assert page.locator('#conceptList').evaluate('(e)=>e.scrollTop===0')
                last.click()
                page.locator('#search').fill('no matching concept')
                expect(page.locator('#conceptEmpty')).to_be_visible()
                page.locator('#search').fill('')
                expect(last).to_have_attribute('aria-pressed','true')
                page.locator('#conceptList').evaluate('(e)=>e.scrollTop=e.scrollHeight')
                page.screenshot(path=str(output/'margin-selection-overflow-dark.png'),full_page=True)
                assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
                assert not errors,errors
                browser.close()
                print('PASS linked graph selection, bounded/searchable concept list, outline click/scroll/restore, source return, mobile/dark, course isolation')

if __name__=='__main__': main()
