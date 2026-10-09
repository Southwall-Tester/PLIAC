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
            atomic_json(folder/'knowledge-map.json',overview_map(lesson))
            doc=Document(id=ident,name='合成课程材料',kind='course_material',unit_label='节',
                units=[SourceUnit(index=i,label=s.title,text=s.explanation) for i,s in enumerate(lesson.sections,1)])
            atomic_json(folder/'materials.json',{'documents':[doc.model_dump()],'origins':{}})
            store.save_job({'id':job_id,'course_id':'ml_acceptance_demo','course_version':1,'chapter_id':'','source_view':'published',
                'status':'completed','created_at':'2026-10-09','page_count':result['page_count'],'title':lesson.title})
            with sync_playwright() as p:
                browser=p.chromium.launch();page=browser.new_page(viewport={'width':1440,'height':1000})
                errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
                page.goto(base+'/')
                expect(page.locator('#readDemo')).to_be_visible()
                page.locator('#readDemo').click()
                expect(page.locator('#graph')).to_have_attribute('data-ready','true')
                expect(page.locator('input[type=file]')).to_have_count(0)
                page.locator('#conceptList button').first.click()
                page.locator('#sectionLinks a').first.click()
                expect(page.locator('#lessonFrame')).to_have_attribute('data-ready','true',timeout=30000)
                frame=page.frame_locator('#lessonFrame')
                expect(frame.locator('#pages .web-source-button').first).to_be_visible()
                frame.locator('#pages .web-source-button').first.click()
                expect(page.locator('#sourceDialog')).to_be_visible()
                expect(page.locator('#sourceContent pre')).to_contain_text('已知')
                page.locator('#closeSource').click()
                expect(page.locator('#sourceDialog')).to_be_hidden()
                page.locator('#mapMode').click()
                page.reload()
                expect(page.locator('#graph')).to_have_attribute('data-ready','true')
                page.set_viewport_size({'width':390,'height':844})
                page.locator('#themeButton').click()
                assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
                page.locator('#readMode').click()
                expect(page.locator('#lessonFrame')).to_have_attribute('data-ready','true',timeout=30000)
                assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
                assert not errors,errors
                # A valid job identifier in a different course never exposes its files.
                wrong=page.request.get(base+f'/api/handouts/{job_id}/artifacts/lesson.json?course_id=')
                assert wrong.status==404,wrong.status
                assert page.request.get(base+'/margin/api/documents').status==404
                browser.close()
                print('PASS course materials reader, graph-to-lesson, source return, reload, mobile/dark, course isolation; no second upload app')

if __name__=='__main__': main()
