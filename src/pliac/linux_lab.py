"""Local native LinuxLab sessions, frozen course bindings and evidence imports."""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
import uuid

from learning_agent.course_graph import CourseGraphError, _atomic_json, _fingerprint, _text, safe_id
from .linux_diagnosis import diagnose, digest
from .linux_mastery import assess_run
from . import linux_dialogue
from .workspace import empty_workspace

SCENES = {"space": "太空站", "ocean": "深海站", "museum": "博物馆", "anime": "动漫主题", "ai": "AI 自选主题（需要 LinuxLab 本地模型配置）"}
UUID = re.compile(r"[0-9a-f]{32}\Z")


def read(path):
    if path.is_symlink() or path.stat().st_size > 4_000_000:
        raise CourseGraphError("实训文件无效或超过容量。", 409)
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, UnicodeError) as exc:
        raise CourseGraphError("实训文件格式无效。", 409) from exc


def linux_path(path):
    path = Path(path).resolve()
    if os.name == "nt":
        if len(path.drive) != 2 or path.drive[1] != ":":
            raise CourseGraphError("WSL 接入需要本机盘符路径。")
        return "/mnt/" + path.drive[0].lower() + path.as_posix()[2:]
    return str(path)


class LinuxLab:
    def __init__(self, store, lab_root=None):
        self.store = store
        self.root = Path(lab_root or os.environ.get("PLIAC_LINUXLAB_ROOT", str(Path.home() / "Desktop/LinuxLab"))).resolve()
        self.runs = store.output_dir / "linuxlab/runs"

    def graph(self, mode="auto"):
        if mode not in ("auto", "preview", "published"):
            raise CourseGraphError("实训模式无效。")
        published = self.store.load_graph()
        mode = ("published" if published else "preview") if mode == "auto" else mode
        graph = self.store.load_graph("draft") if mode == "preview" else self.store._require_graph()
        return graph, mode, self.activity(graph)

    @staticmethod
    def activity(graph):
        item = next((a for a in graph.get("activities", []) if a.get("engine") == "linuxlab"), None)
        if not item:
            raise CourseGraphError("此课程未配置 LinuxLab。", 404)
        if any(n not in {x["id"] for x in graph["nodes"]} for s in item["stages"] for n in s["node_ids"]):
            raise CourseGraphError("实训关联知识点缺失，请教师修复课程映射。", 409)
        return item

    def descriptor(self, activity):
        entry = self.root / "pliac_bridge.py"
        if not entry.is_file():
            raise CourseGraphError("未找到 LinuxLab 接入模块；请配置 PLIAC_LINUXLAB_ROOT。", 409)
        try:
            result = subprocess.run([sys.executable, "-X", "utf8", str(entry), "--describe"], cwd=self.root,
                                    capture_output=True, text=True, encoding="utf-8", timeout=12)
            value = json.loads(result.stdout) if result.returncode == 0 else {}
        except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
            raise CourseGraphError("LinuxLab 任务契约读取失败，请检查安装。", 409) from exc
        for key in ("contract_version", "contract_hash"):
            if value.get(key) != activity.get(key):
                raise CourseGraphError("LinuxLab 与课程任务契约不匹配，已阻止启动；需先核验映射。", 409)
        expected = [{k: s[k] for k in ("phase", "task_id", "concepts")} for s in activity["stages"]]
        if value.get("schema") != 1 or value.get("course_id") != activity["lab_course_id"] or value.get("stages") != expected:
            raise CourseGraphError("LinuxLab 关卡映射不匹配。", 409)
        return value

    def view(self, student, mode="auto"):
        safe_id(student, "匿名编号")
        graph, mode, activity = self.graph(mode)
        try:
            self.descriptor(activity)
            ready, notice = True, "LinuxLab 任务契约与课程映射一致。"
        except CourseGraphError as exc:
            ready, notice = False, str(exc)
        sessions = []
        if self.runs.exists():
            for folder in self.runs.iterdir():
                if UUID.fullmatch(folder.name) and not folder.is_symlink() and (folder / "binding.json").is_file():
                    b = read(folder / "binding.json")
                    if b["student_id"] == student and b["mode"] == mode:
                        summary = read(folder / "import.json") if (folder / "import.json").is_file() else {}
                        sessions.append({k: b[k] for k in ("binding_id", "created_at", "course_version", "mode", "scene")} | {
                            "phases_passed": summary.get("phases_passed", 0), "synced": bool(summary),
                            "report_available": (folder / "telemetry.json").is_file(),
                            "diagnostic_cases": len(summary.get("diagnosis", {}).get("cases", []))})
        return dict(course={"id": graph["id"], "title": graph["title"], "version": graph["version"]},
                    mode=mode, ready=ready, notice=notice, activity=activity, scenes=SCENES,
                    assessments=self.assessments(graph, student, mode),
                    nodes=[{k: n[k] for k in ("id", "title")} for n in graph["nodes"]],
                    runs=sorted(sessions, key=lambda x: x["created_at"], reverse=True))

    def assessments(self, graph, student, mode):
        if mode != "published":
            return {}
        learner = self.store.load_learner(student, graph)
        return {ident: state["auto_assessment"] for ident, state in learner["states"].items() if "auto_assessment" in state}

    def directory(self, binding_id):
        if not isinstance(binding_id, str) or not UUID.fullmatch(binding_id):
            raise CourseGraphError("周目编号无效。")
        folder = self.runs / binding_id
        if folder.resolve() != folder or not (folder / "binding.json").is_file():
            raise CourseGraphError("实训周目不存在。", 404)
        return folder

    def bound(self, binding_id, student):
        safe_id(student, "匿名编号")
        folder = self.directory(binding_id)
        b = read(folder / "binding.json")
        if b["student_id"] != student or b["course_id"] != self.store.load_graph("draft")["id"]:
            raise CourseGraphError("实训周目与当前学习者或课程不符。", 409)
        return folder, b

    def create(self, payload):
        student = safe_id(payload.get("student_id"), "匿名编号")
        graph, mode, activity = self.graph(payload.get("mode", "auto"))
        if payload.get("course_version") != graph["version"]:
            raise CourseGraphError("课程已变化，请刷新后创建周目。", 409)
        scene = payload.get("scene", "space")
        if scene not in SCENES:
            raise CourseGraphError("请选择已提供的实训情景。")
        descriptor = self.descriptor(activity)
        binding_id = uuid.uuid4().hex
        folder = self.runs / binding_id
        b = dict(schema=1, binding_id=binding_id, student_id=student, course_id=graph["id"],
                 course_version=graph["version"], mode=mode, scene=scene,
                 contract_version=activity["contract_version"], contract_hash=activity["contract_hash"],
                 created_at=self.store._stamp(), report_path=linux_path(folder / "telemetry.json"))
        with self.store._writer():
            folder.mkdir(parents=True, exist_ok=False)
            _atomic_json(folder / "graph.json", graph)
            _atomic_json(folder / "descriptor.json", descriptor)
            _atomic_json(folder / "binding.json", b)
        return self.session(binding_id, student)

    def command(self, folder):
        args = ["python3", linux_path(self.root / "pliac_bridge.py"), "--manifest", linux_path(folder / "binding.json")]
        if os.name == "nt":
            distro = os.environ.get("PLIAC_LINUXLAB_DISTRO", "Ubuntu")
            args = ["wsl.exe", "-d", distro, "--", *args]
            # Display is PowerShell syntax, not a command evaluated by the server.
            display = "& " + " ".join("'" + arg.replace("'", "''") + "'" for arg in args)
        else:
            display = shlex.join(args)
        return args, display

    def session(self, binding_id, student):
        folder, b = self.bound(binding_id, student)
        graph = read(folder / "graph.json")
        summary = read(folder / "import.json") if (folder / "import.json").is_file() else {}
        return dict(binding=b, launch_command=self.command(folder)[1],
                    native_launch_available=os.name == "nt", activity=self.activity(graph),
                    assessments=self.assessments(graph, student, b["mode"]),
                    summary=summary, reflections=read(folder / "reflections.json") if (folder / "reflections.json").is_file() else [],
                    raw_report=read(folder / "raw" / (summary["raw_digest"] + ".json")) if summary else None,
                    nodes=[{k: n[k] for k in ("id", "title")} for n in graph["nodes"]])

    def launch(self, binding_id, student):
        folder, b = self.bound(binding_id, student)
        self.descriptor(self.activity(read(folder / "graph.json")))
        if os.name != "nt":
            raise CourseGraphError("请在本机终端执行页面提供的启动命令。", 409)
        try:
            subprocess.Popen(self.command(folder)[0], creationflags=subprocess.CREATE_NEW_CONSOLE)
        except OSError as exc:
            raise CourseGraphError("终端启动失败，可复制页面命令手动启动。", 409) from exc
        return dict(launched=True, notice="已请求打开 WSL 终端；若窗口退出，请复制启动命令到 PowerShell 查看环境错误。")

    def validate_report(self, report, b, activity):
        if not isinstance(report, dict):
            raise CourseGraphError("实训报告格式无效。")
        allowed = {"schema", "binding_id", "course_id", "course_version", "student_id", "mode", "contract_version", "contract_hash",
                   "lab_session_id", "events", "operations", "input_patterns", "tracking_enabled", "operation_total",
                   "phases_passed", "completed", "validation_scope", "reference_lookups", "reference_total",
                   "dialogue_evidence", "dialogue_analysis", "dialogue_total"}
        if set(report) - allowed:
            raise CourseGraphError("报告含白名单以外的字段，未导入。")
        for key in ("schema", "binding_id", "course_id", "course_version", "student_id", "mode", "contract_version", "contract_hash"):
            if report.get(key) != b[key]:
                raise CourseGraphError("报告与冻结的课程、学习者或任务契约不符。", 409)
        _text(report.get("lab_session_id"), "Lab 周目", 80)
        events = report.get("events")
        if not isinstance(events, list) or len(events) > 10000:
            raise CourseGraphError("实训事件格式或容量无效。")
        cursor, passed = 0, []
        for e in events:
            if (not isinstance(e, dict) or type(e.get("id")) is not int or e["id"] <= cursor
                    or type(e.get("phase")) is not int or e["phase"] not in range(1, 10)
                    or e.get("kind") not in ("passed", "retry", "hint", "tutor", "repair")
                    or type(e.get("prompt_level")) is not int or e["prompt_level"] not in range(4)
                    or type(e.get("operation_cursor")) is not int or e["operation_cursor"] < 0):
                raise CourseGraphError("实训事件字段无效。")
            if set(e) - {"id", "phase", "kind", "at", "prompt_level", "operation_cursor", "issue_code", "concepts", "problem_id", "repeat_checks"}:
                raise CourseGraphError("检查事件包含未允许的字段。")
            _text(e.get("at"), "事件时间", 80)
            if e["phase"] != len(passed) + 1:
                raise CourseGraphError("关卡检查序列不一致。", 409)
            if e["kind"] == "passed":
                passed.append(e["phase"])
            if e["kind"] == "retry":
                _text(e.get("issue_code"), "检查类别", 60)
                if (not isinstance(e.get("concepts"), list) or any(c not in activity["concept_map"] for c in e["concepts"])
                        or type(e.get("problem_id")) is not int or type(e.get("repeat_checks")) is not int
                        or e["repeat_checks"] < 0):
                    raise CourseGraphError("失败检查的概念引用无效。")
            cursor = e["id"]
        if report.get("phases_passed") != len(passed) or report.get("completed") is not (len(passed) == 9):
            raise CourseGraphError("关卡完成摘要与检查事件不一致。", 409)
        for field, limit in (("operations", 2000), ("input_patterns", 200)):
            values = report.get(field)
            if not isinstance(values, list) or len(values) > limit or any(not isinstance(x, dict) for x in values):
                raise CourseGraphError("过程观察格式或容量无效。")
        sequence = 0
        for op in report["operations"]:
            if (type(op.get("sequence")) is not int or op["sequence"] <= sequence
                    or type(op.get("phase")) is not int or op["phase"] not in range(1, 10)
                    or type(op.get("exit_code")) is not int or op["exit_code"] not in range(256)
                    or not isinstance(op.get("facts"), dict)):
                raise CourseGraphError("操作观察字段无效。")
            if set(op) - {"sequence", "at", "phase", "command", "exit_code", "flags", "operand_roles", "known_options", "facts",
                          "plain_star_excludes_hidden", "config_changed_since_observation", "command_kind"}:
                raise CourseGraphError("操作观察包含未允许的字段。")
            if set(op["facts"]) - {"backup_hidden_present", "backup_nested_present"} or any(type(v) is not bool for v in op["facts"].values()):
                raise CourseGraphError("现场观察字段无效。")
            _text(op.get("command"), "观察命令", 40)
            sequence = op["sequence"]
        for p in report["input_patterns"]:
            if (p.get("concept") not in activity["concept_map"] or type(p.get("phase")) is not int or p["phase"] not in range(1, 10)
                    or not isinstance(p.get("phases"), list) or any(type(v) is not int or v not in range(1, 10) for v in p["phases"])
                    or any(type(p.get(k)) is not int or p[k] < 0 for k in ("attempts", "episodes", "resolved_episodes"))):
                raise CourseGraphError("输入问题字段无效。")
            if type(p.get("active")) is not bool or p["resolved_episodes"] > p["episodes"]:
                raise CourseGraphError("输入问题的修正状态无效。")
            if set(p) - {"id", "kind", "command", "concept", "phase", "phases", "attempts", "episodes", "resolved_episodes", "active", "at", "operation_cursor"}:
                raise CourseGraphError("输入问题包含未允许的字段。")
            for key in ("id", "kind", "command"):
                _text(p.get(key), "输入问题标识", 80)
        if type(report.get("operation_total")) is not int or report["operation_total"] < sequence:
            raise CourseGraphError("操作观察计数无效。")
        from .linux_mastery import REFERENCE_TOPICS, REFERENCE_SOURCES
        references = report.get('reference_lookups', [])
        if not isinstance(references, list) or len(references) > 2000:
            raise CourseGraphError("查阅记录格式或容量无效。")
        cursor = 0
        for ref in references:
            if (not isinstance(ref, dict) or set(ref) != {'sequence', 'at', 'phase', 'source', 'topic', 'operation_cursor', 'after_completion'}
                    or type(ref.get('sequence')) is not int or ref['sequence'] <= cursor
                    or type(ref.get('phase')) is not int or ref['phase'] not in range(1, 10)
                    or not isinstance(ref.get('source'), str) or ref['source'] not in REFERENCE_SOURCES
                    or not isinstance(ref.get('topic'), str) or ref['topic'] not in REFERENCE_TOPICS | {''}
                    or type(ref.get('operation_cursor')) is not int or not 0 <= ref['operation_cursor'] <= report['operation_total']
                    or type(ref.get('after_completion')) is not bool):
                raise CourseGraphError("查阅记录字段无效。")
            _text(ref['at'], '查阅时间', 80)
            cursor = ref['sequence']
        total = report.get('reference_total', 0)
        if (type(total) is not int or total < cursor or len(references) != min(total, 2000)
                or [r['sequence'] for r in references] != list(range(total - len(references) + 1, total + 1))):
            raise CourseGraphError("查阅记录计数无效。")
        linux_dialogue.validate(report, activity)

    def sync(self, binding_id, student, *, persisted=False):
        folder, b = self.bound(binding_id, student)
        if persisted:
            # Maintenance replays only the already imported immutable report;
            # it must not collect unsynced work or manufacture a new attempt.
            summary = read(folder / "import.json")
            report = read(folder / "raw" / (summary["raw_digest"] + ".json"))
        elif not (folder / "telemetry.json").is_file():
            raise CourseGraphError("尚未收到终端记录，请先启动本周目。", 409)
        else:
            report = read(folder / "telemetry.json")
        graph = read(folder / "graph.json")
        activity = self.activity(graph)
        self.validate_report(report, b, activity)
        descriptor = read(folder / "descriptor.json")
        with self.store._writer():
            old = read(folder / "import.json") if (folder / "import.json").is_file() else {}
            if old:
                prior = read(folder / "raw" / (old["raw_digest"] + ".json"))
                previous_ops = {o["sequence"]: o for o in prior["operations"]}
                previous_references = {r['sequence']: r for r in prior.get('reference_lookups', [])}
                if (prior["lab_session_id"] != report["lab_session_id"]
                        or report["events"][:len(prior["events"])] != prior["events"]
                        or not linux_dialogue.unchanged(prior, report)
                        or report["operation_total"] < prior["operation_total"]
                        or any(o["sequence"] in previous_ops and o != previous_ops[o["sequence"]] for o in report["operations"])
                        or report.get('reference_total', 0) < prior.get('reference_total', 0)
                        or any(r['sequence'] in previous_references and r != previous_references[r['sequence']]
                               for r in report.get('reference_lookups', []))):
                    raise CourseGraphError("报告回退或改写了既有记录，已保留此前证据。", 409)
            raw_hash = digest(report)
            _atomic_json(folder / "raw" / (raw_hash + ".json"), report)
            reflections = read(folder / "reflections.json") if (folder / "reflections.json").is_file() else []
            diagnostic = diagnose(report, activity, descriptor["issues"], graph, reflections)
            assessment = assess_run(report, b, graph, activity)
            old_assessment = old.get("assessment", {})
            stamp = self.store._stamp()
            for ident, item in assessment["nodes"].items():
                previous_item = old_assessment.get("nodes", {}).get(ident, {})
                item["updated_at"] = (previous_item["updated_at"]
                                      if (previous_item.get("observation_key") == item["observation_key"]
                                          or (old.get("raw_digest") == raw_hash
                                              and old_assessment.get("policy_version") != assessment["policy_version"]))
                                      and previous_item.get("updated_at") else stamp)
            assessment_changed = assessment != {k: v for k, v in old_assessment.items() if k != "updated_at"}
            assessment["updated_at"] = stamp if assessment_changed else old_assessment["updated_at"]
            _atomic_json(folder / "assessments" / (digest(assessment) + ".json"), assessment)
            imported = 0
            if b["mode"] == "published":
                # Historical runs keep their published version; no silent rebinding.
                if self.store._require_graph(b["course_version"]) != graph:
                    raise CourseGraphError("冻结课程与发布版本不一致。", 409)
                learner = self.store._read_learner(student)
                ledger = learner.setdefault("workspace", empty_workspace()).setdefault("linuxlab", {}).setdefault(binding_id, {"events": [], "cases": {}, "reflections": []})
                nodes = {n["id"]: n for n in graph["nodes"]}
                dialogue_ledger = ledger.setdefault('dialogues', {})
                for row in report.get('dialogue_evidence', []):
                    if row['id'] in dialogue_ledger:
                        continue
                    related = [c for c in diagnostic['cases'] if c['id'] == 'dialogue-' + row['id']]
                    ids = sorted({n for c in related for n in c['node_ids']})
                    evidence_ids = []
                    for node_id in ids:
                        for role in ('learner', 'assistant'):
                            speech = row[role]
                            origin = ('learner_expression' if role == 'learner' else
                                      'model_inference' if speech['origin'] == 'model_inference' else 'system_completion')
                            e = self.evidence(learner, graph, nodes[node_id], b, row['phase'], speech['text'],
                                              row['prior_help_level'] if role == 'learner' else 3, raw_hash,
                                              ['dialogue:' + row['id']], origin=origin,
                                              source_type='annotation' if role == 'learner' else 'technical')
                            e['context'].update(dialogue_role=role, dialogue_turn_id=row['id'], not_assessment_answer=True)
                            evidence_ids.append(e['id'])
                            imported += 1
                    dialogue_ledger[row['id']] = evidence_ids
                for e in report["events"]:
                    if e["id"] in ledger["events"]:
                        continue
                    if e["kind"] in ("passed", "retry"):
                        for node_id in activity["stages"][e["phase"] - 1]["node_ids"]:
                            self.evidence(learner, graph, nodes[node_id], b, e["phase"],
                                          f"LinuxLab 第 {e['phase']} 关：{'检查通过' if e['kind'] == 'passed' else '检查尚未通过'}；仅为检查结果。",
                                          e["prompt_level"], raw_hash, ["check:" + str(e["id"])])
                            imported += 1
                    ledger["events"].append(e["id"])
                for case in diagnostic["cases"]:
                    signature = digest(case)
                    if ledger["cases"].get(case["id"]) == signature:
                        continue
                    for node_id in case["node_ids"]:
                        evidence = self.evidence(learner, graph, nodes[node_id], b, case["phase"],
                                                 "；".join(case["observations"]), case["prompt_level"], raw_hash, case["evidence_refs"],
                                                 origin='model_inference' if case.get('kind') == 'dialogue' else None)
                        refs = [evidence["id"]] + [r["evidence_id"] for r in reflections if r["case_id"] == case["id"] and r["node_id"] == node_id and r.get("evidence_id")]
                        refs += [ident for c in case.get('dialogue_context', []) for ident in dialogue_ledger.get(c['turn_id'], [])
                                 if next(e for e in learner['evidence'] if e['id'] == ident)['node_id'] == node_id]
                        learner["diagnoses"].append(dict(id=uuid.uuid4().hex, student_id=student, course_id=graph["id"],
                            course_version=graph["version"], node_id=node_id, node_fingerprint=_fingerprint(nodes[node_id]),
                            evidence_ids=refs, status="uncertain", basis="观察：" + "；".join(case["observations"]) + "\n候选原因（未确诊）：" + "；".join(case["hypotheses"]) + "\n核验：" + next(q["question"] for q in case["verification_questions"] if q["node_id"] == node_id),
                            review_status="draft", reviewer="", reviewed_at=None, is_retest=False,
                            resolves_diagnosis_ids=[], mastered_at=None, review_stage=0, created_at=self.store._stamp(),
                            policy_version=diagnostic["policy_version"], linuxlab_case_id=case["id"], binding_id=binding_id))
                        imported += 1
                    ledger["cases"][case["id"]] = signature
                ledger_changed = ledger.get("assessment") != assessment
                ledger["assessment"] = assessment
                if imported or ledger_changed:
                    self.store._commit(learner)
            summary = dict(raw_digest=raw_hash, synced_at=self.store._stamp(), phases_passed=report["phases_passed"],
                           completed=report["completed"], events=report["events"], diagnosis=diagnostic,
                           mode=b["mode"], newly_imported_evidence=imported, assessment=assessment)
            _atomic_json(folder / "import.json", summary)
        return self.session(binding_id, student)

    def evidence(self, learner, graph, node, b, phase, text, level, raw_hash, refs, *, expression=False, origin=None, source_type=None):
        task = self.activity(graph)["stages"][phase - 1]
        record = dict(id=uuid.uuid4().hex, student_id=b["student_id"], course_id=graph["id"], course_version=graph["version"],
                      node_id=node["id"], node_fingerprint=_fingerprint(node), source_type=source_type or ("practice" if expression else "technical"),
                      origin=origin or ("learner_expression" if expression else "system_completion"), prompt_level=level, text=text,
                      context=dict(task_id=task["task_id"], task_version=b["contract_version"], skeleton_id="linux-nine-v1", skeleton_version=1,
                                   binding_id=b["binding_id"], phase=phase, raw_digest=raw_hash, raw_refs=refs),
                      expressed_relations=[], created_at=self.store._stamp())
        learner["evidence"].append(record)
        return record

    def reflect(self, binding_id, payload):
        folder, b = self.bound(binding_id, payload.get("student_id"))
        ident = safe_id(payload.get("request_id"), "请求编号")
        text = _text(payload.get("text"), "学习者解释", 3000)
        level = payload.get("prompt_level")
        if type(level) is not int or level not in range(5):
            raise CourseGraphError("请选择解释时使用的提示等级。")
        with self.store._writer():
            summary = read(folder / "import.json")
            case = next((c for c in summary["diagnosis"]["cases"] if c["id"] == payload.get("case_id")), None)
            if not case or payload.get("node_id") not in case["node_ids"]:
                raise CourseGraphError("请关联本次诊断中的知识点。")
            # Existing observed help cannot be silently reset to independent.
            observed = max((e["prompt_level"] for e in summary["events"] if e["phase"] == case["phase"]), default=0)
            if level < observed:
                raise CourseGraphError(f"本关已记录 {observed} 级帮助，请如实保留提示语境。")
            items = read(folder / "reflections.json") if (folder / "reflections.json").is_file() else []
            item = dict(id=ident, case_id=case["id"], node_id=payload["node_id"], text=text, prompt_level=level)
            old = next((r for r in items if r["id"] == ident), None)
            if old:
                if any(old[k] != v for k, v in item.items()):
                    raise CourseGraphError("重复请求内容不同。", 409)
            else:
                graph = read(folder / "graph.json")
                if b["mode"] == "published":
                    self.store._require_graph(b["course_version"])
                    learner = self.store._read_learner(b["student_id"])
                    # Recover idempotently if a prior commit succeeded before
                    # writing the local reflection index.
                    old_e = next((e for e in learner["evidence"] if e.get("context", {}).get("reflection_request") == ident
                                  and e["context"].get("binding_id") == binding_id), None)
                    if old_e:
                        if old_e["text"] != text or old_e["node_id"] != item["node_id"] or old_e["prompt_level"] != level:
                            raise CourseGraphError("重复解释请求内容不同。", 409)
                        evidence = old_e
                    else:
                        node = next(n for n in graph["nodes"] if n["id"] == item["node_id"])
                        evidence = self.evidence(learner, graph, node, b, case["phase"], text, level,
                                                 summary["raw_digest"], case["evidence_refs"], expression=True)
                        evidence["context"]["reflection_request"] = ident
                        self.store._commit(learner)
                    item["evidence_id"] = evidence["id"]
                items.append(item)
                _atomic_json(folder / "reflections.json", items)
        return self.sync(binding_id, b["student_id"])
