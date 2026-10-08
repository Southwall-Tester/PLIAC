"""Large, synthetic graph: exercise the real GPU renderer and idle scheduling."""
from functools import partial
import argparse
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import threading

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *_):
        pass


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--browser-channel', default='chromium')
    args = parser.parse_args()
    output = ROOT / "outputs/verification"
    output.mkdir(parents=True, exist_ok=True)
    report = {"synthetic": True, "errors": []}
    server = ThreadingHTTPServer(("127.0.0.1", 0), partial(QuietHandler, directory=str(ROOT / "static")))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(channel=args.browser_channel or None)
            try:
                page = browser.new_page(viewport={"width": 1440, "height": 900})
                page.on("pageerror", lambda error: report["errors"].append(str(error)))
                page.set_default_timeout(90000)
                page.goto(f"http://127.0.0.1:{server.server_port}/theme.js")
                page.set_content('<body style="margin:0;background:#fcfbf9"><div id="graph" style="width:1440px;height:900px"></div></body>')
                for path in ("vendor/g6-5.1.1.min.js", "vendor/pixi-8.19.0.min.js", "graph-encoding.js", "network-layout.js", "network-pixi.js", "network-view.js"):
                    page.add_script_tag(url=f"http://127.0.0.1:{server.server_port}/{path}")
                page.evaluate('''async()=>{
                  window.__network=new NetworkView(document.getElementById('graph'),id=>window.__selected=id);
                  const nodes=Array.from({length:501},(_,i)=>({id:'n'+i,data:{title:'合成知识点 '+i},style:{size:i?12:36,fill:['#e8a6ba','#a4cfb1','#c4afe3'][i%3]}}));
                  const edges=Array.from({length:3000},(_,i)=>({id:'e'+i,source:'n'+(i%501),target:'n'+((i%501+1+Math.floor(i/501)*11)%501),data:{label:i%3?'关联':'包含'},style:{endArrow:i%3===0,lineDash:i%5===0?[4,4]:undefined}}));
                  // Known positions avoid conflating layout throughput and interaction rendering.
                  for(let i=0;i<nodes.length;i++)__network.force.points.set('n'+i,{id:'n'+i,x:70+i%25*52,y:65+Math.floor(i/25)*36,vx:0,vy:0});
                  await __network.setData({nodes,edges},true);
                  window.__paintCount=0;window.__paintTimes=[];const paint=__network.graph.app.render.bind(__network.graph.app);
                  __network.graph.app.render=(...args)=>{__paintCount++;const start=performance.now();try{return paint(...args)}finally{__paintTimes.push(performance.now()-start)}};
                }''')
                page.wait_for_timeout(400)
                assert page.evaluate("__network.graph.constructor.name") == "CoursePixiGraph"
                report['backend'] = page.evaluate("()=>{const gl=__network.graph.app.renderer.gl,ext=gl.getExtension('WEBGL_debug_renderer_info');return ext?gl.getParameter(ext.UNMASKED_RENDERER_WEBGL):gl.getParameter(gl.RENDERER)}")
                assert page.evaluate("[__network.graph.getNodeData().length,__network.graph.getEdgeData().length]") == [501, 3000]
                visible_labels=page.evaluate("()=>{const g=__network.graph;return {nodes:[...g.nodeViews.values()].filter(r=>r.label.visible).length,edges:[...g.edgeViews.values()].filter(r=>r.label.visible).length}}")
                assert 0<visible_labels['nodes']<=150 and visible_labels['edges']<=60, visible_labels
                cdp = page.context.new_cdp_session(page)
                cdp.send("Performance.enable")

                def metrics():
                    return {item["name"]: item["value"] for item in cdp.send("Performance.getMetrics")["metrics"]}

                page.mouse.move(2, 2)
                page.wait_for_function("!__network.busy&&!__network.transition&&!__network.focusDirty")
                page.wait_for_timeout(150)
                before, paints = metrics(), page.evaluate("__paintCount")
                page.wait_for_timeout(750)
                after = metrics()
                report["idle_paints"] = page.evaluate("__paintCount") - paints
                report["idle_script_ms"] = round((after["ScriptDuration"] - before["ScriptDuration"]) * 1000, 2)
                assert report["idle_paints"] == 0, report
                assert report["idle_script_ms"] < 100, report
                page.evaluate('''()=>{window.__frames=[];window.__sampling=true;let previous=performance.now();function frame(now){__frames.push(now-previous);previous=now;if(__sampling)requestAnimationFrame(frame)}requestAnimationFrame(frame)}''')
                for i in (27, 53, 79, 105, 131):
                    point = page.evaluate("id=>__network.graph.getViewportByCanvas(__network.graph.getElementPosition(id))", "n" + str(i))
                    page.mouse.move(*point)
                    page.wait_for_timeout(120)
                page.mouse.move(15, 15)
                page.mouse.down()
                page.mouse.move(65, 42, steps=16)
                page.mouse.up()
                for delta in (-120, -120, 120, 120):
                    page.mouse.wheel(0, delta)
                    page.wait_for_timeout(160)
                page.wait_for_timeout(350)
                frames = page.evaluate("()=>{__sampling=false;return __frames}")
                frames.sort()
                report["interaction_frame_p95_ms"] = round(frames[int((len(frames)-1)*.95)], 2)
                report["interaction_frame_max_ms"] = round(max(frames), 2)
                paints = sorted(page.evaluate('__paintTimes'))
                report['paint_cpu_p95_ms'] = round(paints[int((len(paints)-1)*.95)], 2)
                # CI can use CPU-emulated WebGL. Keep its browser/JS work bounded;
                # real hardware additionally has a full interaction-frame budget.
                assert report['paint_cpu_p95_ms'] < 150, report
                if not any(name in report['backend'].lower() for name in ('swiftshader','llvmpipe','software')):
                    assert report["interaction_frame_p95_ms"] < 100, report
                page.mouse.move(2, 2)
                page.wait_for_function("!__network.transition&&!__network.focusDirty")
                point = page.evaluate("__network.graph.getViewportByCanvas(__network.graph.getElementPosition('n53'))")
                position = page.evaluate("__network.graph.getElementPosition('n53')")
                page.mouse.click(*point)
                page.wait_for_function("window.__selected==='n53'")
                page.wait_for_function("!__network.transition&&!__network.focusDirty")
                actual = page.evaluate('''()=>{
                  const g=__network.graph,nodes=[...g.nodeViews.values()],edges=[...g.edgeViews.values()];
                  const focused=g.nodeViews.get('n53'),dim=nodes.find(r=>r.style.opacity===.12),edge=edges.find(r=>r.style.opacity===.05);
                  return {focused:focused.key.getGlobalAlpha(),dim:dim.key.getGlobalAlpha(),edge:edge.key.getGlobalAlpha(),label:dim.text.getGlobalAlpha()};
                }''')
                assert all(abs(actual[key]-value)<.001 for key,value in {'focused':1,'dim':.12,'edge':.05,'label':.12}.items()), actual
                assert page.evaluate("__network.graph.nodeViews.get('n53').label.visible"), 'Focused node label must remain visible'
                assert page.evaluate("__network.graph.getElementPosition('n53')") == position
                assert page.evaluate("[__network.graph.getNodeData().length,__network.graph.getEdgeData().length]") == [501, 3000]
                page.mouse.move(2, 2)
                page.wait_for_timeout(300)
                page.screenshot(path=str(output / "gpu-large-graph.png"))
                assert not report["errors"], report
                report["passed"] = True
            finally:
                browser.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(5)
        (output / "gpu-large-graph-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
