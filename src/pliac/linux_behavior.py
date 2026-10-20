"""Observable behavior sequences; never infer intent or learning causality.

Operation cursors order shell actions. Equal-cursor checks and lookups need
strictly ordered timestamps; ties remain unknown. Aggregated input patterns do
not contain a full timeline and must not be reconstructed into invented events.
"""
from datetime import datetime


def timestamp(value):
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.timestamp() if parsed.tzinfo else None
    except (ValueError, TypeError, AttributeError):
        return None


def check_before(check, lookup):
    left, right = check["operation_cursor"], lookup["operation_cursor"]
    if left != right:
        return left < right
    a, b = timestamp(check.get("at")), timestamp(lookup.get("at"))
    return a is not None and b is not None and a < b


def stage_behavior(phase, task_id, events, relevant, good, lookups, passed, complete, repair, helped, issue_codes):
    failures = [e for e in events if e["kind"] == "retry" and e.get("issue_code") in issue_codes]
    # Repeated checks of an unchanged problem retain their references, but do
    # not create new episodes or evidence that an attempted correction failed.
    episodes = {}
    for event in failures:
        key = (event.get("issue_code"), event.get("problem_id", event["id"]))
        if event.get("repeat_checks", 0) and key not in episodes:
            continue
        episodes.setdefault(key, event)
    failed_ops = [op for op in relevant if op["exit_code"] != 0]
    verified = bool(passed and good and complete and not repair)
    sequences = []
    for lookup in lookups:
        before = [e for e in episodes.values() if check_before(e, lookup)]
        before_ops = [o for o in failed_ops if o["sequence"] <= lookup["operation_cursor"]]
        after = [e for e in episodes.values() if check_before(lookup, e)]
        after_ops = [o for o in failed_ops if o["sequence"] > lookup["operation_cursor"]]
        later_good = [o for o in good if o["sequence"] > lookup["operation_cursor"]]
        same_errors = sorted({e["issue_code"] for e in before} & {e["issue_code"] for e in after})
        earlier_good = [o for o in good if o["sequence"] <= lookup["operation_cursor"]]
        if not complete or repair:
            status = "uncertain"
        elif verified and later_good:
            status = "corrected_after_reference" if before or before_ops else "reference_then_success"
        elif after or after_ops:
            status = "same_error_after_reference" if same_errors else "difficulty_after_reference"
        elif earlier_good and not later_good:
            status = "review_after_success"
        else:
            status = "awaiting_attempt"
        refs = ["reference:" + str(lookup["sequence"])]
        refs += ["check:" + str(e["id"]) for e in before[-1:] + after[-1:]]
        refs += ["operation:" + str(o["sequence"])
                 for o in before_ops[-1:] + after_ops[-1:] + later_good[-1:] + earlier_good[-1:]]
        if passed:
            refs.append("check:" + str(passed["id"]))
        sequences.append(dict(reference_sequence=lookup["sequence"], source=lookup["source"], topic=lookup["topic"],
            status=status, failure_before=bool(before or before_ops), failure_after=bool(after or after_ops),
            repeated_issue_codes=same_errors, evidence_refs=sorted(set(refs))))
    check_episodes = [dict(issue_code=e["issue_code"], problem_id=e.get("problem_id", e["id"]),
        resolved=bool(verified and passed["id"] > e["id"]
                      and any(o["sequence"] > e["operation_cursor"] for o in good)),
        evidence_refs=["check:" + str(e["id"])]) for e in episodes.values()]
    supported = verified and any(r["operation_cursor"] < max(o["sequence"] for o in good) for r in lookups)
    return dict(phase=phase, task_id=task_id, complete=complete, repaired=repair,
        verified=verified, prompt_observed=helped, sequences=sequences[-20:], sequence_count=len(sequences),
        reference_supported=supported, check_episodes=check_episodes,
        failed_operations=len(failed_ops),
        independent_observed=verified and not helped and not supported,
        completed_at=passed.get("at") if verified else None,
        started_at=_boundary_time(events + relevant, min), observed_at=_boundary_time(events + relevant, max))


def _boundary_time(rows, select):
    valid = [(timestamp(r.get("at")), r.get("at")) for r in rows]
    valid = [(number, value) for number, value in valid if number is not None]
    return select(valid)[1] if valid else None


def copy_facets(ident, phase, events, relevant, good, passed, complete, repair):
    """Artifact-backed details under existing nodes; no new graph or mental cause.

    Only phase 2 grades a backup. Scene facts elsewhere cannot re-grade it.
    A fact is paired with its next backup failure, not arbitrary later actions.
    """
    if ident not in ("cp", "file_integrity") or phase != 2:
        return []
    specs = (("copy.hidden", "隐藏文件完整性", "backup_hidden_present", True),
             ("copy.layout", "目标目录层级", "backup_nested_present", False),
             ("copy.original", "原始资料保留", None, None),
             ("copy.operands", "源与目标角色", None, None))
    verified = bool(passed and good and complete and not repair)
    result = []
    for key, label, fact, expected in specs:
        failures, refs = set(), []
        for event in events:
            if event["kind"] != "retry" or event.get("repeat_checks", 0):
                continue
            matching = False
            if fact and event.get("issue_code") == "backup":
                previous = max((e["operation_cursor"] for e in events if e["id"] < event["id"]
                                and e["kind"] in ("retry", "repair")), default=0)
                recent = [o for o in relevant if previous < o["sequence"] <= event["operation_cursor"]]
                if recent and recent[-1]["facts"].get(fact) is not None:
                    matching = recent[-1]["facts"][fact] is not expected
                    if matching:
                        refs.append("operation:" + str(recent[-1]["sequence"]))
            elif key == "copy.original":
                matching = event.get("issue_code") == "original"
            if matching:
                failures.add(event.get("problem_id", event["id"]))
                refs.append("check:" + str(event["id"]))
        observed = [o for o in relevant if o.get("operand_roles", [])[:2] == ["original", "backup"]]
        if key == "copy.operands":
            # Recognized roles are descriptive, not proof of path understanding.
            status = "observed" if observed else "unknown"
            refs += ["operation:" + str(o["sequence"]) for o in observed]
        elif verified and (not fact or good[-1]["facts"].get(fact) is expected):
            status = "corrected" if failures else "passed"
            refs += ["check:" + str(passed["id"]), "operation:" + str(good[-1]["sequence"])]
        else:
            status = "difficulty" if failures else "unknown"
        result.append(dict(id=key, label=label, phase=phase, status=status,
            failure_episodes=len(failures), evidence_refs=sorted(set(refs))))
    return result
