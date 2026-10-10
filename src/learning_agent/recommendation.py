"""Deterministic, cold-start resource selection over an already validated course.

Book-inspired content filtering and transparent reranking are adapted to v7's
educational constraints. This module neither learns a model nor updates mastery.
"""

from __future__ import annotations

import copy
import re


RULE_VERSION = "content-frontier-v1"
STRATEGY = "reviewed_content_and_prerequisite_rules"


def recommend_resources(graph, states, target_id, *, limit=4):
    """Return at most four eligible resources and a reproducible selection trace.

    Only prerequisite relations constrain the actionable frontier. Missing or due
    evidence never satisfies a prerequisite. Interest and click histories are not
    arguments to this function and cannot affect the ranking or learner state.
    """
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 4:
        raise ValueError("资源推荐数量必须是 1 至 4 的整数。")
    nodes = {node["id"]: node for node in graph["nodes"]}
    if target_id not in nodes:
        raise ValueError("目标知识节点不存在。")
    course_order = {node["id"]: index for index, node in enumerate(graph["nodes"])}
    predecessors = {ident: set() for ident in nodes}
    for edge in graph["edges"]:
        if edge["type"] == "prerequisite":
            predecessors[edge["target"]].add(edge["source"])

    def mastered(ident):
        state = states.get(ident, {})
        return state.get("status") == "mastered" and not state.get("due", False)

    pending, visited, todo = set(), set(), [target_id]
    while todo:
        ident = todo.pop()
        if ident in visited:
            continue
        visited.add(ident)
        if mastered(ident):
            continue
        pending.add(ident)
        todo.extend(predecessors[ident])
    pending_ids = sorted(pending, key=course_order.__getitem__)
    frontier = [ident for ident in pending_ids if all(mastered(p) for p in predecessors[ident])]
    frontier_set = set(frontier)
    frontier_order = {ident: index for index, ident in enumerate(frontier)}
    excluded, eligible = [], []

    def exclude(resource, codes, reasons, **extra):
        excluded.append({"resource_id": resource["id"], "reason_codes": codes,
                         "reasons": reasons, "reason": "；".join(reasons), **extra})

    for resource in sorted(graph.get("resources", []), key=lambda item: item["id"]):
        codes, reasons = [], []
        matched = frontier_set.intersection(resource.get("node_ids", []))
        if resource.get("review_status") not in {"reviewed", "auto_validated"}:
            codes.append("not_reviewed")
            reasons.append("资源尚未通过有效核验")
        if not matched:
            codes.append("outside_frontier")
            reasons.append("未覆盖当前可行动的待核验知识点")
        missing = [ident for ident in resource.get("prerequisite_ids", []) if not mastered(ident)]
        if missing:
            codes.append("unmet_resource_prerequisites")
            reasons.append("资源前置知识仍待核验：" + "、".join(nodes[ident]["title"] for ident in missing))
        if codes:
            exclude(resource, codes, reasons, missing_prerequisite_ids=missing)
            continue
        eligible.append((resource, sorted(matched, key=frontier_order.__getitem__)))

    eligible_count = len(eligible)
    selected, covered, formats, selected_keys, rounds = [], set(), set(), {}, []

    def duplicate_key(resource):
        # Keep separate course/video segments; only exact URL + normalized segment
        # duplicates collapse. URL fragments and query strings may select a lesson.
        segment = re.sub(r"\s+", " ", resource.get("applicable_segment", "")).strip()
        url = resource.get("url", "").strip()
        return ("url_segment", url, segment) if url else ("resource_id", resource["id"])

    def ranking_key(item):
        resource, matched = item
        new_nodes = set(matched) - covered
        first_uncovered = min((frontier_order[n] for n in new_nodes), default=len(frontier))
        return (first_uncovered, -len(new_nodes), resource.get("format", "") in formats,
                -len(matched), resource["id"])

    while eligible and len(selected) < limit:
        eligible.sort(key=ranking_key)
        resource, matched = eligible.pop(0)
        key = duplicate_key(resource)
        if key in selected_keys:
            exclude(resource, ["duplicate_segment"], ["与已选资源的链接及适用片段相同"],
                    duplicate_of=selected_keys[key])
            continue
        rank_key = ranking_key((resource, matched))
        newly_covered = [ident for ident in matched if ident not in covered]
        new_format = resource.get("format", "") not in formats
        titles = "、".join(nodes[ident]["title"] for ident in matched)
        relation_reason = ("先补齐目标知识的可行动先修：" if target_id not in frontier_set
                           else "关联当前待核验知识：") + titles
        reasons = ["已通过自动核验" if resource.get('review_status') == 'auto_validated' else "已通过人工审核", relation_reason, "资源前置条件已满足"]
        if newly_covered:
            reasons.append("补充本轮尚未覆盖的知识点")
        if new_format and selected:
            reasons.append("提供不同形态的学习材料")
        reasons.append("学习后仍需独立作答核验")
        value = copy.deepcopy(resource)
        value.update(recommendation_node_id=matched[0], matched_node_ids=matched,
                     recommendation_reason="；".join(reasons), reason="；".join(reasons),
                     rank=len(selected) + 1, recommendation_rule_version=RULE_VERSION)
        selected.append(value)
        selected_keys[key] = resource["id"]
        covered.update(matched)
        formats.add(resource.get("format", ""))
        rounds.append({"rank": len(selected), "resource_id": resource["id"],
                       "matched_node_ids": matched, "newly_covered_node_ids": newly_covered,
                       "new_format": new_format, "ranking_key": list(rank_key)})

    for resource, _matched in eligible:
        key = duplicate_key(resource)
        if key in selected_keys:
            exclude(resource, ["duplicate_segment"], ["与已选资源的链接及适用片段相同"],
                    duplicate_of=selected_keys[key])
        else:
            exclude(resource, ["selection_limit"], [f"已满足本轮最多 {limit} 项的展示数量限制"])

    excluded.sort(key=lambda item: item["resource_id"])
    return {
        "resources": selected,
        "frontier_node_ids": frontier,
        "pending_node_ids": pending_ids,
        "excluded_resources": excluded,
        "strategy": STRATEGY,
        "rule_version": RULE_VERSION,
        "selection_trace": {
            "mode": "deterministic_rules",
            "model_trained": False,
            "candidate_count": len(graph.get("resources", [])),
            "eligible_count": eligible_count,
            "selected_count": len(selected),
            "limit": limit,
            "ranking_rule": "课程顺序中尚未覆盖的前沿节点优先，其次新增覆盖数、形态多样性、总覆盖数和稳定资源编号。",
            "mastery_effect": "none",
            "rounds": rounds,
        },
    }
