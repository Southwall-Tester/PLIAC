"""Bounded estimates of LinuxLab performance, never a fabricated human review.

The frozen course owns node IDs. Check results need matching observed operations
before they support a positive estimate. One run contributes at most one result
per node, regardless of checks, phases, or repeated syncs.
"""
from datetime import datetime

from learning_agent.course_graph import _fingerprint
from .linux_diagnosis import digest
from .linux_behavior import stage_behavior, copy_facets

POLICY = "linuxlab-mastery-v3"
REFERENCE_TOPICS = frozenset(('basics navigation glob ls pwd cd mkdir cp mv rm cat head tail '
                              'tar chmod top ps id grep find du df vim').split())
REFERENCE_SOURCES = frozenset(('notes', 'lab_help', 'command_help', 'man', 'shell_help'))


def reference_nodes(topic):
    if topic == 'navigation':
        return {'cwd', 'cd', 'absolute', 'relative'}
    if topic == 'basics':
        return {'syntax'}
    if not topic:
        return set()
    return {topic} | {n for n, commands in COMMANDS.items() if topic in commands}
# These are explicit assessment mappings for the authored Linux course, not
# inferred graph edges. Abstract concepts without observable support stay unknown.
COMMANDS = {
    "cwd": {"pwd"}, "cd": {"cd"}, "ls": {"ls"}, "mkdir": {"mkdir"},
    "cp": {"cp"}, "mv": {"mv"}, "rm": {"rm"}, "tar": {"tar"},
    "cat": {"cat"}, "tail": {"tail"}, "vim": {"vim"}, "identity": {"id"},
    "chmod": {"chmod"}, "ps": {"ps"}, "top": {"top"},
    "process": {"ps", "top"}, "file_integrity": {"cp"},
}
# A failed check may involve several alternative causes. Only these directly
# checked concepts receive a difficulty estimate, not every stage/prerequisite.
ISSUES = {
    "location": {"cwd", "relative"}, "directory": {"mkdir"}, "beacon": {"ls"},
    "backup": {"cp", "file_integrity"}, "original": {"file_integrity"},
    "move": {"mv"}, "cleanup": {"glob"}, "preserve": {"glob", "file_integrity"},
    "seal": {"tar"}, "extraction": {"tar"}, "log_record": {"log_record"},
    "config_format": {"config_record"}, "config_duplicate": {"config_record"},
    "config_value": {"config_record"}, "config_keys": {"config_record"},
    "permissions": {"chmod", "file_permissions"}, "receipt": {"script"},
    "process_identity": {"process"}, "archive_layout": {"tar"},
    "archive_content": {"tar", "file_integrity"}, "archive_permissions": {"file_permissions"},
    "archive_format": {"tar"},
}


def phase_timing(report, phase):
    """Estimate intervals between observable actions, not attention or focus.

    Gaps over two minutes are explicitly unknown time and are excluded from
    within-person speed comparisons. This never restricts the learner's pace.
    """
    events = [e for e in report["events"] if e["phase"] == phase]
    ops = [o for o in report["operations"] if o["phase"] == phase]
    previous = next((e for e in report["events"] if e["phase"] == phase - 1 and e["kind"] == "passed"), None)
    rows = events + ops + ([previous] if previous else [])
    times = []
    for row in rows:
        try:
            time = datetime.fromisoformat(row["at"].replace("Z", "+00:00"))
            if time.tzinfo is None:
                raise ValueError("Time zone required")
            times.append(time.timestamp())
        except (KeyError, TypeError, ValueError, AttributeError):
            return dict(phase=phase, available=False, reason="时间记录缺失或格式无效。")
    times = sorted(set(times))
    if len(times) < 2 or not report.get("tracking_enabled") or report["operation_total"] != len(report["operations"]):
        return dict(phase=phase, available=False, reason="过程记录不足，无法估计处理时间。")
    gaps = [b - a for a, b in zip(times, times[1:])]
    return dict(phase=phase, available=True, completed=any(e["kind"] == "passed" for e in events),
                elapsed_seconds=round(times[-1] - times[0], 1),
                continuous_seconds=round(sum(g for g in gaps if g <= 120), 1),
                unobserved_seconds=round(sum(g for g in gaps if g > 120), 1),
                long_gaps=sum(g > 120 for g in gaps), observations=len(times),
                reason="只记录操作之间的间隔；长于 120 秒的空档单列，不推断思考、离开或不理解。")


def assess_run(report, binding, graph, activity):
    """Pure deterministic snapshot. References point into an immutable raw report."""
    observations, behaviors, facets = {}, {}, {}
    references = report.get('reference_lookups', [])
    complete = (report.get("tracking_enabled") is True
                and report["operation_total"] == len(report["operations"])
                and report.get('reference_total', len(references)) == len(references))
    for stage in activity["stages"]:
        phase = stage["phase"]
        events = [e for e in report["events"] if e["phase"] == phase]
        ops = [o for o in report["operations"] if o["phase"] == phase]
        stage_references = [r for r in references if r['phase'] == phase and not r['after_completion']]
        if not events and not ops:
            continue
        passed = next((e for e in events if e["kind"] == "passed"), None)
        repair = any(e["kind"] == "repair" for e in events)
        helped = any(e["kind"] in ("hint", "tutor") or e["prompt_level"] > 0 for e in events)
        for ident in stage["node_ids"]:
            refs = ["check:" + str(e["id"]) for e in events]
            relevant = [o for o in ops if o["command"] in COMMANDS.get(ident, ())
                        and o.get("command_kind") in ("file", "builtin") and o.get("known_options") is True]
            good = [o for o in relevant if o["exit_code"] == 0
                    and passed and o["sequence"] <= passed["operation_cursor"]]
            if ident == "file_integrity":
                good = [o for o in good if o["facts"].get("backup_hidden_present") is True
                        and o["facts"].get("backup_nested_present") is False]
            failed_checks = [e for e in events if e["kind"] == "retry"
                             and ident in ISSUES.get(e.get("issue_code"), ())]
            # A successful command before a later failed check is not a repair.
            correction_cursor = max([e["operation_cursor"] for e in failed_checks]
                                    + [o["sequence"] for o in relevant if o["exit_code"] != 0], default=-1)
            corrected_good = [o for o in good if o["sequence"] > correction_cursor]
            lookups = [r for r in stage_references if ident in reference_nodes(r['topic'])]
            # A lookup after the last successful relevant action is verification/
            # review, not evidence that the earlier action depended on a reference.
            support = [r for r in lookups if corrected_good and complete and not repair
                       and r['operation_cursor'] < max(o['sequence'] for o in corrected_good)]
            refs += ['reference:' + str(r['sequence']) for r in lookups]
            # Re-running the same unchanged check is one episode.
            issues = {e.get("problem_id", e["id"]) for e in events
                      if e["kind"] == "retry" and not e.get("repeat_checks", 0)
                      and ident in ISSUES.get(e.get("issue_code"), ())}
            refs += ["operation:" + str(o["sequence"]) for o in relevant]
            negative = bool(issues) or any(o["exit_code"] != 0 for o in relevant)
            if passed and corrected_good and complete and not repair:
                outcome = "assisted" if helped else "referenced" if support else "recovered" if negative else "success"
                reason = ("相关操作与关卡检查通过；过程中使用过提示或助教。" if helped else
                          "相关操作与关卡检查通过；成功操作前查阅过对应资料，本次不计作无辅助成功。" if support else
                          "出现问题后完成了相关操作并通过检查；建议换周目复测。" if negative else
                          "记录到相关命令成功执行且关卡通过，未记录到本关提示或修复。")
            elif negative and not passed:
                outcome, reason = "difficulty", "相关检查或命令仍未通过，需要针对该知识点练习。"
            else:
                outcome = "insufficient"
                reason = ("本关使用过自动修复，检查通过不能用于提升掌握估计。" if repair else
                          "过程记录关闭或不完整，不能确认相关操作。" if not complete else
                          "目前只有关卡结果或间接观察，缺少该知识点的直接操作依据。")
            observations.setdefault(ident, []).append(dict(phase=phase, outcome=outcome, reason=reason,
                evidence_refs=sorted(set(refs)), issues=len(issues), prompt_observed=helped, repaired=repair,
                reference_support=[r['sequence'] for r in support]))
            behaviors.setdefault(ident, []).append(stage_behavior(phase, stage["task_id"], events,
                relevant, corrected_good, lookups, passed, complete, repair, helped,
                {code for code, ids in ISSUES.items() if ident in ids}))
            facets.setdefault(ident, []).extend(copy_facets(ident, phase, events, relevant,
                corrected_good, passed, complete, repair))
    # Input mistakes are relevant only to the observed command/syntax, not every
    # possible path concept or prerequisite. An unresolved episode can downgrade.
    input_signals = {}
    for pattern in report.get("input_patterns", []):
        ids = {n for n, commands in COMMANDS.items() if pattern["command"] in commands
               and n not in ("process", "file_integrity")}
        if pattern["kind"].startswith(("command_", "option_", "lab_")) or pattern["kind"] == "missing_operands":
            ids.add("syntax")
        for ident in ids:
            input_signals.setdefault(ident, []).append({k: pattern[k] for k in
                ("id", "kind", "command", "phase", "episodes", "attempts", "resolved_episodes", "active")})
            observations.setdefault(ident, []).append(dict(phase=pattern["phase"],
                outcome="difficulty" if pattern.get("active") and pattern["episodes"] >= 2 else "insufficient",
                reason="仍有相关输入问题未修正。" if pattern.get("active") else "输入问题已修正，需要新的操作与检查验证。",
                evidence_refs=["input:" + pattern["id"]], issues=pattern["episodes"],
                prompt_observed=False, repaired=False))
    nodes = {}
    # A failure elsewhere in the same run takes priority over a passed phase.
    for node in graph["nodes"]:
        rows = observations.get(node["id"], [])
        if not rows:
            continue
        outcomes = {r["outcome"] for r in rows}
        outcome = next(k for k in ("difficulty", "assisted", "referenced", "recovered", "success", "insufficient") if k in outcomes)
        signals = input_signals.get(node["id"], [])
        episodes = sum(p["episodes"] for p in signals)
        for behavior in behaviors.get(node['id'], []):
            behavior['contract_hash'] = binding['contract_hash']
            phase_signals = [p for p in signals if p['phase'] == behavior['phase']]
            behavior['input_problem_episodes'] = sum(p['episodes'] for p in phase_signals)
            behavior['unresolved_input_episodes'] = sum(p['episodes'] - p['resolved_episodes']
                                                       for p in phase_signals if p['active'])
            if behavior['unresolved_input_episodes']:
                behavior['independent_observed'] = False
        if outcome == "success" and episodes >= 2:
            outcome = "recovered"
            rows.append(dict(phase=signals[-1]["phase"], outcome=outcome,
                reason="相关输入问题在多个尝试段反复出现；即使最终通过，当前操作仍需巩固。",
                evidence_refs=["input:" + p["id"] for p in signals], issues=episodes,
                prompt_observed=False, repaired=False))
        timings = [phase_timing(report, phase) for phase in sorted({r["phase"] for r in rows})]
        support_ids = {ident for r in rows for ident in r.get('reference_support', [])}
        node_references = [dict(r, use='before_success' if r['sequence'] in support_ids else 'lookup_only')
                           for r in references if node['id'] in reference_nodes(r['topic'])]
        nodes[node["id"]] = dict(node_fingerprint=_fingerprint(node), outcome=outcome,
            observation_key=digest(dict(basis=[{k: ([ref for ref in v if not ref.startswith('reference:')]
                                                        if k == 'evidence_refs' else v)
                                               for k, v in r.items() if k != 'reference_support' or v}
                                               for r in rows if r["outcome"] == outcome], input_signals=signals)),
            reasons=list(dict.fromkeys(r["reason"] for r in rows)), phases=sorted({r["phase"] for r in rows}),
            evidence_refs=sorted({ref for r in rows for ref in r["evidence_refs"]}
                                 | {'reference:' + str(r['sequence']) for r in node_references}),
            limitations=["未记录到提示不等于已验证独立完成；这里只估计本实训内的操作表现。"],
            observations=rows, input_signals=signals, timing=timings, references=node_references,
            behavior=behaviors.get(node["id"], []), facets=facets.get(node["id"], []))
    return dict(policy_version=POLICY, origin="rule_inference", human_reviewed=False,
                course_id=graph["id"], course_version=graph["version"], student_id=binding["student_id"],
                binding_id=binding["binding_id"], lab_session_id=report["lab_session_id"],
                raw_digest=digest(report), nodes=nodes)
