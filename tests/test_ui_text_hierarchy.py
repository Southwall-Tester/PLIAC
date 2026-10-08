"""Legacy text-page projection in real Chromium, using synthetic temporary stores."""
from pathlib import Path
import json
import tempfile
import traceback

import httpx
from playwright.sync_api import expect, sync_playwright

from test_ui_documents import isolated_application
from learning_agent.documents import atomic_json

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "outputs" / "verification"


def legacy_document(store, real_chapter=False):
    """Saved pre-migration graph; no extraction worker or model is started."""
    job = store.create("synthetic-chapter.md" if real_chapter else "synthetic-legacy.md")
    ident = job["id"]
    text = "实体表示对象。\n" + ("\n## 真实章节\n" if real_chapter else "") + "关系连接实体。"
    store.source(ident).write_text(text, encoding="utf-8")
    page = {"page": 1, "text": text, "ocr": False}
    atomic_json(store.directory(ident) / "pages/1.json", page)

    def evidence(quote):
        start = text.index(quote)
        return [{"page": 1, "start": start, "end": start + len(quote), "quote": quote}]

    nodes = [{"id": "entity", "title": "实体", "description": "表示对象。",
              "evidence": evidence("实体表示对象。"), "review_status": "draft", "origin": "local"},
             {"id": "relation", "title": "关系", "description": "连接实体。",
              "evidence": evidence("关系连接实体。"), "review_status": "draft", "origin": "local"}]
    hierarchy = {"nodes": [
        {"id": "book_root", "title": job["title"], "parent_id": None, "kind": "book", "page": 1, "level": 0},
        {"id": "page_1", "title": "第 1 段", "parent_id": "book_root", "kind": "page", "page": 1, "level": 1},
    ], "memberships": [{"source": "page_1", "target": "entity"},
                        {"source": "real_chapter" if real_chapter else "page_1", "target": "relation"}]}
    if real_chapter:
        hierarchy["nodes"].append({"id": "real_chapter", "title": "真实章节", "parent_id": "book_root",
                                   "kind": "chapter", "page": 1, "level": 1, "start": text.index("##")})
    graph = {"id": ident, "title": job["title"], "engine": "local", "page_kind": "section",
             "nodes": nodes, "edges": [{"id": "edge_1", "source": "entity", "target": "relation",
                                        "type": "cooccurs", "reason": "原文中共同出现。", "evidence": evidence(text),
                                        "review_status": "draft", "origin": "local"}],
             "hierarchy": hierarchy, "review_status": "draft", "source_url": f"/api/documents/{ident}/source"}
    atomic_json(store.directory(ident) / "graph.json", graph)
    store.update(ident, status="completed", stats=job["stats"] | {"pages": 1, "parsed_pages": 1,
                                                                  "chunks": 1, "nodes": 2, "edges": 1})
    paths = [store.source(ident), store.directory(ident) / "graph.json", store.directory(ident) / "pages/1.json"]
    return ident, graph, page, {path: path.read_bytes() for path in paths}


def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    report = {"synthetic_only": True, "temporary_stores": True, "checks": [], "page_errors": []}
    try:
        with tempfile.TemporaryDirectory(prefix="text-hierarchy-ui-") as temporary:
            with isolated_application(Path(temporary)) as (base, seed, documents):
                original_seed = seed.load_graph("draft")
                with httpx.Client(base_url=base, timeout=15) as client, sync_playwright() as playwright:
                    browser = playwright.chromium.launch()
                    page = browser.new_page(viewport={"width": 1440, "height": 900})
                    page.on("pageerror", lambda error: report["page_errors"].append(str(error)))
                    page.add_init_script("""Object.defineProperty(window,'NetworkView',{
                      get(){return this.__View},set(View){this.__View=class extends View{
                        constructor(...args){super(...args);window.__network=this;}
                      }}});""")
                    for real_chapter in (False, True):
                        ident, graph, source_page, snapshots = legacy_document(documents, real_chapter)
                        expected_count = 4 if real_chapter else 3
                        page.goto(f"{base}/documents?id={ident}")
                        page.wait_for_function("count=>window.__network?.data?.nodes.length===count && !__network.busy", arg=expected_count)
                        shown = page.evaluate("__network.data")
                        assert all(node["id"] != "page_1" for node in shown["nodes"])
                        # Both fixtures contain one family. Its mother, wrappers,
                        # section and concepts differ by size, never by hue.
                        assert len({node["style"]["fill"] for node in shown["nodes"]}) == 1
                        assert len({node["data"]["family_id"] for node in shown["nodes"]}) == 1
                        assert shown["nodes"][0]["data"]["family_id"] is not None
                        pairs = {(edge["source"], edge["target"]) for edge in shown["edges"]}
                        assert ("book_root", "entity") in pairs
                        assert (("real_chapter" if real_chapter else "book_root"), "relation") in pairs
                        if real_chapter:
                            assert ("book_root", "real_chapter") in pairs
                            assert any(node["id"] == "real_chapter" and node["data"]["title"] == "真实章节" for node in shown["nodes"])
                        page.screenshot(path=str(OUTPUT / f"text-hierarchy-{'chapter' if real_chapter else 'legacy'}-document.png"))

                        created = client.post("/api/courses", json={"title": "合成层级课程"}).json()
                        course_id = created["course"]["id"]
                        imported = client.post(f"/api/documents/{ident}/import",
                                               json={"course_id": course_id, "expected_version": 1})
                        imported.raise_for_status()
                        draft = imported.json()["graph"]
                        imported_ids = {node["title"]: node["id"] for node in draft["nodes"]}
                        chapter_id = "doc_" + ident
                        page.goto(f"{base}/author?course_id={course_id}")
                        page.wait_for_function("() => window.__network?.data?.nodes.some(n=>n.data.kind==='concept') && !__network.busy")
                        shown = page.evaluate("__network.data")
                        assert all(not node["id"].endswith("page_1") for node in shown["nodes"])
                        family_nodes = [node for node in shown["nodes"] if node["data"].get("family_id") == chapter_id]
                        assert len({node["style"]["fill"] for node in family_nodes}) == 1
                        assert next(node for node in shown["nodes"] if node["id"] == "course_root")["data"]["family_id"] is None
                        pairs = {(edge["source"], edge["target"]) for edge in shown["edges"]}
                        document_chapter = "chapter_" + chapter_id
                        assert ("course_root", document_chapter) in pairs
                        assert (document_chapter, imported_ids["实体"]) in pairs
                        owner = f"section_{chapter_id}_real_chapter" if real_chapter else document_chapter
                        assert (owner, imported_ids["关系"]) in pairs
                        if real_chapter:
                            assert (document_chapter, owner) in pairs
                        for selected_id, label in (("course_root", "课程"), (document_chapter, "章节"),
                                                   (owner, "章节"), (imported_ids["实体"], "知识点")):
                            page.evaluate("id=>__network.graph.emit('node:click',{target:{id}})", selected_id)
                            expect(page.locator(".detail-pane .drawer-head strong")).to_have_text(label)
                        page.locator("#closeDetail").click()
                        for node in draft["nodes"]:
                            original = next(item for item in graph["nodes"] if item["title"] == node["title"])
                            assert node["document_evidence"] == original["evidence"]
                        assert client.get(f"/api/documents/{ident}/pages/1").json() == source_page
                        assert all(path.read_bytes() == value for path, value in snapshots.items())
                        page.screenshot(path=str(OUTPUT / f"text-hierarchy-{'chapter' if real_chapter else 'legacy'}-course.png"))
                        report["checks"].append("Real chapters survive text-section projection in document and course views" if real_chapter else
                                                "Legacy text pages collapse to direct concept membership in document and course views")
                    assert seed.load_graph("draft") == original_seed
                    assert not report["page_errors"], report["page_errors"]
                    report["checks"].append("Source files, saved legacy graph, page slices and imported evidence remain unchanged; seed course is preserved")
                    report["checks"].append("Course detail headers distinguish course roots, imported chapters and knowledge points")
                    browser.close()
        report["passed"] = True
    except Exception:
        report["failure"] = traceback.format_exc()
        raise
    finally:
        (OUTPUT / "text-hierarchy-ui-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
