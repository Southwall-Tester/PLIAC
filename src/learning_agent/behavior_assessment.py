"""Interpretable dimensions and time-ordered follow-up over persisted Lab runs."""
from datetime import datetime


def _time(value):
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.timestamp() if parsed.tzinfo else None
    except (ValueError, TypeError, AttributeError):
        return None


def summarize(records, timing):
    recent = records[-3:]
    latest = recent[-1][1] if recent else {}
    stages = latest.get("behavior", [])
    sequences = [dict(s, phase=b["phase"], task_id=b["task_id"])
                 for b in stages for s in b["sequences"]]
    errors = {}
    for snapshot, item in recent:
        for stage in item.get("behavior", []):
            for episode in stage["check_episodes"]:
                code = episode["issue_code"]
                data = errors.setdefault(code, dict(issue_code=code, episodes=0, runs=set(), resolved=0))
                data["episodes"] += 1
                data["resolved"] += int(episode["resolved"])
                data["runs"].add(snapshot["lab_session_id"])
    error_patterns = [dict(data, runs=len(data["runs"])) for _, data in sorted(errors.items())]
    recurring = any(e["episodes"] >= 2 for e in error_patterns)
    current_errors = [e for b in stages for e in b["check_episodes"]]
    unresolved = any(not e["resolved"] for e in current_errors) or any(
        b.get('unresolved_input_episodes', 0) or (b['failed_operations'] and not b['verified']) for b in stages)
    # A subsequent run must actually start after the earlier observations. Sync
    # order or a changed scene name is not evidence of retention or transfer.
    followups = []
    for stage in stages:
        start = _time(stage.get("started_at"))
        if not stage["independent_observed"] or start is None:
            continue
        candidates = []
        for snapshot, item in records[:-1]:
            for old in item.get("behavior", []):
                end = _time(old.get("observed_at"))
                if (old["task_id"] != stage["task_id"] or end is None or end >= start
                        or not stage.get('contract_hash') or old.get('contract_hash') != stage['contract_hash']
                        or not old.get("complete") or old.get("repaired")):
                    continue
                needed_support = old["prompt_observed"] or old.get('reference_supported') or any(s["status"] in (
                    "corrected_after_reference", "reference_then_success", "same_error_after_reference",
                    "difficulty_after_reference") for s in old["sequences"])
                had_difficulty = bool(old["check_episodes"] or old["failed_operations"]
                                      or old.get('input_problem_episodes', 0) >= 2)
                if needed_support or had_difficulty:
                    candidates.append((end, snapshot, old))
        if candidates:
            end, snapshot, old = max(candidates, key=lambda c: (c[0], c[1]["binding_id"]))
            followups.append(dict(task_id=stage["task_id"], phase=stage["phase"],
                prior_binding_id=snapshot["binding_id"], prior_raw_digest=snapshot["raw_digest"],
                prior_observed_at=old["observed_at"], completed_at=stage["completed_at"],
                gap_hours=round((start - end) / 3600, 2),
                status="independent_recovery" if stage["check_episodes"] or stage["failed_operations"]
                       or stage.get('input_problem_episodes', 0)
                       else "independent_followup"))
    status = ("independent_followup" if any(f["status"] == "independent_followup" for f in followups)
              else "independent_recovery" if followups else
              "pending_independent" if any(s["status"] in ("corrected_after_reference", "reference_then_success",
                  "same_error_after_reference", "difficulty_after_reference") for s in sequences)
              or latest.get("outcome") in ("assisted", "difficulty", "recovered") else "not_verified")
    # A positive phase cannot mask another unresolved phase of the same node.
    if latest.get("outcome") in ("difficulty", "insufficient", "assisted", "referenced"):
        status = "pending_independent" if stages else "not_verified"
    outcome = latest.get("outcome")
    correct = ("尚无直接证据" if not latest else "相关操作或检查仍存在问题" if outcome == "difficulty" else
               "证据不足" if outcome == "insufficient" else "相关操作与检查通过")
    independent = ("证据不足" if outcome in (None, "insufficient") else
                   "借助提示完成" if outcome == "assisted" else
                   "参考资料完成" if outcome == "referenced" else
                   "完成情况尚待验证" if outcome == "difficulty" else
                   "未记录到相关帮助；仍受采集范围限制")
    recovery = ("尚无过程记录" if not stages else "仍有操作或检查问题待修正" if unresolved else
                "错误后已通过检查" if current_errors or any(b['failed_operations'] for b in stages) else
                "记录到已修正的输入问题" if any(b.get('input_problem_episodes', 0) for b in stages) else
                "未记录到操作或检查错误")
    speed = ("比个人基线更费时；不据此扣减正确性" if any(t["comparison"].startswith("slower") for t in timing)
             else "接近个人近期表现" if any(t["comparison"] == "typical" for t in timing)
             else "记录含长空档，不能判断快慢" if any(t["comparison"] == "interrupted" for t in timing)
             else "可比记录不足，暂不判断快慢")
    retention = {"independent_followup": "后续同类任务已无辅助通过；迁移尚未验证",
                 "independent_recovery": "后续同类任务自行纠错后通过；仍需巩固",
                 "pending_independent": "等待后续独立复测", "not_verified": "尚未验证保持与迁移"}[status]
    return dict(sequences=sequences, sequence_count=sum(b.get('sequence_count', len(b['sequences'])) for b in stages),
        error_patterns=error_patterns, recurring_check_errors=recurring,
        followup=dict(status=status, records=followups, transfer_verified=False),
        facets=latest.get("facets", []),
        dimensions=[dict(id=key, label=label, summary=summary) for key, label, summary in (
            ("correctness", "正确性", correct), ("independence", "独立性", independent),
            ("recovery", "纠错能力", recovery), ("fluency", "操作流畅度", speed),
            ("retention", "保持与迁移", retention))])
