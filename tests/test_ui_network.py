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
                    page.goto(url+'/author')
                    page.wait_for_function('window.__network?.data?.nodes.length === 43 && !window.__network.busy')
                    expect(page.locator('.sidebar')).to_be_hidden()
                    expect(page.locator('.detail-pane')).to_be_hidden()
                    assert page.evaluate('__network.graph.getOptions().node.type') == 'circle'
                    assert page.evaluate('__network.graph.getOptions().edge.type') == 'line'
                    assert page.evaluate('__network.data.edges.filter(e=>e.data.type!=="hierarchy").length') == 68
                    report['checks'].append('43 circular nodes including course and two units; 68 semantic plus hierarchy edges; full canvas')
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
                    page.locator('#themeButton').click()
                    report['checks'].append('labels and dark mode change rendered graph')
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
                    page.locator('#levelFilter').select_option('concept')
                    page.wait_for_function('__network.data.nodes.length===43 && !__network.busy')
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
