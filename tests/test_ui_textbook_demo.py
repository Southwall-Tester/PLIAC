"""Replay the packaged textbook through the real app; no paid model or user writes."""
import json
from pathlib import Path
import statistics
import tempfile
import time

from playwright.sync_api import expect, sync_playwright
from test_ui_documents import isolated_application
from test_ui_large_graph import HOOK
from learning_agent.textbook_demo import DEMO_ID, manifest

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/"outputs/verification"


def main():
    OUT.mkdir(parents=True,exist_ok=True)
    info=manifest()
    report=dict(fixture=DEMO_ID,browser_mode="headless Chromium; measured on this machine, not a user trial",
                source_pages=info["source_pages"],source_characters=info["source_characters"],
                candidate_nodes=500,candidate_edges=2000,model_calls=0,ocr_reexecuted=False)
    with tempfile.TemporaryDirectory() as tmp, isolated_application(Path(tmp)) as (base,_,_):
        with sync_playwright() as p:
            browser=p.chromium.launch()
            page=browser.new_page(viewport={"width":1440,"height":1000})
            errors=[]
            page.on("pageerror",lambda e:errors.append(str(e)))
            page.add_init_script(HOOK)
            page.goto(base+"/courses")
            card=page.locator(f'[data-course-id="{DEMO_ID}"]')
            expect(card).to_be_visible()
            cards=page.locator('.course-card')
            widths=cards.evaluate_all('(items)=>items.map(e=>e.getBoundingClientRect().width)')
            assert len(widths)>=2 and max(widths)-min(widths)<1, widths
            structures=cards.evaluate_all('(items)=>items.map(e=>[...e.children].map(c=>c.tagName+":"+c.className).join("|"))')
            assert len(set(structures))==1, structures
            start=time.perf_counter()
            card.locator('.handout-course').click()
            expect(page.locator('#graph')).to_have_attribute('data-ready','true',timeout=60000)
            page.wait_for_function('marginNetwork.graph.nodeViews.size===500')
            report['first_open_ms']=round((time.perf_counter()-start)*1000,2)
            expect(page.locator('#generate')).to_be_visible()
            expect(page.locator('#graphNotice')).to_contain_text('共现')
            assert page.evaluate('marginNetwork.data.edges.length')==2000
            report['graph_json_bytes']=page.evaluate("performance.getEntriesByType('resource').find(x=>x.name.includes('knowledge-map.json')).decodedBodySize")
            samples=[]
            for index in [0,10,25,49,99]:
                button=page.locator('#conceptList button').nth(index)
                ident=button.get_attribute('data-concept')
                begin=time.perf_counter()
                button.click()
                expect(button).to_have_attribute('aria-pressed','true')
                page.wait_for_function('(id)=>marginNetwork.graph.nodeViews.get(id).style.lineWidth===3&&!marginNetwork.transition',arg=ident)
                samples.append(round((time.perf_counter()-begin)*1000,2))
            report['selection_with_transition_ms']=samples
            report['selection_median_ms']=round(statistics.median(samples),2)
            page.locator('#conceptList button').first.click()
            page.locator('#conceptSources button').first.click()
            expect(page.locator('#sourceDialog')).to_be_visible()
            expect(page.locator('#sourceContent pre')).not_to_be_empty()
            page.locator('#closeSource').click()
            begin=time.perf_counter()
            page.locator('#search').fill('寄存器')
            expect(page.locator('#conceptCount')).to_contain_text('匹配')
            assert page.locator('#conceptList button:visible').count()>0
            report['search_ms']=round((time.perf_counter()-begin)*1000,2)
            page.locator('#search').fill('')
            page.locator('#fit').click()
            page.screenshot(path=str(OUT/'textbook-demo-full-graph.png'),full_page=True)
            report['chapter_switch_ms']={}
            for chapter in ['chapter_1','chapter_5','appendix_a','']:
                expected=next(j for j in info['jobs'] if j['chapter_id']==chapter)
                begin=time.perf_counter()
                page.locator('#chapter').select_option(chapter)
                page.wait_for_function('(count)=>marginNetwork.data.nodes.length===count',arg=expected['candidate_nodes'])
                report['chapter_switch_ms'][chapter or 'all']=round((time.perf_counter()-begin)*1000,2)
            page.locator('#readMode').click()
            expect(page.locator('#lessonFrame')).to_have_attribute('data-ready','true',timeout=30000)
            expect(page.locator('#outline button')).to_have_count(7)
            page.locator('#outline button').nth(4).click()
            expect(page.locator('#outline button').nth(4)).to_have_attribute('aria-current','location')
            page.screenshot(path=str(OUT/'textbook-demo-guide.png'),full_page=True)
            pdf=page.request.get(base+page.locator('#pdfDownload').get_attribute('href'))
            assert pdf.status==200 and pdf.body().startswith(b'%PDF')
            # Exercise shared scope validation without starting a paid model job.
            denied=page.request.post(base+'/api/handouts?course_id='+DEMO_ID,data={'chapter_id':'missing'})
            assert denied.status==404
            page.locator('#mapMode').click()
            page.set_viewport_size({'width':390,'height':844})
            page.locator('#themeButton').click()
            page.locator('#fit').click()
            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
            page.screenshot(path=str(OUT/'textbook-demo-mobile-dark.png'),full_page=True)
            report['long_tasks']=page.evaluate('__bench.longTasks')
            report['network_methods']=page.evaluate('__bench.calls.filter(c=>["view.layout","view.setData"].includes(c.name))')
            report['browser_version']=browser.version
            report['errors']=errors
            assert not errors,errors
            browser.close()
    (OUT/'textbook-demo-performance.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k not in {'long_tasks','network_methods'}},ensure_ascii=False,indent=2))


if __name__=='__main__':main()
