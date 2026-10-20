"""Auditable LinuxLab diagnostic drafts from bounded observations.

Task failure, process observations, candidate explanations, and learner speech
remain different objects. No inferred mental cause becomes reviewed mastery.
"""
import hashlib
import json

POLICY = "linuxlab-evidence-diagnosis-v3"
INPUT_LABELS = {
    "command_typo": "检测到命令名拼写候选错误", "command_case": "检测到命令名大小写候选错误",
    "command_spacing": "检测到命令与参数分隔问题", "lab_command_typo": "检测到 Lab 子命令拼写问题",
    "option_typo": "检测到选项拼写候选错误", "option_value_missing": "检测到选项缺少取值",
    "missing_operands": "检测到命令缺少必需操作数", "path_missing": "命令失败后未找到所指路径",
    "path_case": "检测到路径大小写候选错误", "path_typo": "检测到路径拼写候选错误",
    "path_base": "检测到相对路径起点候选错误",
}
VERIFY = {
    "ls": "普通 ls 没有显示 .settings，能否据此断定它不存在？你会怎样核对观察范围？",
    "cp": "在无关练习中，backup 已是目录，执行 cp -a notes backup 前后会是什么目录层级？请先画出预测，再观察验证，并解释为何。",
    "file_integrity": "你用哪些观察证明副本包含原目录的隐藏项、子目录及内容，并确认原件仍保留？",
    "relative": "请写出操作时的当前目录，再逐段解释相对路径的起点；若换一个当前目录，目标会改变吗？",
    "syntax": "请拆分命令名、选项和操作数，说明哪个部分有问题，以及怎样用本机帮助核实；一次笔误与不理解有什么不同证据？",
    "config_record": "请解释重复键、错误字段值和未保存修改的区别，并说明怎样根据磁盘文件排除这些可能。",
    "vim": "你如何区分缓冲区已修改、文件已保存和编辑了其他路径？请用一个无关练习文件验证。",
    "log_record": "日志末尾新增心跳时，最近有效业务记录是否改变？你会怎样保证多个字段来自同一条有效记录？",
    "process": "请说明如何核实一个 PID 属于本次目标且当前仍存活，以及为何历史 PID 或日志序号不足以作证。",
    "chmod": "请解释文件的属主、组、其他权限与执行位，再说明为何配置文件和脚本需要不同的最小权限。",
    "tar": "请预测归档成员相对路径与解包目录组合后的路径，并说明怎样确认包内是修改后的最新内容。",
}


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def diagnose(report, activity, rules, graph, reflections=()):
    nodes = {n["id"]: n for n in graph["nodes"]}
    stages = {s["phase"]: s for s in activity["stages"]}
    operations = {o["sequence"]: o for o in report.get("operations", [])}
    available_refs = ({"check:" + str(e["id"]) for e in report["events"]}
                      | {"operation:" + str(i) for i in operations}
                      | {"input:" + p["id"] for p in report.get("input_patterns", [])})
    available_refs |= {prefix + r['id'] for r in report.get('dialogue_evidence', [])
                       for prefix in ('dialogue:', 'dialogue_analysis:')}
    available_refs |= {'reference:' + str(r['sequence']) for r in report.get('reference_lookups', [])}
    cases = []
    for event in report["events"]:
        if event["kind"] != "retry" or event.get("repeat_checks", 0):
            continue
        rule = rules.get(event.get("issue_code"), rules["unknown"])
        concepts = event.get("concepts") or rule["concepts"] or stages[event["phase"]]["concepts"]
        ids = list(dict.fromkeys(n for c in concepts for n in activity["concept_map"].get(c, [])))
        refs = ["check:" + str(event["id"])]
        observations = [rule["observation"]]
        hypotheses = list(rule["hypotheses"])
        # Restrict causal correlation to this stage, after its previous check.
        previous = max((e["operation_cursor"] for e in report["events"]
                        if e["id"] < event["id"] and e["phase"] == event["phase"]
                        and e["kind"] in ("passed", "retry", "repair")), default=0)
        recent = [o for o in operations.values() if o["phase"] == event["phase"]
                  and previous < o["sequence"] <= event["operation_cursor"]]
        for op in recent[-20:]:
            # Alias, functions and compound commands have no command semantics.
            if op.get("command_kind") not in (None, "file", "builtin", "missing"):
                continue
            detail = None
            if event.get("issue_code") == "backup" and op["command"] == "cp":
                if op.get("facts", {}).get("backup_nested_present"):
                    detail = "复制后观察到备份中额外嵌套原件目录；与本次备份检查失败相邻。"
                    hypotheses = ["目标已存在时复制整个源目录，可能多套一层；也需排除后续移动。"]
                elif op.get("plain_star_excludes_hidden") and not op.get("facts", {}).get("backup_hidden_present"):
                    detail = "记录到不含隐藏项的星号选择范围，且复制后的观察中未见备份隐藏项。"
                    hypotheses = ["通配选择范围可能遗漏隐藏项；需解释展开规则并排除后续删除。"]
            if event.get("issue_code", "").startswith("config_") and op["command"] == "vim":
                detail = ("Vim 结束后检测到磁盘配置变化；字段检查仍未通过。" if op.get("config_changed_since_observation")
                          else "观察到 Vim 调用，但没有足够证据确认保存；未记录编辑器内部操作。")
            if detail:
                observations.append(detail)
                refs.append("operation:" + str(op["sequence"]))
        later = next((e for e in report["events"] if e["id"] > event["id"] and e["phase"] == event["phase"] and e["kind"] == "passed"), None)
        if later:
            refs.append("check:" + str(later["id"]))
            observations.append("后续同关检查通过，说明本次检查项已满足；不能据此确定早先原因或独立掌握。")
        same = [e for e in report["events"] if e["kind"] == "retry" and e["phase"] == event["phase"]
                and e.get("problem_id") == event.get("problem_id")]
        cases.append(dict(id="check-" + str(event["id"]), phase=event["phase"], phases=[event["phase"]], node_ids=ids,
                          observations=observations, evidence_refs=refs, hypotheses=hypotheses,
                          outcome="artifact_corrected" if later else "awaiting_verification",
                          check_attempts=len(same), episodes=1, prompt_level=event["prompt_level"]))
    for p in report.get("input_patterns", []):
        concept = p["concept"]
        # Input grammar issues also implicate syntax; path issues implicate
        # relative paths, without inferring every prerequisite is misunderstood.
        ids = activity["concept_map"].get(concept, [])
        if p["kind"].startswith(("command_", "option_", "lab_")) or p["kind"] == "missing_operands":
            ids = list(dict.fromkeys(["syntax", *ids]))
        cases.append(dict(id=p["id"], phase=p["phase"], phases=p["phases"], node_ids=ids,
                          observations=[INPUT_LABELS.get(p["kind"], "检测到有限输入问题") + "；目标命令：" + p["command"]],
                          evidence_refs=["input:" + p["id"]],
                          hypotheses=["可能是一次输入笔误，也可能对语法或路径理解不清，需要学习者解释及新任务核验。"],
                          outcome="related_input_corrected" if p["resolved_episodes"] else "awaiting_verification",
                          check_attempts=p["attempts"], episodes=p["episodes"], prompt_level=None))
    from .linux_operation_cases import cases as operation_cases
    cases.extend(operation_cases(report, nodes, cases))
    from .linux_dialogue import cases as dialogue_cases
    cases.extend(dialogue_cases(report, activity, nodes, cases))
    for case in cases:
        case["node_ids"] = [n for n in case["node_ids"] if n in nodes]
        case["verification_questions"] = [dict(node_id=n, question=VERIFY.get(n, nodes[n]["check_question"])) for n in case["node_ids"]]
        case["prerequisite_candidates"] = sorted({e["source"] for e in graph["edges"]
                                                  if e["type"] == "prerequisite" and e["target"] in case["node_ids"]})
        answers = [r for r in reflections if r["case_id"] == case["id"]]
        case["learner_explanations"] = answers
        case["review_status"] = "draft"
        case["diagnosis_status"] = "uncertain"
        case["quality"] = {"traceable": bool(case["evidence_refs"]) and set(case["evidence_refs"]) <= available_refs, "mapped": bool(case["node_ids"]),
                           "alternatives_present": bool(case["hypotheses"]), "verification_defined": bool(case["verification_questions"]),
                           "has_learner_explanation": bool(answers), "has_dialogue": bool(case.get('dialogue_context')), "human_reviewed": False,
                           "eligible_for_mastery": False}
        case["next_action"] = "回答核验问题，完成换数据的独立复测后交教师复核；先修候选仅供排查。"
    return dict(policy_version=POLICY, cases=cases, review_status="draft",
                boundary="这是可追溯的诊断草稿。检查通过、退出码、重复尝试和自动关联均不能单独证明理解或掌握。",
                coverage=dict(tracking_enabled=report.get("tracking_enabled", False),
                              retained_operations=len(operations), total_operations=report.get("operation_total", 0),
                              retained_dialogue=len(report.get('dialogue_evidence', [])), total_dialogue=report.get('dialogue_total', 0),
                              truncated=report.get("operation_total", 0) > len(operations)),
                collection_limits=["未采集原生 stderr、按键或 Vim 内部过程。", "组合命令、别名及未识别语法不作原因推断。",
                                   "同一现场重复检查不算多次独立知识错误。", "缺失过程记录表示未知，不表示未操作。",
                                   "对话候选引用学习者原话；AI 回答作为帮助背景，未经过正确性复核。",
                                   "对话只保留最近一百轮；提问次数不等于知识错误次数，自述报错不等于已观察到的报错。"])
