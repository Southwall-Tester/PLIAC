"""Measure document preparation separately from G6; preserve every synthetic node.

The renderer boundary is recorded in Chromium so this test measures documents.js
filtering and DOM work, not renderer FPS. Real G6 coverage remains in the document
and hierarchy UI suites. Optional --baseline compares a saved documents.js file.
"""
from pathlib import Path
import argparse
import json
import statistics
import tempfile

from playwright.sync_api import expect, sync_playwright

from test_ui_documents import isolated_application
from learning_agent.documents import atomic_json

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "outputs" / "verification"

RENDERER = """
window.__documentMetrics={draws:[],listWrites:0,legendWrites:0};
const descriptor=Object.getOwnPropertyDescriptor(Element.prototype,'innerHTML');
Object.defineProperty(Element.prototype,'innerHTML',{...descriptor,set(value){
  if(this.id==='nodeList')__documentMetrics.listWrites++;
  if(this.id==='colorLegend')__documentMetrics.legendWrites++;
  descriptor.set.call(this,value);
}});
window.NetworkView=class {
  constructor(element,select,edgeSelect,menu){window.__network=this;this.select=select;this.menu=menu;this.delay=0;}
  bindControls(){} async clearLayout(){}
  async setData(data){this.data=data;__documentMetrics.draws.push(document.querySelector('#search').value);
    if(this.delay)await new Promise(resolve=>setTimeout(resolve,this.delay));}
};
window.showGraphMenu=(title,items)=>{window.__menu={title,items};};
"""


def synthetic_document(store):
    job = store.create("synthetic-large-graph.md")
    root = {"id": "root", "title": "合成资料", "kind": "book", "parent_id": None}
    chapters = [{"id": f"chapter_{i}", "title": f"章节 {i}", "kind": "chapter", "parent_id": "root"}
                for i in range(10)]
    sections = [{"id": f"section_{i}", "title": f"小节 {i}", "kind": "chapter",
                 "parent_id": f"chapter_{i // 9}"} for i in range(90)]
    nodes = [{"id": f"n{i}", "title": f"知识点 {i:04d}", "description": f"计算机组成原理合成说明 {i}",
              "evidence": [{"page": i % 41 + 1, "start": 0, "end": 4, "quote": "合成原文"}]}
             for i in range(500)]
    members = [{"source": f"section_{(i + offset * 19) % 90}", "target": f"n{i}"}
               for i in range(500) for offset in range(4)]
    kinds = ["prerequisite", "contains", "related", "cooccurs"]
    edges = [{"id": f"e{i}", "source": f"n{i % 500}", "target": f"n{(i + 1 + i // 500) % 500}",
              "type": kinds[i % 4], "evidence": []} for i in range(1393)]
    graph = {"id": job["id"], "title": job["title"], "page_kind": "section", "nodes": nodes,
             "edges": edges, "hierarchy": {"nodes": [root, *chapters, *sections], "memberships": members}}
    atomic_json(store.directory(job["id"]) / "graph.json", graph)
    job = store.update(job["id"], status="extracting", stats=job["stats"] | {
        "pages": 41, "parsed_pages": 41, "nodes": 500, "edges": 1393})
    return job, graph


def run_case(browser, base, job, graph, source, *, check):
    page = browser.new_page(viewport={"width": 1440, "height": 900})
    errors, counts = [], {"job": 0, "graph": 0}
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.route("**/static/network-view.js?*", lambda route: route.fulfill(body=RENDERER, content_type="text/javascript"))
    hooks = "window.__documentTest={render,visibleData,documentMenu};\n"
    instrumented = source.rsplit("})();", 1)[0] + hooks + "})();"
    page.route("**/static/documents.js?*", lambda route: route.fulfill(body=instrumented, content_type="text/javascript"))

    def current_job(route):
        counts["job"] += 1
        route.fulfill(json=job | {"progress": {"current": counts["job"], "total": 100}})

    def current_graph(route):
        counts["graph"] += 1
        route.fulfill(json=graph)

    page.route(f"**/api/documents/{job['id']}", current_job)
    page.route(f"**/api/documents/{job['id']}/graph", current_graph)
    page.goto(f"{base}/documents?id={job['id']}")
    page.wait_for_function("window.__network?.data?.nodes.length===601")
    assert page.evaluate("__network.data.edges.length") == 3493
    page.locator("#filtersButton").click()
    expect(page.locator("#nodeList button")).to_have_count(601)
    timings = page.evaluate("""async () => {
      const query=document.querySelector('#search'), relation=document.querySelector('#relationFilter');
      const result={unchanged:[],relation:[],search:[]};
      for(let i=0;i<15;i++){
        let start=performance.now();await __documentTest.render();result.unchanged.push(performance.now()-start);
        relation.value=i%2?'all':'contains';start=performance.now();await __documentTest.render();result.relation.push(performance.now()-start);
        query.value=i%2?'':'知识点 000';start=performance.now();await __documentTest.render();result.search.push(performance.now()-start);
        query.value='';relation.value='all';await __documentTest.render();
      }
      return result;
    }""")
    summary = {name: {"median_ms": round(statistics.median(values), 3), "max_ms": round(max(values), 3)}
               for name, values in timings.items()}
    if check:
        before = page.evaluate("structuredClone(__documentMetrics)")
        page.evaluate("""async()=>{await __documentTest.render();document.querySelector('#relationFilter').value='contains';await __documentTest.render();}""")
        after = page.evaluate("structuredClone(__documentMetrics)")
        assert after["listWrites"] == before["listWrites"], "Unchanged node lists must retain their DOM"
        assert after["legendWrites"] == before["legendWrites"], "Filters must retain the full-source family legend"
        assert len(after["draws"]) == len(before["draws"]) + 1
        expected_edges = {e["id"] for e in graph["edges"] if e["type"] == "contains"}
        actual_edges = set(page.evaluate("__network.data.edges.filter(e=>e.data.type!=='structure').map(e=>e.id)"))
        assert actual_edges == expected_edges
        page.evaluate("""async()=>{document.querySelector('#relationFilter').value='all';document.querySelector('#search').value='知识点 0499';await __documentTest.render();}""")
        assert page.evaluate("__network.data.nodes.filter(n=>n.data.kind==='concept').map(n=>n.id)") == ["n499"]
        page.locator('#nodeList [data-node="n499"]').click()
        expect(page.locator("#sourceTitle")).to_have_text("知识点 0499")
        expect(page.locator("#sourceContent .source-quote")).to_have_count(1)
        assert page.locator("#sourceContent a").first.get_attribute("href").endswith("#page=8")
        page.locator("#closeSource").click()
        page.evaluate("""async()=>{
          document.querySelector('#search').value='';await __documentTest.render();
          __documentTest.documentMenu('root',{});
        }""")
        assert page.evaluate("__menu.items[1].label") == "收起下级（600）"
        page.evaluate("async()=>{__menu.items[1].action();await __documentTest.render();}")
        assert page.evaluate("__network.data.nodes.map(n=>n.id)") == ["root"]
        page.evaluate("async()=>{__documentTest.documentMenu('root',{});__menu.items[1].action();await __documentTest.render();}")
        assert page.evaluate("__network.data.nodes.length") == 601
        assert page.evaluate("__network.data.edges.length") == 3493
        # A slow renderer must see the current filter after a burst, without a
        # queue entry for every intermediate input state.
        burst = page.evaluate("""async()=>{
          __network.delay=40;const before=__documentMetrics.draws.length,pending=[];
          for(const value of ['知识点 000','知识点 001','知识点 002','知识点 003','']){
            document.querySelector('#search').value=value;pending.push(__documentTest.render());
          }
          await Promise.all(pending);__network.delay=0;
          return {draws:__documentMetrics.draws.length-before,nodes:__network.data.nodes.length};
        }""")
        assert burst == {"draws": 2, "nodes": 601}, burst
        before = page.evaluate("structuredClone(__documentMetrics)")
        graph_reads, job_reads = counts["graph"], counts["job"]
        page.wait_for_timeout(4300)
        assert counts["job"] >= job_reads + 2
        assert counts["graph"] == graph_reads == 1
        assert page.evaluate("structuredClone(__documentMetrics)") == before
        summary["retained_nodes"] = 601
        summary["retained_edges"] = 3493
        summary["poll_graph_reads"] = counts["graph"]
        summary["filter_burst_draws"] = burst["draws"]
    assert not errors, errors
    page.close()
    return summary


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline", type=Path)
    args = parser.parse_args()
    report = {"synthetic_only": True, "scope": "documents.js preparation and DOM; renderer is recorded"}
    with tempfile.TemporaryDirectory(prefix="documents-perf-") as temporary:
        with isolated_application(Path(temporary)) as (base, course, documents), sync_playwright() as playwright:
            original = course.load_graph("draft")
            job, graph = synthetic_document(documents)
            browser = playwright.chromium.launch()
            try:
                if args.baseline:
                    report["before"] = run_case(browser, base, job, graph, args.baseline.read_text(encoding="utf-8"), check=False)
                report["after"] = run_case(browser, base, job, graph, (ROOT / "static/documents.js").read_text(encoding="utf-8"), check=True)
                assert documents.graph(job["id"]) == graph
                assert course.load_graph("draft") == original
            finally:
                browser.close()
    report["passed"] = True
    OUTPUT.mkdir(parents=True, exist_ok=True)
    (OUTPUT / "documents-performance-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
