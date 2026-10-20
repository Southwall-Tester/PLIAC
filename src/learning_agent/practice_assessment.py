"""Derived per-learner estimates over persisted, version-bound Lab observations.

These estimates are a separate layer from reviewed diagnoses and course content.
They never satisfy the platform's confirmed-mastery gates.
"""
from statistics import median
from .behavior_assessment import summarize
LABELS = {
    "not_observed": "尚未涉及", "insufficient": "证据不足", "needs_practice": "需要练习",
    "assisted": "借助提示完成", "referenced": "参考资料完成", "developing": "初步掌握", "proficient": "较稳定",
}
NEXT = {
    "not_observed": "完成包含该知识点的练习。",
    "insufficient": "补充该知识点的直接操作与检查；抽象概念需另做解释或迁移题。",
    "needs_practice": "查看本次错误依据，针对该知识点修正后再检查。",
    "assisted": "在新周目先不看提示完成对应任务，再检查结果。",
    "referenced": "本次成功前查阅了对应资料；可在新周目先尝试自行完成，再按需要查阅和核对。",
    "developing": "在新周目复测该知识点，积累不同尝试的表现。",
    "proficient": "尝试不同任务或解释操作原因，验证能否迁移。",
}


def derive(learner, graph, history):
    from .course_graph import _fingerprint
    snapshots = [entry["assessment"] for entry in learner.get("workspace", {}).get("linuxlab", {}).values()
                 if entry.get("assessment", {}).get("course_id") == graph["id"]
                 and entry["assessment"].get("student_id") == learner["student_id"]]
    if not snapshots:
        return {}
    result = {}
    for node in graph["nodes"]:
        fingerprint = _fingerprint(node)
        compatible, stale = [], 0
        for snapshot in snapshots:
            item = snapshot["nodes"].get(node["id"])
            if not item:
                continue
            if (snapshot["course_version"] > graph["version"] or item["node_fingerprint"] != fingerprint
                    or any(nodes.get(node["id"]) != fingerprint for version, nodes in history.items()
                           if snapshot["course_version"] < version <= graph["version"])):
                stale += 1
                continue
            compatible.append((snapshot, item))
        compatible.sort(key=lambda pair: (pair[1]["updated_at"], pair[0]["binding_id"]))
        # Distinct bindings that point at the same LinuxLab save are not new trials.
        unique = {}
        for snapshot, item in compatible:
            unique[snapshot["lab_session_id"]] = (snapshot, item)
        records = sorted(unique.values(), key=lambda pair: (pair[1]["updated_at"], pair[0]["binding_id"]))
        recent = records[-3:]
        streak = 0
        for _, item in reversed(records):
            if item["outcome"] != "success":
                break
            streak += 1
        latest = recent[-1][1] if recent else None
        level = ("insufficient" if stale else "not_observed") if latest is None else {
            "difficulty": "needs_practice", "assisted": "assisted", "referenced": "referenced", "recovered": "developing",
            "success": "proficient" if streak >= 2 else "developing", "insufficient": "insufficient",
        }[latest["outcome"]]
        reasons = list(latest["reasons"]) if latest else ["旧记录对应的节点内容已变化，需要重新评估。" if stale else "没有该知识点的实训观察。"]
        support_runs = sum(any(r['use'] == 'before_success' for r in item.get('references', [])) for _, item in recent)
        lookups = (latest or {}).get('references', [])
        if support_runs >= 2:
            reasons.append(f"最近 {len(recent)} 个周目中有 {support_runs} 个在成功操作前查阅同一知识点，记录到反复查阅依赖；是否仍需帮助以最新独立复测为准。")
        if lookups and not any(r['use'] == 'before_success' for r in lookups):
            reasons.append("记录到相关资料查阅，但未发现它位于本关成功操作之前；仅作查阅记录，不据此降低既有表现。")
        episodes = sum(p["episodes"] for _, item in recent for p in item.get("input_signals", []))
        unresolved = sum(max(0, p["episodes"] - p["resolved_episodes"])
                         for p in (latest or {}).get("input_signals", []) if p["active"])
        recurring = episodes >= 2
        if recurring:
            if level == "proficient":
                level = "developing"
            reasons.append(f"最近 {len(recent)} 个周目记录到 {episodes} 个输入问题段，存在反复易错迹象；重复检查不增加问题段。")
        elif episodes:
            reasons.append("目前只有一个输入问题段，按偶发失误记录，不据此判定知识不熟练。")
        if streak >= 2 and not recurring:
            reasons.append(f"连续 {streak} 个不同周目有直接成功依据；同一周目的重复检查只算一次。")
        timing = []
        for current in (latest or {}).get("timing", []):
            item = dict(current, comparison="insufficient_baseline", baseline_samples=0)
            baseline = [t["continuous_seconds"] for _, old in records[:-1] if old["outcome"] == "success"
                        for t in old.get("timing", []) if t["phase"] == current["phase"] and t.get("available")
                        and t.get("completed") and not t["long_gaps"] and t["continuous_seconds"] >= 5]
            item["baseline_samples"] = len(baseline)
            if current.get("available") and current["long_gaps"]:
                item["comparison"] = "interrupted"
            elif current.get("available") and current.get("completed") and len(baseline) >= 3:
                typical = median(baseline[-5:])
                item.update(baseline_seconds=typical, ratio=round(current["continuous_seconds"] / typical, 2))
                slow = current["continuous_seconds"] >= max(30, typical * 2)
                item["comparison"] = "slower" if slow else "typical"
                if slow:
                    reasons.append(f"第 {current['phase']} 关的连续操作间隔合计为自身近期基线的 {item['ratio']} 倍；用时本身不扣掌握等级。")
                    if recurring or unresolved or level in ("needs_practice", "assisted", "referenced"):
                        item["comparison"] = "slower_with_difficulty"
                        reasons.append("本次较慢同时伴随反复输入问题、未修正问题或提示依赖，建议针对该环节练习熟练度。")
            timing.append(item)
        behavior = summarize(records, timing)
        if behavior['recurring_check_errors']:
            if level == 'proficient':
                level = 'developing'
            reasons.append("近期同一类检查问题在多个尝试段或周目重复出现，需针对具体检查项巩固。")
        followup = behavior['followup']['status']
        if followup == 'independent_followup':
            reasons.append("先前求助或出错后，新的同类任务已有无辅助通过记录；这支持独立操作有所改善，但尚未验证迁移。")
        elif followup == 'independent_recovery':
            reasons.append("后续周目已自行修正并通过同类任务；本次仍有错误，继续巩固。")
        if any(s['status'] == 'corrected_after_reference' for s in behavior['sequences']):
            reasons.append("观察到出错后查阅、随后修正并通过检查的顺序；保留其学习价值，不将查阅本身判作未掌握。")
        next_action = NEXT[level]
        if any(s['status'] == 'same_error_after_reference' for s in behavior['sequences']):
            next_action = "查阅后同类检查错误仍出现：对照具体检查项解释原因，修正后检查，再在新周目独立复测。"
        elif followup == 'independent_followup' and level in ('developing', 'proficient'):
            next_action = "已观察到后续独立完成；下一步换任务条件或隔一段时间复测，验证保持与迁移。"
        refs = [dict(binding_id=s["binding_id"], course_version=s["course_version"],
                     raw_digest=s["raw_digest"], refs=item["evidence_refs"], outcome=item["outcome"],
                     assessed_at=item["updated_at"]) for s, item in recent]
        result[node["id"]] = dict(level=level, label=LABELS[level], origin="rule_inference", human_reviewed=False,
            scope="LinuxLab 操作表现的自动估计", confidence="中" if level == "proficient" else "低",
            reasons=reasons, next_action=next_action, evidence=refs, behavior=behavior,
            runs_observed=len(records), successful_streak=streak, excluded_version_records=stale,
            fluency=dict(status="recurring_errors" if recurring else "isolated_slip" if episodes else "no_recorded_errors",
                         problem_episodes=episodes, unresolved_episodes=unresolved, recent_runs=len(recent)),
            timing=timing,
            reference_usage=dict(recent_runs=len(recent), supported_runs=support_runs,
                                 recurring=support_runs >= 2, lookups=lookups),
            policy_version=recent[-1][0]["policy_version"] if recent else "linuxlab-mastery-v1",
            updated_at=recent[-1][1]["updated_at"] if recent else None,
            limitations=["规则等级未经真实学习效果校准，不是掌握概率或人工确认。",
                         "相同九关中的重复表现不能证明跨任务迁移或概念理解。"])
    return result
