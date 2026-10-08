"""Real Chromium checks for book upload, hierarchy, sources and draft import.

Run as a script. Importing this module does not start a browser or server.
Source documents and both stores live in a temporary directory; only screenshots
and a verification report remain under outputs/verification.
"""
from __future__ import annotations

import json
import re
import socket
import sys
import tempfile
import threading
import time
import traceback
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

import httpx
import uvicorn
from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from learning_agent import api, document_api
from learning_agent.course_graph import CourseGraphStore
from learning_agent.documents import DocumentStore
from learning_agent.main import app

OUTPUT = ROOT / "outputs" / "verification"
SOURCE = """# 知识图谱

知识图谱是指通过图结构组织实体、关系与属性的知识库。
知识图谱包括实体、关系和属性。

## 实体识别

实体识别是指从文本中提取人物、组织和地点的任务。
实体识别包含序列标注。

## 关系抽取

关系抽取是指提取实体之间语义关系的过程。
关系抽取包含实体对识别与关系分类。
"""


def expect_controls(page, *, visible=(), hidden=()):
    for selector in visible:
        expect(page.locator(selector)).to_be_visible()
    for selector in hidden:
        expect(page.locator(selector)).to_be_hidden()


def assert_neutral_toolbar(page):
    page.mouse.move(0, page.viewport_size["height"] - 1)
    page.wait_for_function("document.querySelector('.toolbar').getAnimations({subtree:true}).every(animation=>animation.playState!=='running')")
    styles = page.locator(".toolbar button:visible, .toolbar select:visible").evaluate_all("""elements => elements.map(element => {
        const style=getComputedStyle(element);
        return [style.color,style.backgroundColor,style.borderTopColor];
    })""")
    assert styles and all(style == styles[0] for style in styles), styles
    for color in styles[0]:
        channels = [int(n) for n in re.findall(r"\d+", color)[:3]]
        assert max(channels) - min(channels) <= 18, color
    assert page.locator(".toolbar a:visible").evaluate_all(
        "(links,color)=>links.every(link=>getComputedStyle(link).color===color)", styles[0][0])


def assert_surface_theme(page, selectors, *, dark):
    for selector in selectors:
        surface = page.locator(selector).first
        expect(surface).to_be_visible()
        color = surface.evaluate("""element => {
            for (let current=element; current; current=current.parentElement) {
                const color=getComputedStyle(current).backgroundColor;
                const channels=color.match(/[\\d.]+/g)?.map(Number);
                if (channels && (channels.length===3 || channels[3]>=.9)) return channels.slice(0,3);
            }
            return [255,255,255];
        }""")
        assert (max(color) <= 95 if dark else min(color) >= 220), (selector, color, dark)


def assert_left_toolbar(page):
    controls = page.locator(".toolbar button:not(#themeButton):visible, .toolbar a:visible, .toolbar select:visible, .toolbar .active-course-title:visible").evaluate_all("""elements => elements.map(element => {
        const r=element.getBoundingClientRect(); return {x:r.x,right:r.right,center:r.y+r.height/2};
    })""")
    rows = []
    for control in sorted(controls, key=lambda item: item["center"]):
        if not rows or abs(rows[-1][0]["center"] - control["center"]) > 12:
            rows.append([])
        rows[-1].append(control)
    assert rows
    for row in rows:
        row.sort(key=lambda item: item["x"])
        assert row[0]["x"] <= 16, row
        assert all(-1 <= right["x"] - left["right"] <= 28 for left, right in zip(row, row[1:])), row
        assert row[-1]["right"] <= page.viewport_size["width"], row
    theme = page.locator('#themeButton').bounding_box()
    assert 8 <= page.viewport_size['width'] - theme['x'] - theme['width'] <= 16
    assert theme['y'] <= 12
    assert page.locator('#themeButton').inner_text() == ''
    expect(page.locator('#themeButton svg')).to_be_visible()


@contextmanager
def isolated_application(directory):
    course = CourseGraphStore(output_dir=directory / "course")
    documents = DocumentStore(directory / "documents")
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    base = f"http://127.0.0.1:{port}"
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port,
                                         log_level="error", access_log=False))
    thread = threading.Thread(target=server.run, daemon=True)
    with patch.object(api, "store", course), patch.object(document_api, "document_store", documents):
        try:
            thread.start()
            with httpx.Client(base_url=base, timeout=2) as client:
                for _ in range(100):
                    try:
                        if client.get("/health").is_success:
                            break
                    except httpx.HTTPError:
                        pass
                    time.sleep(.1)
                else:
                    raise AssertionError("Temporary document UI server did not start")
            yield base, course, documents
        finally:
            server.should_exit = True
            if thread.is_alive():
                thread.join(timeout=10)
            if thread.is_alive():
                server.force_exit = True
                thread.join(timeout=5)
            # Wait for upload workers before the temporary directory is removed.
            documents.executor.shutdown(wait=True, cancel_futures=True)


def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    report = {"synthetic_only": True, "persistent_course_store_used": False,
              "persistent_document_store_used": False, "checks": [],
              "page_errors": [], "screenshots": []}

    def passed(name):
        report["checks"].append(name)
        print("PASS", name, flush=True)

    try:
        with tempfile.TemporaryDirectory(prefix="documents-ui-synthetic-") as temporary:
            directory = Path(temporary)
            source = directory / "知识图谱测试.md"
            source.write_text(SOURCE, encoding="utf-8")
            with isolated_application(directory) as (base, course, documents):
                initial_ids = {n["id"] for n in course.load_graph("draft")["nodes"]}
                with sync_playwright() as playwright:
                    browser = playwright.chromium.launch()
                    try:
                        page = browser.new_page(viewport={"width": 1440, "height": 900})
                        page.on("pageerror", lambda error: report["page_errors"].append(str(error)))
                        page.goto(base + "/documents")
                        expect(page.locator("#libraryPanel")).to_be_visible()
                        expect_controls(page, visible=("#themeButton", '#coursesLink'), hidden=(
                            "#physicsSettings", "#stabilizeButton", "#filtersButton", "#labelsButton",
                            "#statsButton", "#hierarchyLevel", "#importButton", "#exportButton", "#canvasControls"))
                        assert_left_toolbar(page)
                        page.locator("#themeButton").click()
                        expect(page.locator("body")).to_have_class(re.compile(r"network-dark"))
                        expect(page.locator("html")).to_have_class(re.compile(r"network-dark"))
                        assert page.evaluate("localStorage.getItem('pliac-theme')") == "dark"
                        page.locator(".upload-options summary").click()
                        dark_library = ("html", "body", "main", "#libraryPanel", "#dropZone",
                                        ".choose-file", "#startPage", "#endPage", "#engine")
                        assert_surface_theme(page, dark_library, dark=True)
                        page.screenshot(path=str(OUTPUT / "documents-library-dark.png"))
                        report["screenshots"].append("documents-library-dark.png")
                        page.set_viewport_size({"width": 390, "height": 844})
                        assert_left_toolbar(page)
                        assert_surface_theme(page, dark_library, dark=True)
                        page.screenshot(path=str(OUTPUT / "documents-library-dark-mobile.png"))
                        report["screenshots"].append("documents-library-dark-mobile.png")
                        page.set_viewport_size({"width": 1440, "height": 900})
                        page.reload()
                        expect(page.locator("html")).to_have_class(re.compile(r"network-dark"))
                        expect(page.locator("body")).to_have_class(re.compile(r"network-dark"))
                        assert_surface_theme(page, ("html", "body", "main", "#libraryPanel", "#dropZone"), dark=True)
                        page.locator('#coursesLink').click()
                        expect(page.locator('#courseList')).to_be_visible()
                        expect(page.locator('body')).to_have_class(re.compile(r'network-dark'))
                        page.locator('.edit-course').first.click()
                        expect(page.locator("#importDocuments")).to_be_visible()
                        expect(page.locator("html")).to_have_class(re.compile(r"network-dark"))
                        expect(page.locator("body")).to_have_class(re.compile(r"network-dark"))
                        page.locator("#importDocuments").click()
                        expect(page.locator("#libraryPanel")).to_be_visible()
                        expect(page.locator("body")).to_have_class(re.compile(r"network-dark"))
                        page.locator("#themeButton").click()
                        expect(page.locator("html")).not_to_have_class(re.compile(r"network-dark"))
                        expect(page.locator("body")).not_to_have_class(re.compile(r"network-dark"))
                        assert page.evaluate("localStorage.getItem('pliac-theme')") == "light"
                        assert_surface_theme(page, ("html", "body", "main", "#libraryPanel", "#dropZone"), dark=False)
                        passed("Dark library covers the page, upload panel and settings; theme survives reload and course navigation, then restores light")
                        passed("Empty library offers theme and course navigation without graph-specific actions")

                        generating = browser.new_page(viewport={"width": 1440, "height": 900})
                        generating.on("pageerror", lambda error: report["page_errors"].append(str(error)))
                        generating.route("**/api/documents/toolbar-generating-fixture", lambda route: route.fulfill(json={
                            "id": "toolbar-generating-fixture", "title": "Toolbar processing fixture",
                            "status": "parsing", "progress": {"current": 1, "total": 5},
                            "stats": {"nodes": 0, "edges": 0}, "warnings": [], "error": None,
                        }))
                        generating.goto(base + "/documents?id=toolbar-generating-fixture")
                        expect(generating.locator("#jobStatus")).to_contain_text("解析中")
                        expect_controls(generating, visible=("#themeButton", "#libraryButton", "#cancelButton"), hidden=(
                            "#physicsSettings", "#stabilizeButton", "#filtersButton", "#labelsButton",
                            "#statsButton", "#hierarchyLevel", "#importButton", "#exportButton", "#canvasControls"))
                        generating.close()
                        passed("A document still processing without graph data offers task actions and hides graph tools")

                        page.evaluate("""() => {
                            const Graph = window.PIXI && window.CoursePixiGraph ? CoursePixiGraph : G6.Graph;
                            const original = Graph.prototype.setData;
                            Graph.prototype.setData = function(data) {
                                window.lastGraphData = data;
                                window.testGraph = this;
                                return original.call(this, data);
                            };
                        }""")
                        page.locator("#fileInput").set_input_files(str(source))
                        expect(page.locator("#importButton")).to_be_enabled(timeout=45000)
                        expect(page.locator("#libraryPanel")).to_be_hidden()
                        ident = parse_qs(urlparse(page.url).query)["id"][0]
                        data = page.evaluate("window.lastGraphData")
                        assert len(data["nodes"]) > 5 and len(data["edges"]) > 2
                        assert any(n["style"].get("lineWidth") == 2 for n in data["nodes"])
                        assert_neutral_toolbar(page)
                        assert_left_toolbar(page)
                        page.set_viewport_size({"width": 390, "height": 844})
                        assert_left_toolbar(page)
                        page.set_viewport_size({"width": 1440, "height": 900})
                        passed("Document toolbar actions flow from the left on desktop and mobile, with and without graph tools")
                        page.locator("#themeButton").click()
                        expect(page.locator("body")).to_have_class(re.compile(r"network-dark"))
                        assert_neutral_toolbar(page)
                        page.locator("#themeButton").click()
                        passed("Upload automatically renders a hierarchical graph with semantic edges")

                        page.locator("#libraryButton").click()
                        expect(page.locator("#libraryPanel")).to_be_visible()
                        expect_controls(page, visible=("#themeButton", "#closeLibrary"), hidden=(
                            "#physicsSettings", "#stabilizeButton", "#filtersButton", "#labelsButton",
                            "#statsButton", "#hierarchyLevel", "#importButton", "#exportButton", "#canvasControls"))
                        page.locator("#closeLibrary").click()
                        expect(page.locator("#libraryPanel")).to_be_hidden()
                        expect_controls(page, visible=("#physicsSettings", "#stabilizeButton", "#filtersButton",
                            "#labelsButton", "#statsButton", "#hierarchyLevel", "#importButton", "#exportButton", "#canvasControls"))
                        passed("Opening the library hides graph tools; returning restores them, with neutral controls in both themes")

                        extracted = documents.graph(ident)
                        sections = {n["id"]: n["title"] for n in extracted["hierarchy"]["nodes"]}
                        for title, expected_section in [("人物", "实体识别"), ("关系分类", "关系抽取")]:
                            concept = next(n for n in extracted["nodes"] if n["title"] == title)
                            owners = {sections[m["source"]] for m in extracted["hierarchy"]["memberships"]
                                      if m["target"] == concept["id"]}
                            assert owners == {expected_section}, (title, owners)
                        assert documents.status(ident)["stats"]["pages"] == 1
                        passed("Concepts in two headings on the same page retain their correct chapter")

                        color_data = page.evaluate("""() => {
                            const normalized = color => {const context=document.createElement('canvas').getContext('2d');context.fillStyle=color;return context.fillStyle;};
                            return {nodes:window.testGraph.getNodeData().map(n=>({id:n.id,title:n.data.title,kind:n.data.kind,family:n.data.family_id,fill:normalized(n.style.fill),size:n.style.size})),
                                legend:[...document.querySelectorAll('#colorLegend [data-family]')].map(item=>({id:item.dataset.family,fill:normalized(item.querySelector('i').style.backgroundColor)}))};
                        }""")
                        person = next(n for n in color_data["nodes"] if n["kind"] == "concept" and n["title"] == "人物")
                        place = next(n for n in color_data["nodes"] if n["kind"] == "concept" and n["title"] == "地点")
                        relation = next(n for n in color_data["nodes"] if n["kind"] == "concept" and n["title"] == "关系分类")
                        assert person["family"] == place["family"] and person["fill"] == place["fill"]
                        assert person["family"] != relation["family"] and person["fill"] != relation["fill"]
                        assert all(n["size"] == 12 for n in color_data["nodes"] if n["kind"] == "concept")
                        assert next(n["size"] for n in color_data["nodes"] if n["kind"] == "book") == 42
                        legend = {item["id"]: item["fill"] for item in color_data["legend"]}
                        assert legend[person["family"]] == person["fill"]
                        assert legend[relation["family"]] == relation["fill"]
                        assert all(node["fill"] == legend[node["family"]] for node in color_data["nodes"] if node["family"] is not None)
                        book_root = next(node for node in color_data["nodes"] if node["kind"] == "book")
                        assert book_root["family"] is None and book_root["fill"] not in legend.values()
                        page.locator("#encodingLegend summary").click()
                        expect(page.locator("#colorLegend")).to_be_visible()
                        expect(page.locator("#colorLegend")).to_contain_text("实体识别")
                        expect(page.locator("#colorLegend")).to_contain_text("关系抽取")
                        page.locator("#encodingLegend summary").click()
                        original_colors = {n["id"]: n["fill"] for n in color_data["nodes"]}
                        passed("Book chapter families share stable colors with a matching legend and explicit level sizes")

                        page.locator("#stabilizeButton").click()
                        page.wait_for_timeout(350)
                        def geometry():
                            return page.evaluate("""() => ({
                                positions:Object.fromEntries(window.testGraph.getNodeData().map(n=>[n.id,window.testGraph.getElementPosition(n.id)])),
                                zoom:window.testGraph.getZoom(),origin:window.testGraph.getViewportByCanvas([0,0])
                            })""")

                        for kind in ("book", "chapter", "concept"):
                            click_target = page.evaluate("""kind => {
                                const g=window.testGraph,n=g.getNodeData().find(n=>n.data.kind===kind);
                                const p=g.getViewportByCanvas(g.getElementPosition(n.id));
                                const rect=document.querySelector('#graph').getBoundingClientRect();
                                return {id:n.id,title:n.data.title,x:p[0]+rect.x,y:p[1]+rect.y};
                            }""", kind)
                            before_click = geometry()
                            page.mouse.click(click_target["x"], click_target["y"])
                            expect(page.locator("#sourcePanel")).to_be_visible()
                            expect(page.locator("#sourceTitle")).to_have_text(click_target["title"])
                            expect(page.locator("#sourceContent .source-type")).to_have_text(
                                {"book": "资料", "chapter": "章节", "concept": "知识点"}[kind])
                            assert geometry() == before_click
                            assert page.evaluate("window.testGraph.getNodeData().length") == len(data["nodes"])
                            page.locator("#closeSource").click()
                        passed("Book, chapter and concept clicks show their node type without moving nodes or changing the viewport")

                        book_target = page.evaluate("""() => {
                            const g=window.testGraph,n=g.getNodeData().find(n=>n.data.kind==='book');
                            const p=g.getViewportByCanvas(g.getElementPosition(n.id));
                            const rect=document.querySelector('#graph').getBoundingClientRect();
                            return {id:n.id,x:p[0]+rect.x,y:p[1]+rect.y};
                        }""")
                        before_menu = geometry()
                        page.mouse.click(book_target["x"],book_target["y"],button="right")
                        expect(page.locator("#graphContextMenu")).to_be_visible()
                        page.get_by_role("menuitem",name=re.compile(r"^收起下级")).click()
                        page.wait_for_function("window.testGraph.getNodeData().length===1")
                        expect_controls(page, visible=("#filtersButton", "#labelsButton"),
                                        hidden=("#physicsSettings", "#stabilizeButton"))
                        collapsed_geometry = geometry()
                        assert collapsed_geometry["zoom"] == before_menu["zoom"]
                        assert collapsed_geometry["origin"] == before_menu["origin"]
                        assert collapsed_geometry["positions"][book_target["id"]] == before_menu["positions"][book_target["id"]]
                        page.mouse.click(book_target["x"],book_target["y"],button="right")
                        page.get_by_role("menuitem",name=re.compile(r"^展开下级")).click()
                        page.wait_for_function("count=>window.testGraph.getNodeData().length===count",arg=len(data["nodes"]))
                        assert geometry() == before_menu
                        expect(page.locator("#toggleBranch")).to_have_count(0)
                        passed("Book right-click menu collapses and expands its hierarchy while preserving coordinates and viewport")

                        # A shared concept remains visible when a different
                        # chapter that owns it is still expanded. Semantic edges
                        # never determine the scope of a directory collapse.
                        hierarchy_nodes = extracted["hierarchy"]["nodes"]
                        memberships = extracted["hierarchy"]["memberships"]
                        owners = {}
                        for member in memberships:
                            owners.setdefault(member["target"],set()).add(member["source"])
                        shared_id = next(node for node,parents in owners.items() if len(parents)>1)
                        family = page.evaluate("id=>window.testGraph.getNodeData(id).data", shared_id)
                        other_titles = [n["title"] for n in hierarchy_nodes
                                        if n["id"] in owners[shared_id] and n["id"] != family["family_id"]]
                        page.locator("#filtersButton").click()
                        page.locator(f'#nodeList [data-node="{shared_id}"]').click()
                        expect(page.locator("#sourceContent .source-type")).to_have_text("知识点")
                        expect(page.locator("#sourceContent .source-family")).to_have_text("所属族群：" + family["family_title"])
                        expect(page.locator("#sourceContent .source-occurrences")).to_have_text("出现于：" + "、".join(other_titles))
                        page.locator("#closeSource").click()
                        page.locator("#closeFilters").click()
                        passed("Shared concept details identify the displayed family and other source sections")
                        candidates = []
                        for chapter_node in hierarchy_nodes:
                            if chapter_node["kind"] != "chapter":
                                continue
                            subtree = {chapter_node["id"]}
                            while True:
                                expanded = subtree | {n["id"] for n in hierarchy_nodes if n.get("parent_id") in subtree}
                                if expanded == subtree:
                                    break
                                subtree = expanded
                            shared = {node for node,parents in owners.items() if parents & subtree and parents - subtree}
                            hidden = {node for node,parents in owners.items() if parents and parents <= subtree}
                            if shared and hidden:
                                candidates.append((chapter_node,subtree,shared,hidden))
                        assert candidates, "The source fixture must contain a concept shared across chapter boundaries"
                        chapter_node,subtree,shared,hidden = candidates[0]
                        branch_target = page.evaluate("""id => {
                            const g=window.testGraph,p=g.getViewportByCanvas(g.getElementPosition(id));
                            const rect=document.querySelector('#graph').getBoundingClientRect();
                            return {x:p[0]+rect.x,y:p[1]+rect.y};
                        }""",chapter_node["id"])
                        expected_ids = set(before_menu["positions"]) - (subtree - {chapter_node["id"]}) - hidden
                        page.mouse.click(branch_target["x"],branch_target["y"],button="right")
                        fold_item = page.get_by_role("menuitem",name=re.compile(r"^收起下级"))
                        fold_label = fold_item.inner_text()
                        assert int(re.search(r"（(\d+)）",fold_label).group(1)) == len(before_menu["positions"]) - len(expected_ids)
                        fold_item.click()
                        page.wait_for_function("count=>window.testGraph.getNodeData().length===count",arg=len(expected_ids))
                        remaining = set(page.evaluate("window.testGraph.getNodeData().map(n=>n.id)"))
                        assert remaining == expected_ids and shared <= remaining
                        remaining_geometry = geometry()
                        assert remaining_geometry["zoom"] == before_menu["zoom"] and remaining_geometry["origin"] == before_menu["origin"]
                        assert all(coords == before_menu["positions"][node] for node,coords in remaining_geometry["positions"].items())
                        page.mouse.click(branch_target["x"],branch_target["y"],button="right")
                        page.get_by_role("menuitem",name=re.compile(r"^展开下级")).click()
                        page.wait_for_function("count=>window.testGraph.getNodeData().length===count",arg=len(data["nodes"]))
                        assert geometry() == before_menu
                        passed("Chapter collapse affects its directory subtree, retains concepts shared with expanded chapters and reports the exact affected count")

                        point = page.evaluate("""() => {
                            const g = window.testGraph;
                            const n = g.getNodeData().find(n => n.style.size < 25);
                            const p = g.getViewportByCanvas(g.getElementPosition(n.id));
                            return {id: n.id, x: p[0], y: p[1]};
                        }""")
                        bounds = page.locator("#graph").bounding_box()
                        x, y = bounds["x"] + point["x"], bounds["y"] + point["y"]
                        page.mouse.move(x, y)
                        page.wait_for_function("window.testGraph.getNodeData().some(n => window.testGraph.getElementRenderStyle(n.id).opacity === .12)")
                        page.mouse.move(20, 100)
                        page.wait_for_function("!window.testGraph.getNodeData().some(n => window.testGraph.getElementRenderStyle(n.id).opacity === .12)")
                        page.mouse.move(x, y)
                        before = page.evaluate("id => window.testGraph.getElementPosition(id)", point["id"])
                        page.mouse.down()
                        page.mouse.move(x + 70, y + 40, steps=10)
                        page.mouse.up()
                        after = page.evaluate("id => window.testGraph.getElementPosition(id)", point["id"])
                        assert abs(after[0] - before[0]) > 10
                        before = page.evaluate("window.testGraph.getNodeData().map(n => [n.style.x, n.style.y])")
                        page.wait_for_timeout(350)
                        after = page.evaluate("window.testGraph.getNodeData().map(n => [n.style.x, n.style.y])")
                        assert before == after
                        page.locator("#physicsSettings").click()
                        page.locator("#repulsion").fill("10000")
                        page.locator('[data-close="physicsDialog"]').click()
                        page.locator("#stabilizeButton").click()
                        page.wait_for_timeout(350)
                        after = page.evaluate("window.testGraph.getNodeData().map(n => [n.style.x, n.style.y])")
                        assert before != after
                        before = page.evaluate("window.testGraph.getNodeData().map(n => [n.style.x, n.style.y])")
                        page.wait_for_timeout(350)
                        assert before == page.evaluate("window.testGraph.getNodeData().map(n => [n.style.x, n.style.y])")
                        passed("Hover and drag work; manual arrange updates the layout and then stays static")

                        page.locator("#filtersButton").click()
                        page.locator("#nodeList button").last.click()
                        expect(page.locator("#sourcePanel")).to_be_visible()
                        expect(page.locator("#sourceContent .source-quote")).not_to_have_count(0)
                        assert "/source#page=" in page.locator("#sourceContent a").first.get_attribute("href")
                        passed("Node selection opens original text and a source locator")
                        page.locator("#closeSource").click()
                        page.locator("#closeFilters").click()
                        page.screenshot(path=str(OUTPUT / "documents-network.png"))
                        report["screenshots"].append("documents-network.png")

                        full_count = len(data["nodes"])
                        page.locator("#hierarchyLevel").select_option("book")
                        page.wait_for_function("window.lastGraphData.nodes.length === 1")
                        expect_controls(page, visible=("#hierarchyLevel", "#labelsButton"),
                                        hidden=("#physicsSettings", "#stabilizeButton"))
                        page.locator("#hierarchyLevel").select_option("chapters")
                        page.wait_for_function("max => window.lastGraphData.nodes.length > 1 && window.lastGraphData.nodes.length < max", arg=full_count)
                        page.locator("#hierarchyLevel").select_option("all")
                        page.wait_for_function("count => window.lastGraphData.nodes.length === count", arg=full_count)
                        assert page.evaluate("expected => window.testGraph.getNodeData().every(n=>n.style.fill===expected[n.id])", original_colors)
                        passed("Book, chapter and all levels update graph topology")

                        page.locator("#filtersButton").click()
                        page.locator("#search").fill("__no_document_node_matches__")
                        page.wait_for_function("window.lastGraphData.nodes.length === 0")
                        expect_controls(page, visible=("#filtersButton", "#statsButton"), hidden=(
                            "#physicsSettings", "#stabilizeButton", "#labelsButton", "#canvasControls"))
                        page.locator("#search").fill("")
                        page.wait_for_function("count => window.lastGraphData.nodes.length === count", arg=full_count)
                        expect_controls(page, visible=("#physicsSettings", "#stabilizeButton", "#labelsButton", "#canvasControls"))
                        page.locator("#closeFilters").click()
                        passed("Empty search hides graph-only actions while its filters remain available to restore the graph")

                        page.locator("#themeButton").click()
                        page.locator("#importButton").click()
                        expect(page.locator("#confirmImport")).to_be_enabled()
                        assert_surface_theme(page, ("#importDialog", ".import-summary", ".import-summary label",
                                                    "#importNodes", "#importNodes label", ".dialog-actions"), dark=True)
                        assert page.locator("#selectAll").evaluate("el=>getComputedStyle(el).colorScheme") == "dark"
                        page.screenshot(path=str(OUTPUT / "documents-import-dark.png"))
                        report["screenshots"].append("documents-import-dark.png")
                        passed("Dark import dialog covers the selection list, select-all row and native checkbox")
                        draft = course.load_graph("draft")
                        draft["title"] = "Temporary version conflict"
                        course.save_graph(draft, draft["version"])
                        page.locator("#confirmImport").click()
                        expect(page.locator("#importError")).to_contain_text("已更新")
                        page.locator("#confirmImport").click()
                        expect(page.locator("#importDialog")).not_to_be_visible()
                        page.locator("#themeButton").click()
                        draft = course.load_graph("draft")
                        added = [n for n in draft["nodes"] if n.get("document_id") == ident]
                        assert added and all(n["review_status"] == "draft" for n in added)
                        assert all(n["id"] not in initial_ids for n in added)
                        assert course.publication()["published_version"] is None
                        passed("Draft import handles a version conflict and preserves draft status")

                        imported_ids = {n["id"] for n in added}
                        imported_chapter = next(c for c in draft["chapters"] if c["id"] == added[0]["chapter_id"])
                        imported_hierarchy = imported_chapter["document_hierarchy"]
                        assert imported_hierarchy["memberships"]
                        assert all(m["target"] in imported_ids for m in imported_hierarchy["memberships"])
                        document_url = page.url
                        page.goto(base + "/author")
                        expect(page.locator("#nodeCount")).to_have_text(str(len(draft["nodes"])))
                        page.locator("#filtersButton").click()
                        page.evaluate("""() => {
                            const Graph = window.PIXI && window.CoursePixiGraph ? CoursePixiGraph : G6.Graph;
                            const original = Graph.prototype.setData;
                            Graph.prototype.setData = function(data) {
                                window.importedCourseGraph = data;
                                return original.call(this, data);
                            };
                        }""")
                        page.locator("#levelFilter").select_option("root")
                        page.wait_for_function("window.importedCourseGraph?.nodes.length === 1")
                        page.locator("#levelFilter").select_option("concept")
                        page.wait_for_function("window.importedCourseGraph?.nodes.some(n => n.id.startsWith('section_'))")
                        course_render = page.evaluate("window.importedCourseGraph")
                        section_ids = {n["id"] for n in course_render["nodes"] if n["id"].startswith("section_")}
                        assert any(e["source"] in section_ids and e["target"] in section_ids for e in course_render["edges"])
                        assert any(e["source"] in section_ids and e["target"] in imported_ids for e in course_render["edges"])
                        selected = next(n for n in added if n["title"] == "人物")
                        page.locator(f'[data-node="{selected["id"]}"]').click()
                        proof = page.locator("#detailContent .document-proof")
                        expect(proof).to_be_visible()
                        expect(proof).to_contain_text(selected["document_evidence"][0]["quote"])
                        expect(proof).to_contain_text("正文段 1")
                        assert f"/api/documents/{ident}/source#page=1" in proof.locator("a").first.get_attribute("href")
                        passed("Imported course preserves nested book structure, mapped memberships and original text")

                        page.goto(document_url)
                        page.reload()
                        expect(page.locator("#importButton")).to_be_enabled(timeout=15000)
                        expect(page.locator("#libraryPanel")).to_be_hidden()
                        assert parse_qs(urlparse(page.url).query)["id"] == [ident]
                        passed("Reload restores the selected document")
                        page.locator("#themeButton").click()
                        assert "network-dark" in page.locator("body").get_attribute("class")
                        page.locator("#labelsButton").click()
                        expect(page.locator("#labelsButton")).to_have_text("显示标签")
                        page.set_viewport_size({"width": 390, "height": 844})
                        page.locator("#libraryButton").click()
                        expect(page.locator("#libraryPanel")).to_be_visible()
                        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
                        page.screenshot(path=str(OUTPUT / "documents-mobile.png"))
                        report["screenshots"].append("documents-mobile.png")
                        passed("Theme, label toggle and mobile layout work")
                        assert not report["page_errors"], report["page_errors"]
                    finally:
                        browser.close()
    except Exception:
        report["failure"] = traceback.format_exc()
        raise
    finally:
        (OUTPUT / "documents-frontend-results.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


if __name__ == "__main__":
    main()
