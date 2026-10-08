"""Read-only authoring checks; findings are review prompts, not semantic verdicts.

The source books motivate preserving typed relations and reviewing alignment.
No embedding, GNN, automatic entity merge, or learner inference is performed.
"""
from collections import Counter, defaultdict
from copy import deepcopy
import unicodedata

import networkx as nx


BOOK_REFERENCES = [
    {"id": "kg_triples", "title": "知识图谱与深度学习", "filename": "知识图谱与深度学习_刘知远_2020.pdf",
     "section": "1.1", "pdf_pages": [18], "printed_pages": [4],
     "applied_to": "区分实体、关系及头尾方向；四类课程关系的具体定义仍以 v7 与教师编排为准。"},
    {"id": "kg_extraction_noise", "title": "知识图谱与深度学习", "filename": "知识图谱与深度学习_刘知远_2020.pdf",
     "section": "1.3.2、3.2.2", "pdf_pages": [26, 84], "printed_pages": [12, 72],
     "applied_to": "概念共现不能单独证明某种关系；来源完整性检查不能替代原文语义核验。"},
    {"id": "kg_alignment", "title": "知识图谱与深度学习", "filename": "知识图谱与深度学习_刘知远_2020.pdf",
     "section": "4.3–4.3.1", "pdf_pages": [141, 143], "printed_pages": [129, 131],
     "applied_to": "名称冲突仅作为人工核查候选，避免错误对齐继续传播；未实现书中的嵌入对齐算法。"},
    {"id": "gnn_graph_types", "title": "深入浅出图神经网络：GNN 原理解析", "filename": "深入浅出图神经网-GNN原理解析_2019.pdf",
     "section": "1.1.1、1.1.2、1.3", "pdf_pages": [3, 6, 11], "printed_pages": [],
     "applied_to": "区分方向、邻接与类型属性。此文件为阅读器截图，底部位置不当作印刷页；未实现 GNN。"},
]

RELATION_SCHEMA = [
    {"type": "prerequisite", "label": "前置", "directed": True, "direction": "先修知识 → 后续知识",
     "meaning": "教师认定后续学习需先核验的知识依赖。", "constrains_learning_order": True,
     "boundary": "只沿前置关系计算学习路径；前置已掌握不等于后续知识已掌握。"},
    {"type": "contains", "label": "包含", "directed": True, "direction": "整体概念 → 组成概念",
     "meaning": "描述课程知识的组成或层次。", "constrains_learning_order": False,
     "boundary": "包含不自动构成先修；整体与部分不能自动相互继承掌握状态。"},
    {"type": "related", "label": "关联", "directed": False, "direction": "双向关联",
     "meaning": "两个概念有可说明的教学联系。", "constrains_learning_order": False,
     "boundary": "关联不等于同义、因果或先修，也不用于传播掌握状态。"},
    {"type": "confusable", "label": "易混淆", "directed": False, "direction": "双向对照",
     "meaning": "两个概念需要通过边界或反例进行辨析。", "constrains_learning_order": False,
     "boundary": "易混淆不表示概念相同；连线不能证明某名学习者已经混淆。"},
]


def normalize_name(value):
    """Normalize typography only. Do not equate punctuation or semantic synonyms."""
    if not isinstance(value, str):
        return ""
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def _has_locator(value):
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, dict):
        return any(_has_locator(item) for item in value.values())
    if isinstance(value, (list, tuple)):
        return any(_has_locator(item) for item in value)
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def audit_graph(graph):
    """Return nonblocking author review findings without changing any input field.

    Designed for an existing validated course graph. This function intentionally
    does not grant review approval or write graph / learner data.
    """
    nodes = graph.get("nodes", [])
    edges = graph.get("edges", [])
    sources = graph.get("sources", [])
    resources = graph.get("resources", [])
    node_ids = {n["id"] for n in nodes}
    source_ids = {s["id"] for s in sources}
    issues = []

    def add(code, title, message, **details):
        issues.append({"code": code, "severity": "notice", "title": title, "message": message,
                       "node_ids": details.pop("node_ids", []), "edge_ids": details.pop("edge_ids", []),
                       "source_ids": details.pop("source_ids", []), "details": details})

    name_index = defaultdict(list)
    for node in nodes:
        by_name = defaultdict(list)
        for kind, value in [("title", node.get("title", "")), *[("alias", v) for v in node.get("aliases", [])]]:
            normalized = normalize_name(value)
            if normalized:
                by_name[normalized].append({"kind": kind, "value": value})
        for normalized, mentions in by_name.items():
            name_index[normalized].append({"node_id": node["id"], "title": node.get("title", ""), "mentions": mentions})
            if len(mentions) > 1:
                add("duplicate_name_within_node", "同一概念的名称重复",
                    "标题或别名经全半角、大小写和空白规范化后重复，可人工整理；核查不会删除名称。",
                    node_ids=[node["id"]], normalized_name=normalized, mentions=mentions)
    for normalized, matches in sorted(name_index.items()):
        if len(matches) > 1:
            add("name_collision", "多个概念使用同一名称",
                "请结合概念定义、边界及来源确认是重名、上下位关系还是需要整理的别名；名称相同不代表同一概念。",
                node_ids=[m["node_id"] for m in matches], normalized_name=normalized, matches=matches)

    for collection, items in (("node", nodes), ("edge", edges)):
        for item in items:
            refs = item.get("source_ids", [])
            missing = [ref for ref in refs if ref not in source_ids]
            binding = {"node_ids" if collection == "node" else "edge_ids": [item["id"]]}
            if not refs or missing:
                add("missing_source", "知识或关系缺少可回查依据",
                    "补充概念出处或教师编排依据，再逐条核查所引用内容是否支持该定义或关系。",
                    **binding, source_ids=missing, item_type=collection)
    for source in sources:
        if not _has_locator(source.get("locator")):
            add("source_locator_missing", "资料尚未填写具体定位",
                "可补充章节、页码、段落或视频时间段，便于复核；有来源链接不等于相关知识已被证实。",
                source_ids=[source["id"]], source_title=source.get("title", ""))
    for edge in edges:
        if not str(edge.get("reason", "")).strip():
            add("relation_reason_missing", "关系尚未说明理由",
                "请解释这条连线的教学或内容依据，并按四类关系边界复核。", edge_ids=[edge["id"]])

    directed = nx.DiGraph()
    directed.add_nodes_from(node_ids)
    prerequisite_edges = [e for e in edges if e.get("type") == "prerequisite"]
    directed.add_edges_from((e["source"], e["target"]) for e in prerequisite_edges)
    edge_lookup = {(e["source"], e["target"]): e["id"] for e in prerequisite_edges}
    for edge in prerequisite_edges:
        other = directed.copy()
        other.remove_edge(edge["source"], edge["target"])
        if nx.has_path(other, edge["source"], edge["target"]):
            route = nx.shortest_path(other, edge["source"], edge["target"])
            route_edges = [edge_lookup[(a, b)] for a, b in zip(route, route[1:])]
            add("transitive_prerequisite", "前置关系已有间接路径",
                "这条直接前置关系还可经其他前置边抵达；请确认是否为了强调直接教学依赖而保留，不会自动删边。",
                node_ids=route, edge_ids=[edge["id"], *route_edges], direct_edge_id=edge["id"], alternative_path=route)

    connected = {e[side] for e in edges for side in ("source", "target")}
    for node in nodes:
        if node["id"] not in connected:
            add("isolated_node", "概念暂未连接其他知识",
                "确认该节点是否有意独立，或需补充有依据的关系；孤立本身不代表内容错误。", node_ids=[node["id"]])

    counts = Counter(issue["code"] for issue in issues)
    relation_counts = Counter(e.get("type") for e in edges)
    schema = deepcopy(RELATION_SCHEMA)
    for relation in schema:
        relation["edge_count"] = relation_counts[relation["type"]]
    return {
        "summary": {
            "node_count": len(nodes), "edge_count": len(edges), "source_count": len(sources),
            "resource_count": len(resources), "issue_count": len(issues), "issue_counts": dict(counts),
            "name_collision_count": counts["name_collision"],
            "duplicate_name_count": counts["duplicate_name_within_node"],
            "missing_source_count": counts["missing_source"],
            "sources_without_locator_count": counts["source_locator_missing"],
            "sources_with_locator_count": sum(_has_locator(s.get("locator")) for s in sources),
            "isolated_node_count": counts["isolated_node"],
            "redundant_prerequisite_count": counts["transitive_prerequisite"],
            "pending_review_count": sum(i.get("review_status") != "reviewed" for i in [*nodes, *edges, *resources]),
            "relation_counts": dict(relation_counts), "read_only": True, "automatic_changes": 0,
        },
        "issues": issues, "relation_schema": schema, "book_references": deepcopy(BOOK_REFERENCES),
        "sources": [{"id": s["id"], "title": s.get("title", ""), "url": s.get("url", ""),
                     "locator": deepcopy(s.get("locator"))} for s in sources],
        "notice": "核查结果仅供教师逐条确认，不会自动合并概念、删边、批准发布或改变学习者状态。",
    }
