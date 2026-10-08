"""Manual, read-only graph benchmark; replay one saved API snapshot per browser run.

python tests/test_ui_large_graph.py --snapshot outputs/verification/large-graph-snapshot.json --tag baseline
This benchmark never uploads, retries, cancels, or changes a course/document.
"""
import argparse
import copy
import hashlib
import json
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
HOOK = r"""window.__bench={phase:'initial',calls:[],longTasks:[],frames:[],errors:[],wrapped:[]};
const bench=window.__bench;
function wrap(target,key,name){
  const original=target?.[key];if(typeof original!=='function'||original.__benchWrapped)return;
  function measured(...args){
    const start=performance.now(),phase=bench.phase;
    const entry={name,phase,start,count:Array.isArray(args[0])?args[0].length:undefined};
    try{
      const result=original.apply(this,args);entry.sync=performance.now()-start;
      if(result&&typeof result.then==='function')return result.then(value=>{entry.total=performance.now()-start;bench.calls.push(entry);return value},error=>{entry.total=performance.now()-start;entry.error=String(error);bench.calls.push(entry);throw error});
      entry.total=entry.sync;bench.calls.push(entry);return result;
    }catch(error){entry.total=performance.now()-start;entry.error=String(error);bench.calls.push(entry);throw error;}
  }
  measured.__benchWrapped=true;target[key]=measured;bench.wrapped.push(name);
}
try{new PerformanceObserver(list=>{for(const e of list.getEntries())bench.longTasks.push({phase:bench.phase,start:e.startTime,duration:e.duration})}).observe({type:'longtask',buffered:true})}catch{}
let lastFrame;function frame(now){if(lastFrame!==undefined)bench.frames.push({phase:bench.phase,start:lastFrame,duration:now-lastFrame});lastFrame=now;requestAnimationFrame(frame)}requestAnimationFrame(frame);
Object.defineProperty(window,'NetworkView',{
  get(){return this.__BenchView},set(View){
    for(const name of ['layout','setData','drawData','redraw','hitTest','startFocusTransition','drawFocusTransition'])wrap(View.prototype,name,'view.'+name);
    try{
      const transform=G6.getExtension?.('transform','process-parallel-edges');
      for(const key of Object.getOwnPropertyNames(transform?.prototype||{}))if(key!=='constructor')wrap(transform.prototype,key,'parallel.'+key);
    }catch(error){bench.errors.push('transform hook: '+String(error));}
    this.__BenchView=class extends View{constructor(...args){super(...args);window.__network=this;
      for(const key of ['setData','updateNodeData','updateEdgeData','draw','render','fitView','zoomTo','translateBy'])wrap(this.graph,key,'graph.'+key);
    }};
  }
});
"""


def percentile(values, fraction):
    if not values:
        return 0
    return sorted(values)[min(len(values) - 1, int((len(values) - 1) * fraction))]


def summarize(raw, stages):
    result = {}
    for stage in stages:
        name = stage['name']
        calls = [call for call in raw['calls'] if call['phase'] == name]
        frames = [item['duration'] for item in raw['frames'] if item['phase'] == name]
        long_tasks = [item['duration'] for item in raw['longTasks'] if stage['start'] <= item['start'] < stage['end']]
        methods = {}
        for method in sorted({call['name'] for call in calls}):
            selected = [call for call in calls if call['name'] == method]
            durations = [call['total'] for call in selected]
            methods[method] = {'calls': len(selected), 'total_ms': round(sum(durations), 2),
                               'sync_ms': round(sum(call.get('sync', 0) for call in selected), 2),
                               'p95_ms': round(percentile(durations, .95), 2), 'max_ms': round(max(durations), 2),
                               'items': sum(call.get('count', 0) or 0 for call in selected)}
        result[name] = {'wall_ms': round(stage['end'] - stage['start'], 2),
                        'task_cpu_ms': round(stage['task_cpu_ms'], 2),
                        'script_cpu_ms': round(stage['script_cpu_ms'], 2),
                        'frames': len(frames), 'frame_p95_ms': round(percentile(frames, .95), 2),
                        'frame_max_ms': round(max(frames, default=0), 2),
                        'long_tasks': len(long_tasks), 'long_task_total_ms': round(sum(long_tasks), 2),
                        'methods': methods}
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--snapshot', type=Path, required=True)
    parser.add_argument('--base-url')
    parser.add_argument('--tag', default='baseline')
    parser.add_argument('--view-script', type=Path, help='Replay a saved network-view.js without changing the service')
    parser.add_argument('--document-script', type=Path, help='Hold the document projection fixed for renderer comparisons')
    parser.add_argument('--layout-script', type=Path, help='Replay a saved layout script')
    parser.add_argument('--browser-channel', help='Use chromium for hardware headless; omitted uses the software headless shell')
    args = parser.parse_args()
    saved = json.loads(args.snapshot.read_text(encoding='utf-8'))
    base = (args.base_url or saved['base_url']).rstrip('/')
    job = copy.deepcopy(saved['job'])
    job['status'] = 'completed'  # Browser fixture stops polling; source JSON remains unchanged.
    graph = saved['graph']
    ident = job['id']
    output = ROOT / 'outputs/verification' / ('large-graph-' + args.tag + '.json')
    report = {'snapshot': str(args.snapshot), 'base_url': base, 'tag': args.tag,
              'viewport': {'width': 1440, 'height': 900}, 'errors': [], 'stages': []}
    view_source = (args.view_script or ROOT / 'static/network-view.js').read_bytes()
    document_source = (args.document_script or ROOT / 'static/documents.js').read_bytes()
    layout_source = (args.layout_script or ROOT / 'static/network-layout.js').read_bytes()
    pixi_source = (ROOT / 'static/network-pixi.js').read_bytes()
    report['network_view_sha256'] = hashlib.sha256(view_source).hexdigest()
    report['network_layout_sha256'] = hashlib.sha256(layout_source).hexdigest()
    report['network_pixi_sha256'] = hashlib.sha256(pixi_source).hexdigest()
    report['document_script_sha256'] = hashlib.sha256(document_source).hexdigest()
    with sync_playwright() as p:
        browser = p.chromium.launch(**({'channel':args.browser_channel} if args.browser_channel else {}))
        try:
            page = browser.new_page(viewport=report['viewport'])
            page.set_default_timeout(120000)
            page.on('pageerror', lambda error: report['errors'].append(str(error)))
            page.add_init_script(HOOK)
            # Freeze the renderer resource at benchmark startup, even if another
            # agent edits the on-disk script while this single page is measured.
            page.route('**/static/network-view.js*', lambda route: route.fulfill(body=view_source, content_type='text/javascript'))
            page.route('**/static/documents.js*', lambda route: route.fulfill(body=document_source, content_type='text/javascript'))
            page.route('**/static/network-layout.js*', lambda route: route.fulfill(body=layout_source, content_type='text/javascript'))
            page.route('**/static/network-pixi.js*', lambda route: route.fulfill(body=pixi_source, content_type='text/javascript'))

            def route_api(route):
                request = route.request
                path = request.url.split('?', 1)[0]
                if request.method != 'GET':
                    report['errors'].append('Blocked write: ' + request.method + ' ' + path)
                    route.abort()
                elif path.endswith('/api/documents/' + ident + '/graph'):
                    route.fulfill(json=graph)
                elif path.endswith('/api/documents/' + ident):
                    route.fulfill(json=job)
                elif path.endswith('/api/documents'):
                    route.fulfill(json={'documents': [job]})
                else:
                    route.continue_()

            page.route('**/api/**', route_api)
            cdp = page.context.new_cdp_session(page)
            cdp.send('Performance.enable')

            def metrics():
                return {item['name']: item['value'] for item in cdp.send('Performance.getMetrics')['metrics']}

            def run_stage(name, action):
                print('Starting '+name, flush=True)
                if name != 'initial':
                    page.evaluate('(name)=>{__bench.phase=name}', name)
                before = metrics()
                start = 0 if name == 'initial' else page.evaluate('performance.now()')
                action()
                after = metrics()
                report['stages'].append({'name': name, 'start': start, 'end': page.evaluate('performance.now()'),
                    'task_cpu_ms': 1000 * (after.get('TaskDuration', 0) - before.get('TaskDuration', 0)),
                    'script_cpu_ms': 1000 * (after.get('ScriptDuration', 0) - before.get('ScriptDuration', 0))})
                print('Finished '+name, flush=True)

            def initial():
                page.goto(base + '/documents?id=' + ident, wait_until='domcontentloaded')
                page.wait_for_function('window.__network?.data?.nodes.length>0 && !__network.busy')
                page.evaluate('async()=>{await __network.operations;}')
                page.wait_for_timeout(250)

            run_stage('initial', initial)
            report['graph'] = page.evaluate('({nodes:__network.data.nodes.length,edges:__network.data.edges.length,zoom:__network.graph.getZoom()})')
            report['renderer'] = page.evaluate('''()=>{const g=__network.graph,gl=g.app?.renderer?.gl,ext=gl?.getExtension('WEBGL_debug_renderer_info');return {engine:g.constructor.name,backend:ext?gl.getParameter(ext.UNMASKED_RENDERER_WEBGL):'Canvas2D'}}''')

            def hover():
                points = page.evaluate('''() => {
                  const rect=__network.element.getBoundingClientRect(),points=[];
                  for(const n of __network.graph.getNodeData()){
                    const p=__network.graph.getViewportByCanvas(__network.graph.getElementPosition(n.id));
                    const point={x:p[0]+rect.x,y:p[1]+rect.y,id:n.id};
                    if(point.x>180&&point.x<innerWidth-180&&point.y>150&&point.y<innerHeight-130&&points.every(q=>Math.hypot(point.x-q.x,point.y-q.y)>65))points.push(point);
                    if(points.length===5)break;
                  }return points;
                }''')
                report.setdefault('hover_targets', points)
                for point in points:
                    page.mouse.move(point['x'], point['y'])
                    page.wait_for_timeout(160)
                page.wait_for_timeout(400)
                page.mouse.move(4, 4)
                page.wait_for_timeout(400)

            run_stage('hover_labels', hover)

            def drag():
                point = page.evaluate('''() => {
                  const r=__network.element.getBoundingClientRect();
                  for(let y=r.y+110;y<r.bottom-150;y+=80)for(let x=r.x+45;x<r.right-200;x+=80)if(!__network.hitTest({clientX:x,clientY:y}))return {x,y};
                }''')
                page.mouse.move(point['x'], point['y'])
                page.mouse.down()
                page.mouse.move(point['x'] + 100, point['y'] + 50, steps=12)
                page.mouse.up()
                page.wait_for_timeout(350)

            run_stage('drag_canvas', drag)

            def zoom():
                page.mouse.move(900, 350)
                for delta in (-120, -120, 120, 120):
                    page.mouse.wheel(0, delta)
                    page.wait_for_timeout(200)
                page.wait_for_timeout(400)

            run_stage('zoom', zoom)

            def hide_labels():
                page.locator('#labelsButton').click()
                page.evaluate('async()=>{await __network.operations;}')
                page.wait_for_function('!__network.busy && !__network.transition')

            run_stage('hide_labels', hide_labels)
            run_stage('hover_no_labels', hover)
            run_stage('idle', lambda: page.wait_for_timeout(700))
            report['raw'] = page.evaluate('__bench')
            report['summary'] = summarize(report['raw'], report['stages'])
        except Exception as error:
            report['errors'].append(str(error))
            try:
                report['raw'] = page.evaluate('__bench')
                report['summary'] = summarize(report['raw'], report['stages'])
            except Exception:
                pass
        finally:
            browser.close()
            output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'report': str(output), 'graph': report.get('graph'), 'errors': report['errors'], 'summary': report.get('summary')}, ensure_ascii=False, indent=2))
    if report['errors']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
