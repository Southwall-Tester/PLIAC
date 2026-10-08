"""Canvas interactions, hierarchy and viewport checks against a temporary course store."""
from pathlib import Path
import json
import re
import socket
import sys
import tempfile
import threading
import time
from unittest.mock import patch

import httpx
import uvicorn
from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from learning_agent import api
from learning_agent.course_graph import CourseGraphStore
from learning_agent.main import app


def expect_controls(page, *, visible=(), hidden=()):
    for selector in visible:
        expect(page.locator(selector)).to_be_visible()
    for selector in hidden:
        expect(page.locator(selector)).to_be_hidden()


def assert_neutral_toolbar(page):
    page.mouse.move(0, page.viewport_size['height'] - 1)
    page.wait_for_timeout(180)
    styles = page.locator('.topbar button:visible, .topbar .button:visible').evaluate_all('''elements => elements.map(element => {
      const style=getComputedStyle(element);
      return [style.color,style.backgroundColor,style.borderTopColor];
    })''')
    assert styles and all(style == styles[0] for style in styles), styles
    for color in styles[0]:
        channels = [int(n) for n in re.findall(r'\d+', color)[:3]]
        assert max(channels) - min(channels) <= 18, color
    assert page.locator('.topbar nav a:visible').evaluate_all(
        '(links,color)=>links.every(link=>getComputedStyle(link).color===color)', styles[0][0])


def assert_dark_surfaces(page, selectors):
    for selector in selectors:
        surface = page.locator(selector).first
        expect(surface).to_be_visible()
        color = surface.evaluate('''element => {
          for(let current=element;current;current=current.parentElement){
            const channels=getComputedStyle(current).backgroundColor.match(/[\\d.]+/g)?.map(Number);
            if(channels && (channels.length===3 || channels[3]>=.9)) return channels.slice(0,3);
          }
          return [255,255,255];
        }''')
        assert max(color) <= 95, (selector, color)


def assert_left_controls(page):
    controls = page.locator('.topbar button:visible, .topbar a:visible, .topbar .active-course-title:visible').evaluate_all('''elements => elements.map(element => {
      const r=element.getBoundingClientRect();return {x:r.x,right:r.right,center:r.y+r.height/2};
    })''')
    rows = []
    for control in sorted(controls, key=lambda item: item['center']):
        if not rows or abs(rows[-1][0]['center'] - control['center']) > 12:
            rows.append([])
        rows[-1].append(control)
    assert rows
    for row in rows:
        row.sort(key=lambda item: item['x'])
        assert row[0]['x'] <= 16, row
        assert all(-1 <= right['x'] - left['right'] <= 28 for left, right in zip(row, row[1:])), row
        assert row[-1]['right'] <= page.viewport_size['width'], row
    graph_controls = page.locator('.graph-toolbar')
    if graph_controls.is_visible():
        graph_left = page.locator('.graph-pane').bounding_box()['x']
        assert 0 <= graph_controls.bounding_box()['x'] - graph_left <= 20, graph_controls.bounding_box()


def main():
    output = ROOT / 'outputs/verification'
    output.mkdir(parents=True, exist_ok=True)
    report = {'checks': [], 'errors': [], 'temporary_store': True}
    with tempfile.TemporaryDirectory() as tmp, socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
        sock.close()
        server = uvicorn.Server(uvicorn.Config(app, host='127.0.0.1', port=port, log_level='error'))
        with patch.object(api, 'store', CourseGraphStore(output_dir=tmp)):
            thread = threading.Thread(target=server.run, daemon=True)
            thread.start()
            try:
                url = f'http://127.0.0.1:{port}'
                for _ in range(100):
                    try:
                        if httpx.get(url+'/health').is_success:
                            break
                    except httpx.HTTPError:
                        pass
                    time.sleep(.1)
                with sync_playwright() as p:
                    browser = p.chromium.launch()
                    page = browser.new_page(viewport={'width':1440, 'height':900})
                    page.on('pageerror', lambda e:report['errors'].append(str(e)))
                    page.add_init_script("""Object.defineProperty(window,'NetworkView',{
                      get(){return this.__View},set(View){this.__View=class extends View{
                        constructor(...args){super(...args);window.__network=this;}
                      }}});""")
                    page.goto(url+'/')
                    expect(page.locator('#unpublished')).to_be_visible()
                    expect_controls(page, visible=('#themeButton', '#authorView'), hidden=(
                        '#physicsSettings', '#stabilizeButton', '#filtersButton', '#labelsButton',
                        '#statsButton', '#profileButton', '#manageButton', '#importDocuments', '.zoom-buttons'))
                    page.locator('#themeButton').click()
                    expect(page.locator('body')).to_have_class(re.compile(r'network-dark'))
                    expect(page.locator('html')).to_have_class(re.compile(r'network-dark'))
                    assert_dark_surfaces(page, ('html', 'body', 'main', '#unpublished'))
                    assert_neutral_toolbar(page)
                    assert_left_controls(page)
                    page.locator('#themeButton').click()
                    report['checks'].append('unpublished page hides graph actions while navigation and theme remain functional')
                    page.goto(url+'/author')
                    page.wait_for_function('window.__network?.data?.nodes.length === 43 && !window.__network.busy')
                    expect_controls(page, visible=('#manageButton', '#importDocuments', '#stabilizeButton'),
                                    hidden=('#profileButton',))
                    assert_neutral_toolbar(page)
                    assert_left_controls(page)
                    expect(page.locator('.sidebar')).to_be_hidden()
                    expect(page.locator('.detail-pane')).to_be_hidden()
                    assert page.evaluate('__network.graph.getOptions().node.type') == 'circle'
                    # Parallel relations remain separate paths, rather than overlapping labels.
                    parallel = page.evaluate('''() => ['edge005','edge053'].map(id=>{
                      const edge=__network.graph.context.element.getElement(id);
                      return {path:edge.getShape('key').attributes.d,arrow:edge.attributes.endArrow};
                    })''')
                    assert parallel[0]['path'] != parallel[1]['path'], parallel
                    assert all(edge['arrow'] for edge in parallel), parallel
                    assert page.evaluate('__network.data.edges.filter(e=>e.data.type!=="hierarchy").length') == 68
                    report['checks'].append('43 circular nodes including course and two units; 68 semantic plus hierarchy edges; full canvas')
                    batched = page.evaluate('''async () => {
                      const nodes=Array.from({length:48},(_,i)=>({id:String(i)}));
                      const edges=nodes.slice(1).map((n,i)=>({source:String(i),target:n.id}));
                      const direct=new CourseNetwork(),batched=new CourseNetwork();
                      direct.setData(nodes,edges);batched.setData(nodes,edges);
                      const directMovement=direct.step(32);let inputTurn=false;
                      setTimeout(()=>{inputTurn=true},0);
                      const batchedMovement=await batched.stepAsync(32,0);
                      return {same:JSON.stringify(direct.positions())===JSON.stringify(batched.positions()),
                        sameMovement:directMovement===batchedMovement,inputTurn};
                    }''')
                    assert all(batched.values()), batched
                    page.wait_for_function('__network.frame===null && !__network.busy && !__network.transition && !__network.focusDirty')
                    page.evaluate('''window.__idleTicks=0;const originalTick=__network.tick;
                      __network.tick=async()=>{__idleTicks++;return originalTick()};void 0;''')
                    page.wait_for_timeout(100)
                    assert page.evaluate('__idleTicks') == 0, page.evaluate('({ticks:__idleTicks,focus:__network.focus,dirty:__network.focusDirty,transition:!!__network.transition,busy:__network.busy,frame:__network.frame})')
                    report['checks'].append('Batched layout yields to the event loop with bit-identical positions; an idle graph schedules no animation frames')
                    zoom_before = page.evaluate('__network.graph.getZoom()')
                    graph_box = page.locator('#graph').bounding_box()
                    page.mouse.move(graph_box['x'] + graph_box['width'] * .75, graph_box['y'] + graph_box['height'] * .65)
                    anchor_before = page.evaluate('__network.graph.getCanvasByViewport([__network.element.clientWidth*.75,__network.element.clientHeight*.65])')
                    page.mouse.wheel(0, -100)
                    page.wait_for_timeout(250)
                    zoom_after = page.evaluate('__network.graph.getZoom()')
                    assert 1 < zoom_after / zoom_before <= 1.105, (zoom_before, zoom_after)
                    anchor_after = page.evaluate('__network.graph.getCanvasByViewport([__network.element.clientWidth*.75,__network.element.clientHeight*.65])')
                    assert max(abs(a-b) for a,b in zip(anchor_before,anchor_after)) < 2
                    page.mouse.wheel(0, 100)
                    page.wait_for_timeout(250)
                    zoom_out = page.evaluate('__network.graph.getZoom()')
                    assert .895 <= zoom_out / zoom_after < 1, (zoom_after,zoom_out)
                    page.mouse.wheel(0, -4)
                    page.wait_for_timeout(250)
                    zoom_small = page.evaluate('__network.graph.getZoom()')
                    assert 1 < zoom_small / zoom_out < 1.015
                    positions_before_zoom = page.evaluate('__network.force.positions()')
                    page.locator('#zoomIn').click()
                    page.wait_for_timeout(180)
                    assert abs(page.evaluate('__network.graph.getZoom()') / zoom_small - 1.1) < .005
                    assert positions_before_zoom == page.evaluate('__network.force.positions()')
                    page.locator('#fitButton').click()
                    page.wait_for_timeout(250)
                    report['checks'].append('Wheel step is capped at 10 percent with cursor anchor preserved; small trackpad inputs stay finer; zoom buttons change 10 percent without moving nodes')
                    page.wait_for_function('!__network.busy')
                    positions = page.evaluate('__network.force.positions()')
                    page.wait_for_timeout(350)
                    assert positions == page.evaluate('__network.force.positions()')
                    page.locator('#physicsSettings').click()
                    page.locator('#repulsion').fill('12000')
                    page.locator('#physicsDialog button[aria-label]').click()
                    page.wait_for_timeout(150)
                    assert positions == page.evaluate('__network.force.positions()')
                    page.locator('#stabilizeButton').click()
                    page.wait_for_function('!__network.busy')
                    assert positions != page.evaluate('__network.force.positions()')
                    positions = page.evaluate('__network.force.positions()')
                    page.wait_for_timeout(350)
                    assert positions == page.evaluate('__network.force.positions()')
                    report['checks'].append('graph stays static; settings take effect on explicit arrange; arranged positions remain static')
                    page.locator('#labelsButton').click()
                    page.wait_for_function('!__network.busy')
                    assert page.evaluate('__network.graph.getNodeData().every(n=>n.style.labelText==="")')
                    page.locator('#labelsButton').click()
                    page.locator('#themeButton').click()
                    expect(page.locator('body')).to_have_class('author-mode network-dark')
                    page.wait_for_function('!__network.busy')
                    assert_neutral_toolbar(page)
                    assert_dark_surfaces(page, ('html', 'body', 'main', '.graph-pane', '.graph-stage'))
                    page.locator('#manageButton').click()
                    expect(page.locator('#nodeEditor')).to_be_visible()
                    assert_dark_surfaces(page, ('#manager', '#managerBody', '#editPick', '#editTitle', '#editDescription'))
                    page.locator('[data-mode="import"]').click()
                    expect(page.locator('#importJson')).to_be_visible()
                    assert_dark_surfaces(page, ('#manager', '#managerBody', '#importFile', '#importJson'))
                    page.screenshot(path=str(output/'network-import-dark.png'))
                    page.locator('#manager .close-dialog').click()
                    page.set_viewport_size({'width':390, 'height':844})
                    assert_left_controls(page)
                    assert_dark_surfaces(page, ('html', 'body', 'main', '.graph-pane', '.graph-stage'))
                    page.screenshot(path=str(output/'network-dark-mobile.png'))
                    page.set_viewport_size({'width':1440, 'height':900})
                    report['checks'].append('dark course and import forms cover page surfaces; toolbar and structure controls stay left on desktop and mobile')
                    page.locator('#themeButton').click()
                    report['checks'].append('author actions suit editing; toolbar controls share neutral colors in both themes; labels and theme update graph')
                    page.locator('#filtersButton').click()
                    expect(page.locator('#colorMode')).to_have_value('family')
                    color_data = page.evaluate('''() => {
                      const normalized = color => { const context=document.createElement('canvas').getContext('2d');context.fillStyle=color;return context.fillStyle; };
                      return {nodes:__network.graph.getNodeData().map(n=>({id:n.id,family:n.data.family_id,kind:n.data.kind,fill:normalized(n.style.fill),size:n.style.size})),
                        legend:[...document.querySelectorAll('#colorLegend [data-family]')].map(item=>({id:item.dataset.family,fill:normalized(item.querySelector('i').style.backgroundColor)}))};
                    }''')
                    concepts = [n for n in color_data['nodes'] if n['kind'] == 'concept']
                    families = {n['family'] for n in concepts}
                    assert families == {'ch1', 'ch2'}
                    family_colors = {family: {n['fill'] for n in concepts if n['family'] == family} for family in families}
                    assert all(len(colors) == 1 for colors in family_colors.values()), family_colors
                    assert family_colors['ch1'] != family_colors['ch2']
                    for family in families:
                        assert {n['fill'] for n in color_data['nodes'] if n['family'] == family} == family_colors[family]
                    common_root = next(n for n in color_data['nodes'] if n['id'] == 'course_root')
                    assert common_root['family'] is None
                    assert common_root['fill'] not in set().union(*family_colors.values())
                    assert all(n['size'] == 12 for n in concepts)
                    assert next(n['size'] for n in color_data['nodes'] if n['id'] == 'course_root') == 42
                    assert all(n['size'] == 32 for n in color_data['nodes'] if n['id'].startswith('chapter_'))
                    for item in color_data['legend']:
                        assert item['fill'] in family_colors[item['id']]
                    original_colors = {n['id']: n['fill'] for n in color_data['nodes']}
                    page.locator('[data-chapter="ch1"]').click()
                    page.wait_for_function('__network.data.nodes.filter(n=>n.data.kind==="concept").length===20 && !__network.busy')
                    assert page.evaluate('expected => __network.graph.getNodeData().every(n=>n.style.fill===expected[n.id])', original_colors)
                    expect(page.locator('#colorLegend [data-family]')).to_have_count(1)
                    page.locator('[data-chapter="all"]').click()
                    page.wait_for_function('__network.data.nodes.length===43 && !__network.busy')
                    assert page.evaluate('expected => __network.graph.getNodeData().every(n=>n.style.fill===expected[n.id])', original_colors)
                    report['checks'].append('chapter families share distinct stable colors with matching legend; node sizes encode levels rather than degree')
                    page.locator('#levelFilter').select_option('chapter')
                    page.wait_for_function('__network.data.nodes.length===3 && !__network.busy')
                    page.locator('#levelFilter').select_option('root')
                    page.wait_for_function('__network.data.nodes.length===1 && !__network.busy')
                    expect_controls(page, visible=('#filtersButton', '#labelsButton'),
                                    hidden=('#physicsSettings', '#stabilizeButton'))
                    page.locator('#levelFilter').select_option('concept')
                    page.wait_for_function('__network.data.nodes.length===43 && !__network.busy')
                    before_empty = page.evaluate('''() => ({positions:__network.force.positions(),
                      zoom:__network.graph.getZoom(),origin:__network.graph.getViewportByCanvas([0,0])})''')
                    page.locator('#relationFilter').select_option('prerequisite')
                    page.locator('#search').fill('__no_course_node_matches__')
                    page.wait_for_function('__network.data.nodes.length===0 && !__network.busy')
                    expect_controls(page, visible=('#filtersButton', '#statsButton'), hidden=(
                        '#physicsSettings', '#stabilizeButton', '#labelsButton', '.zoom-buttons'))
                    page.locator('#search').fill('')
                    page.locator('#relationFilter').select_option('all')
                    page.wait_for_function('__network.data.nodes.length===43 && !__network.busy')
                    after_empty = page.evaluate('''() => ({positions:__network.force.positions(),
                      zoom:__network.graph.getZoom(),origin:__network.graph.getViewportByCanvas([0,0])})''')
                    assert before_empty == after_empty
                    expect_controls(page, visible=('#physicsSettings', '#stabilizeButton', '#labelsButton', '.zoom-buttons'))
                    report['checks'].append('single-root and empty filtered views hide inapplicable tools; restoring filters preserves all positions and viewport without relayout')
                    page.locator('#closeFilters').click()
                    def position(ident):
                        return page.evaluate('id=>{const p=__network.graph.getViewportByCanvas(__network.graph.getElementPosition(id));const r=document.querySelector("#graph").getBoundingClientRect();return {x:p[0]+r.x,y:p[1]+r.y}}', ident)
                    def geometry():
                        return page.evaluate('''() => ({
                          positions:Object.fromEntries(__network.graph.getNodeData().map(n=>[n.id,__network.graph.getElementPosition(n.id)])),
                          zoom:__network.graph.getZoom(),origin:__network.graph.getViewportByCanvas([0,0])
                        })''')
                    def assert_geometry_preserved(before, after):
                        assert after['zoom'] == before['zoom'] and after['origin'] == before['origin'], (before, after)
                        assert all(coords == before['positions'][ident] for ident, coords in after['positions'].items()), (before, after)
                    chapter = page.evaluate('__network.data.nodes.find(n=>n.id.startsWith("chapter_")).id')
                    chapter_title = page.evaluate('id=>__network.data.nodes.find(n=>n.id===id).data.title',chapter)
                    before_click = geometry()
                    pos = position(chapter)
                    page.mouse.click(pos['x'],pos['y'])
                    expect(page.locator('#detailContent h2')).to_have_text(chapter_title)
                    expect(page.locator('.detail-pane')).to_be_visible()
                    assert page.evaluate('__network.data.nodes.length') == 43
                    assert_geometry_preserved(before_click,geometry())
                    expect(page.locator('#toggleCourseBranch')).to_have_count(0)
                    page.locator('#closeDetail').click()
                    pos = position(chapter)
                    page.mouse.click(pos['x'],pos['y'],button='right')
                    expect(page.locator('#graphContextMenu')).to_be_visible()
                    page.get_by_role('menuitem',name=re.compile(r'^收起下级')).click()
                    page.wait_for_function('__network.data.nodes.length===23 && !__network.busy')
                    assert_geometry_preserved(before_click,geometry())
                    pos = position(chapter)
                    page.mouse.click(pos['x'],pos['y'],button='right')
                    page.get_by_role('menuitem',name=re.compile(r'^展开下级')).click()
                    page.wait_for_function('__network.data.nodes.length===43 && !__network.busy')
                    assert_geometry_preserved(before_click,geometry())
                    assert page.evaluate('expected => __network.graph.getNodeData().every(n=>n.style.fill===expected[n.id])', original_colors)
                    pos = position('ml001')
                    page.mouse.click(pos['x'],pos['y'],button='right')
                    expect(page.get_by_role('menuitem')).to_have_count(1)
                    page.get_by_role('menuitem',name='查看详情').click()
                    expect(page.locator('.detail-pane')).to_be_visible()
                    assert page.evaluate('__network.data.nodes.length') == 43
                    assert_geometry_preserved(before_click,geometry())
                    page.locator('#closeDetail').click()
                    report['checks'].append('single click opens details; structural right-click collapse and expand preserve geometry; concept menu only opens details')
                    page.mouse.move(10,10)
                    page.wait_for_timeout(300)
                    base_size = page.evaluate('__network.graph.getNodeData("ml001").style.size')
                    pos = position('ml001')
                    zoom = page.evaluate('__network.graph.getZoom()')
                    radius = base_size * zoom / 2
                    # The label belongs to the G6 node event target, but it must
                    # not count as entering the node's circular key shape.
                    page.mouse.move(pos['x'], pos['y'] + radius + 10 * zoom)
                    page.wait_for_timeout(280)
                    assert page.evaluate('__network.focus') is None
                    assert page.evaluate('__network.graph.getNodeData().every(n => Math.abs((n.style.opacity??1)-1)<.001)')
                    page.mouse.move(pos['x'] + radius + 2, pos['y'])
                    page.wait_for_timeout(280)
                    assert page.evaluate('__network.focus') is None
                    assert page.evaluate('__network.graph.getNodeData().every(n => Math.abs((n.style.opacity??1)-1)<.001)')
                    report['checks'].append('text label and points beyond the resting circle do not trigger hover')
                    other = page.evaluate('''() => {
                      const near = new Set(['ml001']);
                      for (const edge of __network.data.edges) {
                        if (edge.source === 'ml001') near.add(edge.target);
                        if (edge.target === 'ml001') near.add(edge.source);
                      }
                      return __network.data.nodes.find(n => n.id.startsWith('ml') && !near.has(n.id)).id;
                    }''')
                    page.evaluate('''id => {
                      window.__hoverSamples = [];
                      window.__hoverSampling = true;
                      const sample = time => {
                        const nodes = __network.graph.getNodeData();
                        const first = nodes.find(n => n.id === 'ml001');
                        const other = nodes.find(n => n.id === id);
                        __hoverSamples.push({time, focus: __network.focus,
                          opacity: other.style.opacity ?? 1,
                          size: first.style.size});
                        if (__hoverSampling) requestAnimationFrame(sample);
                      };
                      requestAnimationFrame(sample);
                    }''', other)
                    pos = position('ml001')
                    page.mouse.move(pos['x'],pos['y'])
                    page.wait_for_function('__network.focus === "ml001" && __network.graph.getNodeData().some(n=>Math.abs(n.style.opacity-.12)<.001)')
                    page.wait_for_timeout(80)
                    samples = page.evaluate('window.__hoverSampling=false; window.__hoverSamples')
                    assert any(.13 < sample['opacity'] < .99 for sample in samples), samples
                    assert any(base_size < sample['size'] < base_size * 1.15 for sample in samples), samples
                    highlighted = page.evaluate('__network.graph.getNodeData("ml001").style')
                    assert abs(highlighted['size'] - base_size * 1.16) < .05, highlighted
                    assert highlighted.get('shadowBlur', 0) > 0 or highlighted.get('haloLineWidth', 0) > 0, highlighted
                    report['checks'].append('hover opacity and size have intermediate animation frames; focused node finishes enlarged and glowing')

                    other_pos = position(other)
                    for ident, target in [(other,other_pos),('ml001',pos),(other,other_pos),('ml001',pos),(other,other_pos)]:
                        page.mouse.move(target['x'],target['y'])
                        page.wait_for_timeout(25)
                    page.wait_for_function('id => __network.focus===id && __network.graph.getNodeData("ml001").style.opacity <= .121', arg=other)
                    page.mouse.move(10,10)
                    page.wait_for_function('!__network.focus && __network.graph.getNodeData().every(n => Math.abs((n.style.opacity??1)-1)<.001)')
                    restored = page.evaluate('__network.graph.getNodeData("ml001").style')
                    assert abs(restored['size'] - base_size) < .05, restored
                    assert restored.get('shadowBlur',0) < .05 and restored.get('haloLineWidth',0) < .05, restored
                    report['checks'].append('rapid cross-node hover retargets correctly and restores opacity, size and glow on exit')
                    page.wait_for_function('__network.frame===null && !__network.busy && !__network.transition')
                    page.evaluate('''Object.defineProperty(document,'hidden',{configurable:true,value:true});
                      __network.setFocus('ml001');document.dispatchEvent(new Event('visibilitychange'));''')
                    assert page.evaluate('__network.frame===null && __network.focusDirty')
                    page.evaluate("delete document.hidden;document.dispatchEvent(new Event('visibilitychange'))")
                    page.wait_for_function('__network.graph.getNodeData("ml001").style.shadowBlur===16 && !__network.transition')
                    page.evaluate('__network.setFocus(null)')
                    page.wait_for_function('__network.frame===null && !__network.busy && !__network.transition')
                    assert page.evaluate('__network.graph.getNodeData().every(n=>Math.abs((n.style.opacity??1)-1)<.001)')
                    report['checks'].append('Hidden-page highlights defer frames, resume after visibility changes, and stop again when settled')

                    # A resting graph stays still before, during and after hover.
                    pos = position('ml001')
                    page.mouse.move(pos['x'],pos['y'])
                    page.wait_for_function('__network.focus === "ml001"')
                    page.evaluate('window.__hoverLeaves=[];__network.graph.on("node:pointerleave",e=>__hoverLeaves.push(e.target.id))')
                    positions = page.evaluate('__network.force.positions()')
                    page.wait_for_timeout(350)
                    assert positions == page.evaluate('__network.force.positions()')
                    assert page.evaluate('__network.focus') == 'ml001'
                    assert page.evaluate('__hoverLeaves') == []
                    page.mouse.move(10,10)
                    page.wait_for_timeout(350)
                    assert positions == page.evaluate('__network.force.positions()')
                    page.wait_for_function('!__network.busy')
                    report['checks'].append('stationary hover has no leave events and no node movement; exit preserves static positions')

                    pos = position('ml001')
                    page.mouse.move(pos['x'],pos['y'])
                    page.wait_for_function('__network.focus === "ml001"')
                    old = page.evaluate('__network.graph.getElementPosition("ml001")')
                    page.mouse.down()
                    page.mouse.move(pos['x']+80,pos['y']-25,steps=8)
                    page.mouse.up()
                    page.wait_for_timeout(100)
                    new = page.evaluate('__network.graph.getElementPosition("ml001")')
                    assert abs(new[0]-old[0]) > 20
                    point = page.evaluate('__network.force.points.get("ml001")')
                    assert abs(point['x']-new[0]) < 1
                    page.mouse.move(10,10)
                    report['checks'].append('native node drag persists into force coordinates after animated hover')
                    page.locator('#fitButton').click()
                    zoom = page.evaluate('__network.graph.getZoom()')
                    page.locator('#zoomIn').click()
                    page.wait_for_timeout(350)
                    assert page.evaluate('__network.graph.getZoom()') > zoom
                    page.locator('#fitButton').click()
                    page.wait_for_timeout(350)
                    page.screenshot(path=str(output/'network-desktop.png'))
                    page.set_viewport_size({'width':390,'height':844})
                    page.locator('#fitButton').click()
                    page.locator('#filtersButton').click()
                    page.locator('[data-node="ml001"]').click()
                    expect(page.locator('.detail-pane')).to_be_visible()
                    expect(page.locator('.sidebar')).to_be_hidden()
                    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                    page.screenshot(path=str(output/'network-mobile.png'))
                    report['checks'].append('zoom, fit, mobile drawers and no horizontal overflow')

                    # A browser-only published fixture exercises an empty learner
                    # expression view without manufacturing review/publication records.
                    fixture = httpx.get(url+'/api/course-graph?view=draft').json()
                    fixture['learner'] = {'evidence': [], 'states': {}, 'profile': {}}
                    page.route(re.compile(r'/api/course-graph\?'), lambda route: route.fulfill(json=fixture))
                    page.set_viewport_size({'width':1440, 'height':900})
                    page.goto(url+'/')
                    page.wait_for_function('window.__network?.data?.nodes.length===43 && !window.__network.busy')
                    expect_controls(page, visible=('#structureView',), hidden=('#manageButton', '#importDocuments', '#profileButton'))
                    page.locator('#structureView').select_option('expressions')
                    page.wait_for_function('__network.data.nodes.length===0 && !__network.busy')
                    expect_controls(page, visible=('#filtersButton', '#statsButton'), hidden=(
                        '#physicsSettings', '#stabilizeButton', '#labelsButton', '.zoom-buttons'))
                    page.locator('#structureView').select_option('course')
                    page.wait_for_function('__network.data.nodes.length===43 && !__network.busy')
                    expect_controls(page, visible=('#stabilizeButton', '#labelsButton', '.zoom-buttons'))
                    report['checks'].append('empty expression view keeps its recovery controls and restores graph tools on returning to course')
                    # Keep real force iterations in flight while controls enqueue
                    # newer topology and display changes. No rendering is mocked.
                    raced = browser.new_page(viewport={'width':1440, 'height':900})
                    raced.on('pageerror', lambda error: report['errors'].append('queued controls: '+str(error)))
                    raced.add_init_script('''Object.defineProperty(window,'NetworkView',{
                      get(){return this.__View},set(View){this.__View=class extends View{
                        constructor(...args){super(...args);window.__network=this;}
                      }}});''')
                    raced.goto(url+'/author')
                    raced.wait_for_function('window.__network?.data?.nodes.length===43 && !__network.busy')
                    raced.locator('#filtersButton').click()
                    raced.evaluate('''() => {
                      window.__layoutSizes=[];window.__layoutRunning=false;
                      const step=__network.force.stepAsync.bind(__network.force);
                      __network.force.stepAsync=async function(iterations){
                        __layoutRunning=true;__layoutSizes.push(this.nodes.length);
                        try{return await step(iterations,0);}finally{__layoutRunning=false;}
                      };
                      window.__layoutTask=__network.setData(__network.data,false,600);
                    }''')
                    raced.wait_for_function('__layoutRunning && __network.busy')
                    raced.locator('#levelFilter').select_option('chapter')
                    raced.locator('#themeButton').click()
                    raced.locator('#labelsButton').click()
                    raced.locator('#stabilizeButton').click()
                    raced.wait_for_function('!__layoutRunning && !__network.busy && !__network.arranging && __layoutSizes.length===2')
                    raced.evaluate('async()=>{await __layoutTask;await __network.operations;}')
                    result = raced.evaluate('''() => {
                      const ids=items=>items.map(item=>item.id).sort();
                      return {data:ids(__network.data.nodes),rendered:ids(__network.graph.getNodeData()),
                        force:ids(__network.force.nodes),edges:ids(__network.data.edges),
                        renderedEdges:ids(__network.graph.getEdgeData()),layoutSizes:__layoutSizes,
                        dark:document.body.classList.contains('network-dark'),labels:__network.labels,
                        styles:__network.graph.getNodeData().map(n=>({label:n.style.labelText,color:n.style.labelFill}))};
                    }''')
                    expected_ids = ['chapter_ch1', 'chapter_ch2', 'course_root']
                    assert result['data'] == result['rendered'] == result['force'] == expected_ids, result
                    assert result['edges'] == result['renderedEdges'] and len(result['edges']) == 2, result
                    assert result['layoutSizes'] == [43, 3], result
                    assert result['dark'] and not result['labels'], result
                    assert all(style == {'label': '', 'color': '#e8edf6'} for style in result['styles']), result
                    raced.close()
                    report['checks'].append('Filtering, theme, labels and arrange queued during real asynchronous layout retain the latest topology and display state')
                    # Simulate a browser retaining the older layout asset while the
                    # newer view has already loaded. Keep this in an isolated page.
                    cached = browser.new_page(viewport={'width':1440, 'height':900})
                    cached.on('pageerror', lambda error: report['errors'].append('cached layout: '+str(error)))
                    cached.add_init_script('''
                      window.__cachedStepCalls=0;window.__cachedMaxIterations=0;
                      Object.defineProperty(window,'CourseNetwork',{
                        get(){return this.__Force},set(Force){
                          delete Force.prototype.stepAsync;
                          const step=Force.prototype.step;
                          Force.prototype.step=function(iterations=1){
                            __cachedStepCalls++;__cachedMaxIterations=Math.max(__cachedMaxIterations,iterations);
                            return step.call(this,iterations);
                          };
                          this.__Force=Force;
                        }
                      });
                      Object.defineProperty(window,'NetworkView',{
                        get(){return this.__View},set(View){this.__View=class extends View{
                          constructor(...args){super(...args);window.__network=this;}
                        }}
                      });
                    ''')
                    cached.goto(url+'/author')
                    cached.wait_for_function('window.__network?.data?.nodes.length===43 && !__network.busy')
                    assert cached.evaluate('typeof __network.force.stepAsync') == 'undefined'
                    expect(cached.locator('#graphMessage')).to_be_hidden()
                    assert cached.evaluate('__cachedStepCalls') == 320
                    cached.locator('#stabilizeButton').click()
                    cached.wait_for_function('!__network.busy && !__network.arranging')
                    assert cached.evaluate('__cachedStepCalls') == 920
                    assert cached.evaluate('__cachedMaxIterations') == 1
                    assert cached.evaluate('__network.graph.getNodeData().every(n=>Number.isFinite(n.style.x)&&Number.isFinite(n.style.y))')
                    cached.close()
                    assert page.evaluate('typeof CourseNetwork.prototype.stepAsync') == 'function'
                    report['checks'].append('Mixed cached assets without stepAsync still render and arrange in single-step batches; the normal page remains unchanged')
                    assert not report['errors'],report['errors']
                    browser.close()
            finally:
                server.should_exit = True
                thread.join(10)
    report['passed'] = True
    (output/'network-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False,indent=2))


if __name__ == '__main__':
    main()
