"""Chapter projections tested with the checked-in computer organization scan."""
import hashlib
import json
import tempfile
from pathlib import Path

from playwright.sync_api import expect, sync_playwright
from test_ui_documents import isolated_application

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "outputs/verification"


def descendants(graph, ident):
    containers, pending = set(), [ident]
    while pending:
        current = pending.pop()
        if current in containers:
            continue
        containers.add(current)
        pending.extend(n["id"] for n in graph["hierarchy"]["nodes"] if n.get("parent_id") == current)
    concepts = {m["target"] for m in graph["hierarchy"]["memberships"] if m["source"] in containers}
    return containers, concepts


def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    manifest = json.loads((ROOT / "datasets/stress/manifest.json").read_text(encoding="utf-8"))["samples"][0]
    raw = (ROOT / "datasets/stress" / manifest["file"]).read_bytes()
    graph = json.loads(raw)
    job = manifest["job"] | {"status": "completed"}
    report = {"sample_sha256": hashlib.sha256(raw).hexdigest(), "checks": [], "errors": [], "chapters": []}

    def passed(message):
        report["checks"].append(message)
        print("PASS", message, flush=True)

    try:
        with tempfile.TemporaryDirectory(prefix="pliac-subgraphs-") as temporary:
            with isolated_application(Path(temporary)) as (base, _store, _documents), sync_playwright() as p:
                browser = p.chromium.launch()
                page = browser.new_page(viewport={"width": 1440, "height": 1000})
                page.set_default_timeout(60000)
                page.on("pageerror", lambda error: report["errors"].append(str(error)))
                page.add_init_script("""Object.defineProperty(window,'NetworkView',{
                  get(){return this.__View},set(View){this.__View=class extends View{
                    constructor(...args){super(...args);window.__network=this;}};}});""")
                page.route(f"**/api/documents/{job['id']}", lambda route: route.fulfill(json=job))
                page.route(f"**/api/documents/{job['id']}/graph", lambda route: route.fulfill(json=graph))
                page.goto(f"{base}/documents?id={job['id']}")
                page.wait_for_function("window.__network?.data.nodes.length===727 && !__network.busy")
                original = page.evaluate("({positions:Object.fromEntries(__network.graph.getNodeData().map(n=>[n.id,__network.graph.getElementPosition(n.id)])),colors:Object.fromEntries(__network.data.nodes.map(n=>[n.id,n.style.fill])),zoom:__network.graph.getZoom(),origin:__network.graph.getViewportByCanvas([0,0])})")
                page.locator("#chaptersButton").click()
                expect(page.locator("#subgraphList > .subgraph-branch")).to_have_count(6)
                expect(page.locator("#subgraphList")).to_contain_text("第4章 处理器")
                passed("The real book exposes its six chapters and nested section lists")

                root = next(n["id"] for n in graph["hierarchy"]["nodes"] if not n.get("parent_id"))
                chapters = [n for n in graph["hierarchy"]["nodes"] if n.get("parent_id") == root]

                def verify_scope(ident):
                    containers, concepts = descendants(graph, ident)
                    page.wait_for_function("id=>document.querySelector('[data-subgraph=\"'+id+'\"]')?.getAttribute('aria-pressed')==='true'", arg=ident)
                    page.wait_for_function("ids=>{const n=window.__network;return !n.busy&&n.data.nodes.length===ids.length&&n.data.nodes.every(x=>ids.includes(x.id))}", arg=list(containers | concepts))
                    page.evaluate("async()=>{await __network.operations;}")
                    data = page.evaluate("__network.data")
                    assert set(n["id"] for n in data["nodes"]) == containers | concepts
                    assert all(e["source"] in containers | concepts and e["target"] in containers | concepts for e in data["edges"])
                    expected_edges = {e["id"] for e in graph["edges"] if e["source"] in concepts and e["target"] in concepts}
                    assert {e["id"] for e in data["edges"] if e["data"]["type"] != "structure"} == expected_edges
                    assert all(n["style"]["fill"] == original["colors"][n["id"]] for n in data["nodes"])
                    return containers, concepts

                for chapter in chapters:
                    page.locator(f'[data-subgraph="{chapter["id"]}"]').click()
                    containers, concepts = verify_scope(chapter["id"])
                    report["chapters"].append({"title": chapter["title"], "structure_nodes": len(containers), "concepts": len(concepts)})
                passed("Every chapter has exactly its descendants, shared concepts and internal relations; colors stay stable")
                page.locator('[data-subgraph="section_128"]').click()
                containers, concepts = verify_scope("section_128")
                positions = page.evaluate("Object.fromEntries(__network.graph.getNodeData().map(n=>[n.id,__network.graph.getElementPosition(n.id)]))")
                assert all(pos == original["positions"][ident] for ident, pos in positions.items())
                with page.expect_download() as download:
                    page.locator("#exportButton").click()
                exported = json.loads(Path(download.value.path()).read_text(encoding="utf-8"))
                assert {n["id"] for n in exported["nodes"]} == concepts
                assert {n["id"] for n in exported["hierarchy"]["nodes"]} == containers
                assert next(n for n in exported["hierarchy"]["nodes"] if n["id"] == "section_128")["parent_id"] is None
                assert exported["subgraph"]["source_document_id"] == job["id"]
                page.screenshot(path=str(OUTPUT / "computer-organization-chapter.png"), full_page=True)
                passed("Subgraph export retains source IDs and evidence, with the selected chapter as root")
                page.locator("#wholeGraphButton").click()
                page.wait_for_function("__network.data.nodes.length===727 && !__network.busy")
                page.evaluate("async()=>{await __network.operations;}")
                restored = page.evaluate("({positions:Object.fromEntries(__network.graph.getNodeData().map(n=>[n.id,__network.graph.getElementPosition(n.id)])),zoom:__network.graph.getZoom(),origin:__network.graph.getViewportByCanvas([0,0])})")
                assert restored["positions"] == original["positions"]
                assert abs(restored["zoom"] - original["zoom"]) < 1e-6
                assert all(abs(a - b) < 1e-6 for a, b in zip(restored["origin"], original["origin"]))
                passed("Returning to the whole graph restores positions and camera")

                page.locator('[data-subgraph="section_128"]').click()
                verify_scope("section_128")
                section = next(n for n in graph["hierarchy"]["nodes"] if n.get("parent_id") == "section_128")
                page.locator('[data-subgraph="section_128"]').locator('..').locator(':scope > details > summary').click()
                page.locator(f'[data-subgraph="{section["id"]}"]').click()
                verify_scope(section["id"])
                assert "chapter=" + section["id"] in page.url
                page.reload()
                verify_scope(section["id"])
                passed("Section selection and refresh restore the selected subgraph")
                page.locator("#filtersButton").click()
                page.locator("#search").fill("no-matching-concept-xyz")
                page.wait_for_function("__network.data.nodes.length===0")
                expect(page.locator("#wholeGraphButton")).to_be_visible()
                page.locator("#wholeGraphButton").click()
                page.wait_for_function("__network.data.nodes.length===727 && !__network.busy")
                passed("Empty search retains whole-graph recovery")

                page.set_viewport_size({"width": 390, "height": 844})
                page.locator("#themeButton").click()
                page.locator("#chaptersButton").click()
                page.wait_for_function("document.getAnimations().every(a=>a.playState!=='running')")
                page.screenshot(path=str(OUTPUT / "computer-organization-chapters-mobile.png"), full_page=True)
                page.locator('[data-subgraph="section_173"]').click()
                verify_scope("section_173")
                expect(page.locator("#chaptersPanel")).to_be_hidden()
                assert page.evaluate("document.documentElement.scrollWidth<=innerWidth")
                passed("Mobile dark-theme chapter list switches graphs and closes after selection")
                assert not report["errors"], report["errors"]
                assert hashlib.sha256((ROOT / "datasets/stress" / manifest["file"]).read_bytes()).hexdigest() == report["sample_sha256"]
                browser.close()
    finally:
        (OUTPUT / "document-subgraphs-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
