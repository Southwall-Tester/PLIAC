"""Bounded retrieval from explicitly linked course texts and parsed source pages."""
import hashlib
import re

from learning_agent.course_graph import CourseGraphError, safe_id


def terms(text):
    words = set(re.findall(r"[a-z0-9_]{2,}", text.lower()))
    for run in re.findall(r"[\u4e00-\u9fff]+", text):
        words.update(run[index:index + 2] for index in range(len(run) - 1))
    return words


def retrieve_sources(graph, nodes, message, documents=None):
    sources = []
    query = terms(nodes[0]["title"] + " " + message)
    known = {item["id"]: item for item in graph.get("sources", [])}
    for position, node in enumerate(nodes):
        units = []
        if node.get("document_id") and node.get("document_evidence"):
            if documents is None:
                raise CourseGraphError("关联原始资料尚未接入，不能用生成摘要代替原文。", 409)
            ident = safe_id(node["document_id"], "资料编号")
            job = documents.status(ident)
            pages = {item.get("page") for item in node["document_evidence"] if type(item.get("page")) is int and item["page"] > 0}
            if not pages or len(pages) > 80:
                raise CourseGraphError("资料页范围无效或过大，请修正知识点的来源映射。", 409)
            for page in sorted(pages):
                text = documents.page(ident, page).get("text", "")
                if not text.strip():
                    raise CourseGraphError("关联资料页缺少可读原文，请先完成解析。", 409)
                units.append({"key": f"document:{ident}:{page}", "text": text, "origin": "uploaded_document",
                    "title": job["title"], "page": page, "document_id": ident,
                    "url": f"/api/documents/{ident}/source" + (f"#page={page}" if job.get("page_kind") == "pdf" else "")})
        for ref in node.get("source_ids", []):
            source = known.get(ref, {})
            if isinstance(source.get("text"), str) and source["text"].strip():
                units.append({"key": f"source:{ref}", "text": source["text"], "origin": "course_source",
                    "title": source.get("title", ref)})
        # Existing authored course paragraphs remain available, but are explicitly
        # distinguished from original source pages, never relabeled as a textbook.
        if not node.get("document_id"):
            for index, paragraph in enumerate([{"text": node.get("description", "")}, *node.get("lesson_content", [])]):
                if paragraph.get("text", "").strip():
                    units.append({"key": f"course:{node['id']}:{index}", "text": paragraph["text"],
                        "origin": "authored_course_content", "title": node["title"]})
        for unit in units:
            text = unit["text"]
            digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
            for start in range(0, len(text), 2800):
                chunk = text[start:start + 3200]
                record = {key: value for key, value in unit.items() if key not in {"key", "text"}}
                record.update(id=f"{unit['key']}:{start}", text=chunk, node_id=node["id"],
                    course_version=graph["version"], content_digest=digest, char_start=start,
                    char_end=start + len(chunk))
                score = len(query & terms(chunk)) + (5 if position == 0 else 0)
                sources.append((score, record))
    selected, seen = [], set()
    for _, record in sorted(sources, key=lambda item: -item[0]):
        if record["id"] in seen:
            continue
        seen.add(record["id"])
        selected.append(record)
        if len(selected) == 16:
            break
    if not selected:
        raise CourseGraphError("当前知识范围没有可定位的教学正文，请补充资料。", 409)
    return selected
