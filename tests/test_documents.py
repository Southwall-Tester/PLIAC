"""Document ingestion contracts: real parsing, grounded extraction, isolated draft writes."""
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from learning_agent.documents import DocumentStore, chunks, document_outline, extract_local, extract_llm, hierarchy, term_id
from learning_agent.course_graph import CourseGraphStore, CourseGraphError


class DocumentsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = DocumentStore(Path(self.tmp.name) / "documents")
        self.course = CourseGraphStore(output_dir=Path(self.tmp.name) / "course")

    def tearDown(self):
        self.store.executor.shutdown(wait=True)
        self.tmp.cleanup()

    def book(self, text="知识图谱包括实体和关系。实体对齐用于知识融合。知识图谱可以支持关系抽取。", filename="教材.txt"):
        job = self.store.create(filename)
        self.store.source(job["id"]).write_text(text, encoding="utf-8")
        self.store.run(job["id"])
        return job["id"]

    def test_chunks_preserve_original_offsets_and_coverage(self):
        text = ("知识图谱包括实体。\n" * 700)
        seen = set()
        for offset, value in chunks(text):
            self.assertEqual(text[offset:offset + len(value)], value)
            self.assertLessEqual(len(value), 3200)
            seen.update(range(offset, offset + len(value)))
        self.assertEqual(len(seen), len(text))

    def test_local_provenance_is_exact_and_never_creates_prerequisite(self):
        ident = self.book()
        self.assertEqual(self.store.status(ident)["status"], "completed")
        graph, page = self.store.graph(ident), self.store.page(ident, 1)
        self.assertGreater(len(graph["nodes"]), 2)
        self.assertTrue(graph["edges"])
        self.assertNotIn("prerequisite", {e["type"] for e in graph["edges"]})
        for item in graph["nodes"] + graph["edges"]:
            for ev in item["evidence"]:
                self.assertEqual(page["text"][ev["start"]:ev["end"]], ev["quote"])

    def test_negation_and_distant_terms_do_not_become_containment(self):
        negative = extract_local("知识图谱不包含神经网络。", 1)
        distant = extract_local("知识图谱的研究定义涉及多种方法，其中包括神经网络。", 1)
        self.assertFalse(any(e["type"] == "contains" for e in negative["edges"] + distant["edges"]))
        positive = extract_local("知识图谱包括神经网络。", 1)
        self.assertTrue(any(e["type"] == "contains" for e in positive["edges"]))

    def test_terms_preserve_compounds_and_reject_ocr_fragments(self):
        extracted = extract_local("知识图谱使用远程监督进行关系抽取。实体对齐包括硬对齐和软对齐。lle1 e211", 1)
        names = {n["title"] for n in extracted["nodes"]}
        self.assertTrue({"知识图谱", "远程监督", "关系抽取", "实体对齐"} <= names)
        self.assertFalse({"lle1", "e211"} & names)

    def test_local_terms_prefer_marked_compounds_and_reject_translation_fragments(self):
        text = ("**卷积神经网络 (Convolutional Neural Network，简称 CNN)**处理图像。"
                "**支持向量机**用于分类。含义是“Non-deterministic Polynomial”。"
                "公式\\text{CNN}用于说明。家族、答案、学界只是讲解用语。"
                "**“随机化 (randomization)”**用于计算。")
        result = extract_local(text, 3, 80)
        names = {n["title"] for n in result["nodes"]}
        self.assertTrue({"卷积神经网络", "支持向量机", "随机化", "CNN"} <= names)
        self.assertFalse({"Convolutional", "Neural", "Network", "Polynomial", "text", "家族", "答案", "学界", "“随机化"} & names)
        for item in result["nodes"] + result["edges"]:
            for ev in item["evidence"]:
                self.assertEqual(text[ev["start"] - 80:ev["end"] - 80], ev["quote"])

    def test_local_defined_initial_is_preserved_without_matching_larger_words(self):
        text = "**P** 与 **NP** 是两类判定问题。公式\\text{P}与\\text{NP}用来表示类别。"
        result = extract_local(text, 1)
        by_id = {n["id"]: n["title"] for n in result["nodes"]}
        self.assertTrue({"P", "NP"} <= set(by_id.values()))
        self.assertNotIn("text", by_id.values())
        self.assertTrue(any({by_id[e["source"]], by_id[e["target"]]} == {"P", "NP"} for e in result["edges"]))
        self.assertNotIn("P", {n["title"] for n in extract_local("Polynomial time 和 NP 不是单字母定义。", 1)["nodes"]})
        self.assertTrue(all(e["type"] in {"contains", "cooccurs"} for e in result["edges"]))

    def test_local_cleanup_keeps_english_material_and_does_not_change_llm_filter(self):
        names = {n["title"] for n in extract_local("Neural networks include neurons. Networks learn representations.", 1)["nodes"]}
        self.assertTrue({"networks", "neurons"} <= names)
        reply = {"nodes": [{"id": "x", "title": "time", "quote": "time is a quantity."}], "edges": []}
        with patch("learning_agent.llm.call_llm_json", return_value=json.dumps(reply)):
            result = extract_llm("time is a quantity.", 1, config={})
        self.assertEqual([n["title"] for n in result["nodes"]], ["time"])

    def test_pdf_page_range_and_toc_are_real(self):
        import fitz
        job = self.store.create("book.pdf", start_page=2, end_page=2)
        with fitz.open() as doc:
            for text in ["Introduction text and source concepts.", "Networks\nNeurons\nNeural networks include neurons. Neural networks learn representations."]:
                page = doc.new_page()
                page.insert_text((40, 60), text)
            doc.set_toc([[1, "Introduction", 1], [1, "Networks", 2], [2, "Neurons", 2]])
            doc.save(self.store.source(job["id"]))
        self.store.run(job["id"])
        self.assertEqual(self.store.status(job["id"])["stats"]["pages"], 1)
        graph = self.store.graph(job["id"])
        self.assertTrue(graph["nodes"])
        self.assertTrue(all(ev["page"] == 2 for n in graph["nodes"] for ev in n["evidence"]))
        titles = {n["title"] for n in graph["hierarchy"]["nodes"]}
        self.assertTrue({"Networks", "Neurons"} <= titles)
        self.assertNotIn("Introduction", titles)

    def test_invalid_pdf_and_out_of_range_fail_honestly(self):
        job = self.store.create("broken.pdf")
        self.store.source(job["id"]).write_bytes(b"broken")
        self.store.run(job["id"])
        self.assertEqual(self.store.status(job["id"])["status"], "failed")
        job = self.store.create("text.txt", start_page=10)
        self.store.source(job["id"]).write_text("hello", encoding="utf-8")
        self.store.run(job["id"])
        self.assertIn("范围", self.store.status(job["id"])["error"])

    def test_scanned_pdf_uses_ocr_and_caches_page(self):
        import fitz
        job = self.store.create("scan.pdf")
        with fitz.open() as doc:
            page = doc.new_page()
            pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 50, 50))
            pix.clear_with(255)
            page.insert_image(page.rect, pixmap=pix)
            doc.save(self.store.source(job["id"]))
        with patch("learning_agent.documents.ocr_page", return_value="知识图谱包括实体。神经网络使用训练集。") as ocr:
            self.store.run(job["id"])
            self.store.run(job["id"])
        self.assertEqual(ocr.call_count, 1)
        self.assertEqual(self.store.status(job["id"])["stats"]["ocr_pages"], 1)

    def test_markdown_hierarchy_and_text_sections(self):
        ident = self.book("# 机器学习\n## 知识图谱\n知识图谱包括实体。知识图谱支持关系抽取。", "book.md")
        graph = self.store.graph(ident)
        by_title = {n["title"]: n for n in graph["hierarchy"]["nodes"]}
        self.assertEqual(by_title["知识图谱"]["parent_id"], by_title["机器学习"]["id"])
        self.assertEqual(graph["page_kind"], "section")

    def test_headingless_markdown_connects_00_root_to_every_concept(self):
        ident = self.book("知识图谱包括实体和关系。实体对齐用于知识融合。", "00.md")
        graph = self.store.graph(ident)
        self.assertTrue(graph["nodes"])
        containers = graph["hierarchy"]["nodes"]
        self.assertEqual(len(containers), 1)
        self.assertEqual((containers[0]["title"], containers[0]["kind"]), ("00", "book"))
        memberships = graph["hierarchy"]["memberships"]
        self.assertEqual({m["source"] for m in memberships}, {containers[0]["id"]})
        self.assertEqual({m["target"] for m in memberships}, {n["id"] for n in graph["nodes"]})

    def test_standalone_bold_headings_preserve_original_page_and_offset(self):
        titles = ["P 问题 (Polynomial time，多项式时间)", "NP 问题 (Nondeterministic Polynomial time)", "P 与 NP 的关系"]
        text = "原文介绍。\r\n" + " " * 6000 + "\r\n" + "\r\n正文。\r\n".join(f"**{title}**" for title in titles)
        source = Path(self.tmp.name) / "00.md"
        source.write_bytes(text.encode("utf-8"))
        outline = document_outline(source)
        self.assertEqual([h["title"] for h in outline], titles)
        self.assertEqual([h["level"] for h in outline], [1, 1, 1])
        self.assertTrue(all(h["page"] > 1 for h in outline))
        for heading, title in zip(outline, titles):
            at = (heading["page"] - 1) * 6000 + heading["start"]
            self.assertEqual(at, text.index(f"**{title}**"))
            self.assertTrue(text[at:].startswith(f"**{title}**"))

    def test_markdown_bold_peers_follow_explicit_heading_and_exclude_body_or_code(self):
        text = "\n".join([
            "# 复杂度 ###", "**P 问题**", "正文内容。", "**NP 问题**", "## 判定条件", "**验证过程**",
            "```markdown", "# 代码中的标题", "**代码中的粗体**", "````", "~~~", "### 另一围栏标题", "**另一段代码**", "~~~",
            "- **列表中的粗体**", "1. **有序列表粗体**", "  **列表缩进粗体**", "    **缩进代码**", "> **引用中的粗体**",
            "正文里有**粗体词**。", "**P** 与 **NP**", "**NP 完全问题**，是指一类正文内容。",
            "**" + "这是加粗的长正文段落。" * 20 + "**", "# 总结", "**关键关系**",
        ])
        source = Path(self.tmp.name) / "mixed.md"
        source.write_bytes(text.encode("utf-8"))
        outline = document_outline(source)
        self.assertEqual([(h["level"], h["title"]) for h in outline], [
            (1, "复杂度"), (2, "P 问题"), (2, "NP 问题"), (2, "判定条件"), (3, "验证过程"), (1, "总结"), (2, "关键关系"),
        ])

    def test_bold_section_hierarchy_survives_extraction_and_course_import(self):
        ident = self.book("**P 问题**\n知识图谱包括实体。\n**NP 问题**\n神经网络使用训练集。", "00.md")
        graph = self.store.graph(ident)
        containers = {n["id"]: n for n in graph["hierarchy"]["nodes"]}
        owners = {m["target"]: containers[m["source"]]["title"] for m in graph["hierarchy"]["memberships"]}
        self.assertEqual(owners[term_id("知识图谱")], "P 问题")
        self.assertEqual(owners[term_id("神经网络")], "NP 问题")
        self.assertEqual({n["kind"] for n in containers.values()}, {"book", "chapter"})
        for node in graph["nodes"]:
            for ev in node["evidence"]:
                self.assertEqual(self.store.page(ident, ev["page"])["text"][ev["start"]:ev["end"]], ev["quote"])
        imported = self.store.import_draft(ident, self.course, self.course.load_graph("draft")["version"])["graph"]
        chapter = next(c for c in imported["chapters"] if c["id"] == "doc_" + ident)
        mapped = chapter["document_hierarchy"]
        self.assertEqual(mapped["nodes"], graph["hierarchy"]["nodes"])
        targets = {n["id"]: n for n in imported["nodes"] if n.get("document_id") == ident}
        imported_owners = {targets[m["target"]]["title"]: containers[m["source"]]["title"] for m in mapped["memberships"]}
        self.assertEqual(imported_owners["知识图谱"], "P 问题")
        self.assertEqual(imported_owners["神经网络"], "NP 问题")

    def test_explanation_titles_stay_in_outline_but_are_not_graph_parents(self):
        text = ("**模型训练**\n训练集用于拟合。\n**通俗理解：从例子理解**\n知识图谱包括实体。\n"
                "**严格的判定条件**\n实体对齐用于知识融合。\n**模型评估**\n神经网络使用测试集。")
        ident = self.book(text, "概念说明.md")
        outline = document_outline(self.store.source(ident))
        self.assertEqual(len(outline), 4)
        explanations = [h for h in outline if h.get("role") == "explanation"]
        self.assertEqual([h["title"] for h in explanations], ["通俗理解：从例子理解", "严格的判定条件"])
        original = self.store.page(ident, 1)["text"]
        self.assertTrue(all(original[h["start"]:].startswith(f"**{h['title']}**") for h in explanations))
        graph = self.store.graph(ident)
        containers = {n["id"]: n for n in graph["hierarchy"]["nodes"]}
        self.assertFalse({"通俗理解：从例子理解", "严格的判定条件"} & {n["title"] for n in containers.values()})
        owners = {m["target"]: containers[m["source"]]["title"] for m in graph["hierarchy"]["memberships"]}
        self.assertEqual(owners[term_id("知识图谱")], "模型训练")
        self.assertEqual(owners[term_id("实体对齐")], "模型训练")
        self.assertEqual(owners[term_id("神经网络")], "模型评估")

    def test_text_chunk_boundaries_preserve_proofs_without_creating_chapters(self):
        text = "知识图谱包括实体。".ljust(6050, " ") + "神经网络使用训练集。知识图谱支持关系抽取。"
        ident = self.book(text, "分段材料.txt")
        graph = self.store.graph(ident)
        stats = self.store.status(ident)["stats"]
        self.assertGreater(stats["pages"], 1)
        self.assertGreater(stats["chunks"], stats["pages"])
        self.assertEqual([n["kind"] for n in graph["hierarchy"]["nodes"]], ["book"])
        root = graph["hierarchy"]["nodes"][0]["id"]
        self.assertTrue(all(m["source"] == root for m in graph["hierarchy"]["memberships"]))
        concept = next(n for n in graph["nodes"] if n["title"] == "知识图谱")
        self.assertEqual({ev["page"] for ev in concept["evidence"]}, {1, 2})
        for item in graph["nodes"] + graph["edges"]:
            for ev in item["evidence"]:
                page = self.store.page(ident, ev["page"])
                self.assertEqual(page["text"][ev["start"]:ev["end"]], ev["quote"])
        imported = self.store.import_draft(ident, self.course, self.course.load_graph("draft")["version"])["graph"]
        chapter = next(c for c in imported["chapters"] if c["id"] == "doc_" + ident)
        self.assertEqual(chapter["document_hierarchy"]["nodes"], graph["hierarchy"]["nodes"])
        additions = [n for n in imported["nodes"] if n.get("document_id") == ident]
        self.assertEqual({m["source"] for m in chapter["document_hierarchy"]["memberships"]}, {root})
        self.assertEqual({m["target"] for m in chapter["document_hierarchy"]["memberships"]}, {n["id"] for n in additions})
        originals = {n["title"]: n for n in graph["nodes"]}
        self.assertTrue(all(n["document_evidence"] == originals[n["title"]]["evidence"] for n in additions))

    def test_pdf_without_outline_keeps_physical_pages_and_imported_hierarchy(self):
        import fitz
        job = self.store.create("无目录.pdf")
        ident = job["id"]
        with fitz.open() as doc:
            for text in ("Neural networks include neurons. Neural networks learn representations.",
                         "Knowledge graphs link entities. Entity alignment connects knowledge graphs."):
                page = doc.new_page()
                page.insert_text((40, 60), text)
            doc.save(self.store.source(ident))
        self.store.run(ident)
        graph = self.store.graph(ident)
        self.assertTrue(graph["nodes"])
        containers = {n["id"]: n for n in graph["hierarchy"]["nodes"]}
        pages = [n for n in containers.values() if n["kind"] == "page"]
        self.assertEqual({n["page"] for n in pages}, {1, 2})
        self.assertEqual({n["title"] for n in pages}, {"第 1 页", "第 2 页"})
        memberships = graph["hierarchy"]["memberships"]
        self.assertEqual({containers[m["source"]]["kind"] for m in memberships}, {"page"})
        for item in graph["nodes"] + graph["edges"]:
            for ev in item["evidence"]:
                self.assertEqual(self.store.page(ident, ev["page"])["text"][ev["start"]:ev["end"]], ev["quote"])
        imported = self.store.import_draft(ident, self.course, self.course.load_graph("draft")["version"])["graph"]
        chapter = next(c for c in imported["chapters"] if c["id"] == "doc_" + ident)
        self.assertEqual(chapter["document_hierarchy"]["nodes"], graph["hierarchy"]["nodes"])
        targets = {n["id"] for n in imported["nodes"] if n.get("document_id") == ident}
        self.assertEqual({m["target"] for m in chapter["document_hierarchy"]["memberships"]}, targets)

    def test_names_merge_with_multiple_page_proofs(self):
        ident = self.book("知识图谱包括实体。" + " " * 6000 + "知识图谱支持关系抽取。")
        graph = self.store.graph(ident)
        nodes = [n for n in graph["nodes"] if n["title"] == "知识图谱"]
        self.assertEqual(len(nodes), 1)
        self.assertEqual({ev["page"] for ev in nodes[0]["evidence"]}, {1, 2})

    def test_model_rejects_invented_quotes_and_endpoint_mismatch(self):
        result = {"nodes": [{"id": "a", "title": "知识图谱", "quote": "知识图谱关联神经网络。"}, {"id": "b", "title": "神经网络", "quote": "知识图谱关联神经网络。"}],
                  "edges": [{"source": "a", "target": "b", "type": "contains", "quote": "不存在的原文"}]}
        with patch("learning_agent.llm.call_llm_json", return_value=json.dumps(result)):
            extracted = extract_llm("知识图谱关联神经网络。", 3, 100, {})
        self.assertEqual(len(extracted["edges"]), 0)
        self.assertEqual(extracted["rejected"], 1)
        self.assertEqual(extracted["nodes"][0]["evidence"][0]["start"], 100)
        result["nodes"][0]["quote"] = "虚构"
        result["nodes"][1]["quote"] = "虚构"
        with patch("learning_agent.llm.call_llm_json", return_value=json.dumps(result)):
            with self.assertRaises(CourseGraphError):
                extract_llm("知识图谱关联神经网络。", 1, config={})

    def test_failed_chunk_retry_retains_completed_checkpoints(self):
        job = self.store.create("book.txt")
        self.store.source(job["id"]).write_text("知识图谱包括实体。" * 800, encoding="utf-8")
        real_extract = extract_local
        calls = 0
        def fail_second(*args):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise CourseGraphError("模拟请求失败", 502)
            return real_extract(*args)
        with patch("learning_agent.documents.extract_local", side_effect=fail_second):
            self.store.run(job["id"])
        self.assertEqual(self.store.status(job["id"])["status"], "partial")
        self.assertEqual(self.store.status(job["id"])["stats"]["chunks"], 1)
        first = next((self.store.directory(job["id"]) / "chunks").glob("*.json"))
        before = first.stat().st_mtime_ns
        self.store.run(job["id"])
        self.assertEqual(self.store.status(job["id"])["status"], "completed")
        self.assertEqual(first.stat().st_mtime_ns, before)

    def test_cancel_preserves_status_and_stops_processing(self):
        job = self.store.create("book.txt")
        self.store.source(job["id"]).write_text("知识图谱包括实体。", encoding="utf-8")
        self.store.cancelled.add(job["id"])
        self.store.run(job["id"])
        self.assertEqual(self.store.status(job["id"])["status"], "cancelled")
        self.assertFalse((self.store.directory(job["id"]) / "graph.json").exists())

    def test_import_is_draft_versioned_and_maps_cooccurrence(self):
        ident = self.book()
        before = self.course.load_graph("draft")
        with self.assertRaises(CourseGraphError) as conflict:
            self.store.import_draft(ident, self.course, before["version"] + 1)
        self.assertEqual(conflict.exception.status_code, 409)
        result = self.store.import_draft(ident, self.course, before["version"])
        self.assertEqual(result["version"], before["version"] + 1)
        added = [n for n in result["graph"]["nodes"] if n.get("document_id") == ident]
        self.assertTrue(added)
        self.assertTrue(all(n["review_status"] == "draft" and n["document_evidence"] for n in added))
        self.assertTrue(all(n["document_page_kind"] == "section" for n in added))
        self.assertIsNone(self.course.load_graph("published"))
        for edge in result["graph"]["edges"]:
            if edge.get("extraction_type") == "cooccurs":
                self.assertEqual(edge["type"], "related")
        duplicate = self.store.import_draft(ident, self.course, result["version"])
        self.assertEqual(duplicate["nodes_added"], 0)
        self.assertEqual(duplicate["edges_added"], 0)
        self.assertEqual(duplicate["version"], result["version"])

    def test_incremental_import_adds_missing_nodes_edges_and_mapped_hierarchy(self):
        ident = self.book()
        nodes = self.store.graph(ident)["nodes"]
        version = self.course.load_graph("draft")["version"]
        first = self.store.import_draft(ident, self.course, version, [nodes[0]["id"]])
        second = self.store.import_draft(ident, self.course, first["version"], [n["id"] for n in nodes[1:]])
        self.assertEqual(first["nodes_added"] + second["nodes_added"], len(nodes))
        self.assertEqual(len([s for s in second["graph"]["sources"] if s["id"] == "doc_" + ident]), 1)
        chapter = next(c for c in second["graph"]["chapters"] if c["id"] == "doc_" + ident)
        course_ids = {n["id"] for n in second["graph"]["nodes"]}
        self.assertTrue(all(m["target"] in course_ids for m in chapter["document_hierarchy"]["memberships"]))

    def test_same_page_headings_assign_concepts_by_character_offset(self):
        ident = self.book("# 第一节\n神经网络包括训练集。\n# 第二节\n知识图谱支持实体对齐。", "book.md")
        graph = self.store.graph(ident)
        by_id = {n["id"]: n for n in graph["hierarchy"]["nodes"]}
        membership = {m["target"]: by_id[m["source"]]["title"] for m in graph["hierarchy"]["memberships"]}
        self.assertEqual(membership[term_id("神经网络")], "第一节")
        self.assertEqual(membership[term_id("实体对齐")], "第二节")

    def test_path_traversal_and_invalid_engine_are_rejected(self):
        for value in ["../../secret", "x" * 32, "a" * 33]:
            with self.assertRaises(CourseGraphError):
                self.store.directory(value)
        with self.assertRaises(CourseGraphError):
            self.store.create("book.exe")
        with self.assertRaises(CourseGraphError):
            self.store.create("book.pdf", engine="unknown")
        job = self.store.create("../../secret.txt")
        self.assertEqual(job["filename"], "secret.txt")

    def test_upload_api_and_original_file_round_trip(self):
        from fastapi.testclient import TestClient
        from learning_agent.main import app
        with patch("learning_agent.document_api.document_store", self.store):
            client = TestClient(app)
            response = client.post("/api/documents/upload", files={"file": ("教材.txt", "知识图谱包括实体。关系抽取关联神经网络。".encode("utf-8"), "text/plain")})
            self.assertEqual(response.status_code, 200, response.text)
            ident = response.json()["id"]
            self.store.futures[ident].result(timeout=15)
            self.assertEqual(client.get(f"/api/documents/{ident}").json()["status"], "completed")
            self.assertTrue(client.get(f"/api/documents/{ident}/graph").json()["nodes"])
            self.assertIn("知识图谱", client.get(f"/api/documents/{ident}/source").text)
            self.assertEqual(client.get(f"/api/documents/{ident}/pages/1").status_code, 200)
            self.assertEqual(len(client.get("/api/documents").json()["documents"]), 1)


if __name__ == "__main__":
    unittest.main()
