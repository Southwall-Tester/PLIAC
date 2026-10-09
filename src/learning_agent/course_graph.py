"""Small, auditable course graphs and separate learner evidence.

Only prerequisite edges define learning order. A missing observation is unknown,
never evidence of poor performance. Seed files are read-only templates.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import tempfile
import threading
import time
import uuid
from collections import Counter
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit

import networkx as nx

from .recommendation import recommend_resources

ROOT = Path(__file__).resolve().parents[2]
STATUSES = {"mastered", "needs_review", "uncertain", "unknown"}
EDGE_TYPES = {"prerequisite", "contains", "related", "confusable"}
RESOURCE_FORMATS = {"video", "lesson", "case", "practice", "course"}
ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}\Z")
RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}
MAX_JSON_BYTES = 2_000_000


class CourseGraphError(ValueError):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


def _fail(message: str, status_code: int = 400):
    raise CourseGraphError(message, status_code)


def safe_id(value, label="标识") -> str:
    if not isinstance(value, str) or not ID_RE.fullmatch(value) or value.upper() in RESERVED:
        _fail(f"{label}须为 1—64 位字母、数字、下划线或短横线，以字母或数字开头，且不能使用系统保留名称。")
    return value


def _text(value, label, maximum=1000, required=True):
    if not isinstance(value, str) or len(value) > maximum or (required and not value.strip()):
        _fail(f"{label}须为{'非空' if required else ''}文本，最多 {maximum} 字。")
    if any(ord(c) < 32 and c not in "\n\r\t" for c in value):
        _fail(f"{label}含有不支持的控制字符。")
    return value


def _list(value, label, maximum):
    if not isinstance(value, list) or len(value) > maximum:
        _fail(f"{label}须为列表，最多 {maximum} 项。")
    return value


def _dict(value, label):
    if not isinstance(value, dict):
        _fail(f"{label}须为 JSON 对象。")
    return value


def _integer(value, label, minimum=0):
    if type(value) is not int or value < minimum:
        _fail(f"{label}须为不小于 {minimum} 的整数。")
    return value


def _url(value, label):
    _text(value, label, 2000, required=False)
    if not value:
        return value
    try:
        parsed = urlsplit(value)
        port = parsed.port
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
            _fail(f"{label}仅支持不含账号密码的 HTTP/HTTPS 地址；本地资料可留空。")
        if any(c.isspace() for c in value) or "\\" in value:
            _fail(f"{label}格式不正确。")
        del port
    except ValueError:
        _fail(f"{label}格式不正确。")
    return value


def _unique(items, label):
    seen = set()
    for item in items:
        _dict(item, label)
        ident = safe_id(item.get("id"), f"{label} ID")
        if ident in seen:
            _fail(f"{label}存在重复 ID：{ident}。")
        seen.add(ident)
    return seen


def _refs(value, allowed, label):
    _list(value, label, 200)
    if any(not isinstance(v, str) for v in value):
        _fail(f"{label}中的每项须为资料 ID。")
    if len(set(value)) != len(value) or not set(value).issubset(allowed):
        _fail(f"{label}含重复或不存在的资料 ID。")


def _date(value, label):
    _text(value, label, 80)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)
    except ValueError:
        _fail(f"{label}须为有效 ISO 日期或时间。")


def _review(item):
    if item.get("review_status") not in ("draft", "reviewed"):
        _fail("审核状态须为 draft 或 reviewed。")
    for field, label in (("reviewer", "审核人"), ("reviewed_at", "审核时间"), ("review_note", "审核依据")):
        if item.get("review_status") == "reviewed" or field in item:
            _text(item.get(field), label, 2000, item.get("review_status") == "reviewed")
    if item.get("reviewed_at"):
        _date(item["reviewed_at"], "审核时间")


def validate_graph(graph: dict, *, allow_empty=False) -> dict:
    """Validate the complete graph without changing it or writing any files."""
    _dict(graph, "课程图谱")
    try:
        size = len(json.dumps(graph, ensure_ascii=False, allow_nan=False).encode("utf-8"))
    except (TypeError, ValueError, RecursionError):
        _fail("课程图谱必须是有效的 JSON 数据。")
    if size > MAX_JSON_BYTES:
        _fail("课程图谱超过 2 MB，请缩小导入范围。")
    if type(graph.get("schema_version")) is not int or graph["schema_version"] != 1:
        _fail("仅支持 schema_version=1 的课程图谱。")
    safe_id(graph.get("id"), "图谱 ID")
    _text(graph.get("title"), "课程标题", 200)
    _integer(graph.get("version"), "图谱版本", 1)
    chapters = _list(graph.get("chapters"), "章节", 50)
    sources = _list(graph.get("sources"), "来源资料", 200)
    nodes = _list(graph.get("nodes"), "知识节点", 500)
    edges = _list(graph.get("edges"), "知识关系", 2000)
    resources = _list(graph.get("resources"), "教学资源", 500)
    policy = _dict(graph.get("review_policy"), "复习规则")
    intervals = _list(policy.get("intervals_days"), "复习间隔", 12)
    if not intervals:
        _fail("至少配置一个复习间隔。")
    for days in intervals:
        _integer(days, "复习间隔天数", 1)
        if days > 3650:
            _fail("单次复习间隔不能超过 3650 天。")
    if intervals != sorted(set(intervals)):
        _fail("复习间隔须按递增顺序排列且不能重复。")
    if not chapters or (not nodes and not allow_empty):
        _fail("课程至少需要一个章节和一个知识节点。")
    chapter_ids = _unique(chapters, "章节")
    source_ids = _unique(sources, "资料")
    node_ids = _unique(nodes, "节点")
    _unique(edges, "关系")
    _unique(resources, "教学资源")
    for chapter in chapters:
        _text(chapter.get("title"), "章节标题", 200)
        _text(chapter.get("description"), "章节说明", 2000, False)
        if "completion_policy" in chapter:
            rule = _dict(chapter["completion_policy"], "章节达标规则")
            if rule.get("mode") != "all_required_mastered":
                _fail("章节规则须为全部指定节点有当前掌握证据。")
            local_ids = {n["id"] for n in nodes if n.get("chapter_id") == chapter["id"]}
            _refs(rule.get("required_node_ids"), local_ids, "章节必达节点")
            if not rule["required_node_ids"]:
                _fail("章节达标规则至少指定一个本章节点。")
            _text(rule.get("configured_by"), "规则制定人", 200)
            _text(rule.get("basis"), "规则依据", 2000)
    for source in sources:
        _text(source.get("title"), "资料标题", 300)
        _text(source.get("kind"), "资料类型", 64)
        _url(source.get("url"), "资料链接")
        if "locator" in source:
            _text(source["locator"], "资料具体定位", 2000, False)
    for node in nodes:
        _text(node.get("title"), "节点名称", 200)
        _text(node.get("description"), "节点说明", 4000, False)
        if not isinstance(node.get("chapter_id"), str) or node["chapter_id"] not in chapter_ids:
            _fail(f"节点 {node['id']} 的章节不存在。")
        for objective in _list(node.get("objectives"), "学习目标", 20):
            _text(objective, "学习目标", 500)
        for alias in _list(node.get("aliases"), "别名", 30):
            _text(alias, "别名", 200)
        _text(node.get("misconception"), "常见误解", 2000, False)
        for field, label in (("check_question", "自检题"), ("expected_answer", "参考答案")):
            if field in node:
                _text(node[field], label, 4000, False)
        if "check_task" in node:
            task = _dict(node["check_task"], "节点诊断任务")
            safe_id(task.get("id"), "诊断任务 ID")
            _integer(task.get("version"), "诊断任务版本", 1)
            for criterion in _list(task.get("rubric"), "诊断判据", 30):
                _text(criterion, "诊断判据", 2000)
            hints = _list(task.get("hint_levels"), "分级提示", 4)
            if len(hints) != 4:
                _fail("诊断任务需要 4 级提示。")
            for hint in hints:
                _text(hint, "分级提示", 2000)
        _refs(node.get("source_ids"), source_ids, "节点来源")
    seen_edges = set()
    for edge in edges:
        source, target, kind = edge.get("source"), edge.get("target"), edge.get("type")
        if not isinstance(source, str) or not isinstance(target, str) or source not in node_ids or target not in node_ids:
            _fail(f"关系 {edge['id']} 的起点或终点不存在。")
        if source == target:
            _fail(f"关系 {edge['id']} 不能连接节点自身。")
        if not isinstance(kind, str) or kind not in EDGE_TYPES:
            _fail(f"关系 {edge['id']} 的类型须为 prerequisite、contains、related 或 confusable。")
        pair = tuple(sorted((source, target))) if kind in {"related", "confusable"} else (source, target)
        key = (kind, *pair)
        if key in seen_edges:
            _fail(f"知识关系重复：{source} → {target}（{kind}）。")
        seen_edges.add(key)
        _text(edge.get("reason"), "关系理由", 2000)
        _refs(edge.get("source_ids"), source_ids, "关系来源")
    for resource in resources:
        _text(resource.get("title"), "资源标题", 300)
        _text(resource.get("organization"), "资源作者或机构", 300)
        _url(resource.get("url"), "资源链接")
        _text(resource.get("applicable_segment"), "适用片段", 2000, False)
        if resource.get("format") not in tuple(RESOURCE_FORMATS):
            _fail("资源形态须为 video、lesson、case、practice 或 course。")
        _refs(resource.get("node_ids"), node_ids, "资源适用节点")
        _refs(resource.get("prerequisite_ids"), node_ids, "资源前置要求")
        if not resource["node_ids"]:
            _fail("教学资源至少关联一个知识节点。")
        if "source_ids" in resource:
            _refs(resource["source_ids"], source_ids, "资源出处")
    for item in [*nodes, *edges, *resources]:
        _review(item)
    for kind, label in (("prerequisite", "先修"), ("contains", "包含")):
        directed = nx.DiGraph()
        directed.add_nodes_from(node_ids)
        directed.add_edges_from((e["source"], e["target"]) for e in edges if e["type"] == kind)
        if not nx.is_directed_acyclic_graph(directed):
            _fail(f"{label}关系形成循环，请先修正后再保存。")
    return graph_summary(graph)


def graph_summary(graph, learner=None):
    if graph is None:
        return {"node_count": 0, "edge_count": 0, "chapter_count": 0, "resource_count": 0,
                "status_counts": {s: 0 for s in sorted(STATUSES)}, "review_counts": {"draft": 0, "reviewed": 0},
                "has_drafts": False, "review_notice": "课程尚未发布，请先完成课程审核。"}
    states = learner.get("states", {}) if learner else {}
    counts = Counter(states.get(node["id"], {}).get("status", "unknown") for node in graph["nodes"])
    reviews = Counter(item.get("review_status", "draft") for item in [*graph["nodes"], *graph["edges"], *graph["resources"]])
    return {
        "node_count": len(graph["nodes"]), "edge_count": len(graph["edges"]),
        "chapter_count": len(graph["chapters"]),
        "resource_count": len(graph["resources"]),
        "status_counts": {s: counts[s] for s in sorted(STATUSES)},
        "review_counts": {s: reviews[s] for s in ("draft", "reviewed")},
        "has_drafts": bool(reviews["draft"]),
        "review_notice": "含待教师审核的课程草稿。" if reviews["draft"] else "节点与关系已标记审核；审核依据见备注和来源。",
    }


def _utc():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _read_json(path):
    try:
        if path.stat().st_size > 25_000_000:
            _fail("数据文件过大，请联系项目维护者检查。", 500)
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except CourseGraphError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise CourseGraphError("课程数据无法读取，请检查文件是否存在且为有效 JSON。", 500) from exc


def _atomic_json(path, data):
    serialized = json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    if len(serialized.encode("utf-8")) > 25_000_000:
        _fail("记录超过 25 MB，请先导出并由维护者归档；原记录尚未修改。")
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, prefix=".graph-", suffix=".tmp", delete=False) as stream:
            tmp = Path(stream.name)
            stream.write(serialized)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp, path)
    finally:
        if tmp and tmp.exists():
            tmp.unlink()


def _fingerprint(node):
    content = {k: v for k, v in node.items() if k not in {"review_status", "reviewer", "reviewed_at", "review_note"}}
    return hashlib.sha256(json.dumps(content, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def student_graph(graph):
    """Public learning responses omit teacher answer and grading material."""
    if graph is None:
        return None
    result = copy.deepcopy(graph)
    private = {"expected_answer", "reference_answer", "rubric", "solution", "hints", "hint_levels", "answers", "answer_key", "explanation"}

    def clean(value):
        if isinstance(value, dict):
            return {k: clean(v) for k, v in value.items() if k not in private}
        if isinstance(value, list):
            return [clean(v) for v in value]
        return value

    result["nodes"] = [clean(n) for n in result["nodes"]]
    return result


class CourseGraphStore:
    """Versioned curriculum and transactional, separate learner records.

    A learner revision contains separate profile/evidence/diagnoses/actions/use
    files. Only replacing HEAD makes a complete revision visible. Failed writes
    leave the previous revision readable, and never overwrite raw history.
    """
    def __init__(self, seed_path=None, output_dir=None, clock=None):
        self.seed_path = Path(seed_path or ROOT / "data/courses/ml_classification.json")
        self.output_dir = Path(output_dir or ROOT / "outputs/course_graph").resolve()
        self.graph_path = self.output_dir / "draft.json"
        self._lock = threading.RLock()
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def _now(self):
        moment = self.clock()
        return moment.replace(tzinfo=timezone.utc) if moment.tzinfo is None else moment.astimezone(timezone.utc)

    def _stamp(self):
        return self._now().isoformat().replace("+00:00", "Z")

    @contextmanager
    def _writer(self):
        with self._lock:
            self.output_dir.mkdir(parents=True, exist_ok=True)
            lock_path = self.output_dir / ".write.lock"
            deadline = time.monotonic() + 3
            while True:
                try:
                    fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
                    break
                except FileExistsError:
                    if time.monotonic() > deadline:
                        _fail("另一项保存正在进行，请稍后重试；持续失败时请维护者检查写入锁。", 409)
                    time.sleep(0.03)
            try:
                os.close(fd)
                yield
            finally:
                lock_path.unlink(missing_ok=True)

    def load_graph(self, view="published", version=None):
        if view not in ("draft", "published"):
            _fail("图谱视图须为 draft 或 published。")
        if view == "draft":
            graph = _read_json(self.graph_path if self.graph_path.exists() else self.seed_path)
        else:
            pointer = self.output_dir / "publication.json"
            if not pointer.exists():
                if version is not None:
                    _fail("课程尚未发布，不能写入正式学习记录。", 409)
                return None
            publication = _read_json(pointer)
            if version is None:
                version = publication["published_version"]
            _integer(version, "课程版本", 1)
            if version not in publication.get("published_versions", [publication["published_version"]]):
                _fail("该版本未完成发布，不能用于正式学习记录。", 409)
            path = self.output_dir / "published" / f"v{version}.json"
            if not path.exists():
                _fail("该课程版本尚未发布，不能用于正式学习记录。", 409)
            graph = _read_json(path)
        validate_graph(graph, allow_empty=view == "draft")
        return graph

    def publication(self):
        draft = self.load_graph("draft")
        pointer = self.output_dir / "publication.json"
        data = _read_json(pointer) if pointer.exists() else {}
        return {**data, "draft_version": draft["version"], "published_version": data.get("published_version"),
                "notice": "学习端使用已发布课程；草稿修改不会自动上线。" if data else "课程尚未发布。请教师在草稿视图核验节点、关系和资源后发布。"}

    def _require_graph(self, version=None):
        graph = self.load_graph("published", version)
        if graph is None:
            _fail("课程尚未发布，暂不能提交正式学习记录；教师可预览草稿。", 409)
        return graph

    def _node(self, graph, node_id):
        safe_id(node_id, "知识节点 ID")
        for node in graph["nodes"]:
            if node["id"] == node_id:
                return node
        _fail("该课程版本中不存在此知识节点。", 404)

    def save_graph(self, graph, expected_version):
        validate_graph(graph, allow_empty=True)
        _integer(expected_version, "预期草稿版本", 1)
        with self._writer():
            current = self.load_graph("draft")
            if current["version"] != expected_version or graph["version"] != expected_version:
                _fail("草稿已发生变化，请重新载入并合并修改。", 409)
            if graph["id"] != current["id"]:
                _fail("保存草稿不能更换课程 ID。")
            saved = copy.deepcopy(graph)
            audit_fields = ("reviewer", "reviewed_at", "review_note")
            for collection in ("nodes", "edges", "resources"):
                previous = {item["id"]: item for item in current[collection]}
                for item in saved[collection]:
                    old = previous.get(item["id"])
                    if (old and old["review_status"] == "reviewed" and _fingerprint(old) != _fingerprint(item)
                            and all(old.get(key) == item.get(key) for key in audit_fields)):
                        item["review_status"] = "draft"
                        for key in audit_fields:
                            item.pop(key, None)
            saved["version"] += 1
            _atomic_json(self.output_dir / "draft_history" / f"v{current['version']}-{uuid.uuid4().hex}.json", current)
            _atomic_json(self.graph_path, saved)
        return {"graph": saved, "summary": graph_summary(saved), "publication": self.publication()}

    def publish(self, expected_version, published_by, note):
        _integer(expected_version, "预期草稿版本", 1)
        _text(published_by, "发布人", 200)
        _text(note, "发布说明", 2000)
        with self._writer():
            graph = self.load_graph("draft")
            if graph["version"] != expected_version:
                _fail("草稿已变化，请重新审核当前版本。", 409)
            validate_graph(graph)
            pending = [item["id"] for item in [*graph["nodes"], *graph["edges"], *graph["resources"]] if item["review_status"] != "reviewed"]
            if pending:
                _fail(f"还有 {len(pending)} 个节点、关系或资源未人工审核，不能发布。", 409)
            path = self.output_dir / "published" / f"v{graph['version']}.json"
            if path.exists():
                if _read_json(path) != graph:
                    _fail("已发布版本不可覆盖，请创建新草稿版本。", 409)
            else:
                _atomic_json(path, graph)
            previous = self.output_dir / "publication.json"
            versions = _read_json(previous).get("published_versions", []) if previous.exists() else []
            pointer = {"published_version": graph["version"], "published_versions": sorted(set(versions + [graph["version"]])), "published_by": published_by,
                       "published_at": self._stamp(), "note": note}
            _atomic_json(self.output_dir / "publication.json", pointer)
        return {"graph": student_graph(graph), "summary": graph_summary(graph), "publication": self.publication()}

    def _learner_dir(self, student_id):
        safe_id(student_id, "匿名编号")
        # Case-sensitive IDs remain distinct on Windows too.
        digest = hashlib.sha256(student_id.encode("ascii")).hexdigest()[:16]
        path = self.output_dir / "learners" / f"{student_id}-{digest}"
        if not path.resolve().is_relative_to(self.output_dir):
            _fail("学习记录路径不在数据目录内。")
        return path

    @staticmethod
    def _empty(student_id=""):
        return {"schema_version": 1, "student_id": student_id, "version": 0,
                "profile": {"background": "", "goals": "", "interests": [], "current_position": None,
                            "ability_evidence": [], "behavioral_clues": [], "emotional_clues": [], "current_memory": {}},
                "states": {}, "evidence": [], "diagnoses": [], "actions": [], "resource_uses": []}

    def _read_learner(self, student_id):
        if not student_id:
            return self._empty()
        folder = self._learner_dir(student_id)
        head = folder / "HEAD.json"
        if not head.exists():
            return self._empty(student_id)
        commit = _read_json(head)
        revision = safe_id(commit.get("revision"), "记录版本 ID")
        root = folder / "revisions" / revision
        result = self._empty(student_id)
        meta = _read_json(root / "profile.json")
        if meta.get("student_id") != student_id or meta.get("version") != commit.get("version"):
            _fail("学习记录版本不一致，请维护者检查。", 500)
        result.update({"version": meta["version"], "profile": meta["profile"]})
        for name in ("evidence", "diagnoses", "actions", "resource_uses"):
            result[name] = _read_json(root / f"{name}.json")
            if not isinstance(result[name], list):
                _fail("学习历史格式异常，请维护者检查。", 500)
        # Optional for old revisions. Workspace and evidence share the same HEAD.
        if (root / "workspace.json").exists():
            result["workspace"] = _read_json(root / "workspace.json")
        return result

    def _commit(self, learner):
        folder = self._learner_dir(learner["student_id"])
        version = learner["version"] + 1
        revision = f"v{version}-{uuid.uuid4().hex}"
        target = folder / "revisions" / revision
        _atomic_json(target / "profile.json", {"schema_version": 1, "student_id": learner["student_id"],
                                              "version": version, "profile": learner["profile"]})
        for name in ("evidence", "diagnoses", "actions", "resource_uses"):
            if len(learner[name]) > 10000:
                _fail("单类记录已达 10000 条，请先导出并由维护者归档。")
            _atomic_json(target / f"{name}.json", learner[name])
        if "workspace" in learner:
            _atomic_json(target / "workspace.json", learner["workspace"])
        _atomic_json(folder / "HEAD.json", {"version": version, "revision": revision})
        learner["version"] = version

    def _expected(self, learner, expected):
        if expected is not None:
            _integer(expected, "预期学习记录版本")
            if expected != learner["version"]:
                _fail("学习记录已更新，请重新载入后再提交。", 409)

    @staticmethod
    def _actual(evidence):
        return evidence["origin"] == "learner_expression" and evidence["source_type"] != "technical"

    @staticmethod
    def _independent(evidence):
        study = evidence.get("context", {}).get("study")
        recalled = study is None or (study.get("mode") == "recall" and study.get("recall_started")
                                     and not study.get("material_reopened") and not study.get("support_viewed"))
        return (recalled and CourseGraphStore._actual(evidence) and evidence["prompt_level"] == 0
                and evidence["source_type"] not in {"self_assessment", "annotation"})

    @staticmethod
    def _task_bound(evidence):
        context = evidence.get("context", {})
        if not context.get("task_id") or not context.get("task_version"):
            return False
        return (evidence["source_type"] != "practice"
                or bool(context.get("skeleton_id") and context.get("skeleton_version")))

    def _confirmed(self, diagnosis):
        return diagnosis["review_status"] == "reviewed"

    def _published_history(self):
        publication = _read_json(self.output_dir / "publication.json")
        return publication.get("published_versions", [publication["published_version"]])

    def _derive(self, learner, graph):
        states = {}
        if graph is None:
            learner["states"] = states
            return learner
        # A deleted and later reintroduced ID is not continuous evidence of the
        # same skill, even when its final text happens to match an old snapshot.
        course_diagnoses = [d for d in learner["diagnoses"] if d["course_id"] == graph["id"]]
        history = {}
        if course_diagnoses:
            oldest_version = min(d["course_version"] for d in course_diagnoses)
            for version in self._published_history():
                if oldest_version < version <= graph["version"]:
                    snapshot = graph if version == graph["version"] else self.load_graph("published", version)
                    history[version] = {item["id"]: _fingerprint(item) for item in snapshot["nodes"]}
        for node in graph["nodes"]:
            ident = node["id"]
            raw = [e for e in learner["evidence"] if e["node_id"] == ident and e["course_id"] == graph["id"]]
            diagnostics = [d for d in learner["diagnoses"] if d["node_id"] == ident and d["course_id"] == graph["id"]]
            resolved = {ref for d in diagnostics for ref in d.get("resolves_diagnosis_ids", [])}
            active = [d for d in diagnostics if d["id"] not in resolved]
            latest = diagnostics[-1] if diagnostics else None
            mastered = [d for d in diagnostics if d["status"] == "mastered" and self._confirmed(d)]
            last_mastery = mastered[-1] if mastered else None
            recorded = latest["status"] if latest else "unknown"
            status = recorded
            reason = "待完成首次作答。"
            state = {"status": status, "recorded_status": recorded, "due_at": None,
                     "last_mastered_at": last_mastery.get("mastered_at", last_mastery["created_at"]) if last_mastery else None,
                     "reason": reason, "evidence_ids": [e["id"] for e in raw],
                     "diagnosis_ids": [d["id"] for d in diagnostics], "review_stage": last_mastery.get("review_stage", 0) if last_mastery else 0,
                     "version_changed": False, "due": False}
            if latest:
                reason = latest["basis"]
                if not self._confirmed(latest):
                    status, reason = "uncertain", "最新诊断尚待人工复核。"
                decisive = {d["status"] for d in active if self._confirmed(d) and d["status"] in {"mastered", "needs_review"}}
                if len(decisive) > 1:
                    status, reason = "uncertain", "掌握与补学判断存在未调和冲突，请复核证据。"
                changed = latest.get("node_fingerprint") != _fingerprint(node)
                changed = changed or any(nodes.get(ident) != latest.get("node_fingerprint")
                                         for version, nodes in history.items() if version > latest["course_version"])
                if changed:
                    status, reason = "uncertain", "知识节点内容版本已变化，旧判断需要核验。"
                    state["version_changed"] = True
            cited = {ref for d in diagnostics for ref in d["evidence_ids"]}
            pending = [e for e in raw if e["id"] not in cited and self._actual(e)]
            if pending:
                status, reason = "uncertain", "已有新的真实表达或作答，尚未形成诊断。"
            elif status == "unknown" and any(self._actual(e) for e in raw):
                status, reason = "uncertain", "已有学习表达，但证据尚不足以判断掌握情况。"
            if status == "mastered" and last_mastery:
                stage = min(last_mastery.get("review_stage", 0), len(graph["review_policy"]["intervals_days"]) - 1)
                due = _date(state["last_mastered_at"], "掌握时间") + timedelta(days=graph["review_policy"]["intervals_days"][stage])
                state["due_at"] = due.isoformat().replace("+00:00", "Z")
                if self._now() >= due:
                    status, reason = "uncertain", "已到复习时间，请完成复测。"
                    state["due"] = True
            state.update(status=status, reason=reason)
            states[ident] = state
        learner["states"] = states
        return learner

    def load_learner(self, student_id="", graph=None):
        if not isinstance(student_id, str):
            _fail("匿名编号须为文本。")
        return self._derive(self._read_learner(student_id), graph if graph is not None else self.load_graph())

    def view(self, student_id="", view="published"):
        graph = self.load_graph(view)
        if view == "draft":
            learner = self._derive(self._empty(), graph)
            learner["preview_only"] = True
        else:
            learner = self.load_learner(student_id, graph)
        return {"graph": graph if view == "draft" else student_graph(graph), "learner": learner,
                "summary": graph_summary(graph, learner), "publication": self.publication()}

    def _context(self, value):
        context = copy.deepcopy(_dict(value, "任务语境"))
        allowed = {"task_id", "task_version", "turn_id", "skeleton_id", "skeleton_version"}
        if set(context) - allowed:
            _fail("任务语境包含不支持的字段。")
        for prefix in ("task", "skeleton"):
            ident = context.get(f"{prefix}_id")
            version = context.get(f"{prefix}_version")
            if ident:
                safe_id(ident, "任务或骨架 ID")
                _integer(version, "任务或骨架版本", 1)
            elif version is not None:
                _fail("填写任务或骨架版本时，必须同时填写对应 ID。")
        if context.get("turn_id") is not None:
            turn = context["turn_id"]
            if type(turn) is int:
                _integer(turn, "轮次", 1)
            else:
                _text(turn, "轮次", 80)
        return context

    def _mutation_result(self, learner, record=None, kind=None):
        graph = self.load_graph()
        learner = self._derive(learner, graph)
        result = {"learner": learner, "summary": graph_summary(graph, learner)}
        if record is not None:
            result["record"] = record
            if kind:
                result[kind] = record
        return result

    def add_evidence(self, payload):
        _dict(payload, "学习证据")
        if "status" in payload:
            _fail("原始证据不能直接修改掌握状态，请另外提交带依据的诊断。")
        student_id = safe_id(payload.get("student_id"), "匿名编号")
        version = _integer(payload.get("course_version"), "课程版本", 1)
        source_type = payload.get("source_type")
        if source_type not in ("manual", "dialog", "quiz", "practice", "annotation", "self_assessment", "technical"):
            _fail("证据类型不正确。")
        origin = payload.get("origin")
        if origin not in ("learner_expression", "system_completion", "model_inference"):
            _fail("证据来源须区分真实表达、系统补全和模型推断。")
        prompt = payload.get("prompt_level")
        if prompt is not None and (type(prompt) is not int or prompt not in range(5)):
            _fail("提示等级须为 0—4 的整数；未知时填写 null。")
        text = _text(payload.get("text"), "原始证据", 4000)
        context = self._context(payload.get("context", {}))
        with self._writer():
            graph = self._require_graph(version)
            node = self._node(graph, payload.get("node_id"))
            expressed_relations = []
            for item in _list(payload.get("expressed_relations", []), "学习者表达关系", 20):
                _dict(item, "学习者表达关系")
                source = self._node(graph, item.get("source"))["id"]
                target = self._node(graph, item.get("target"))["id"]
                if node["id"] not in (source, target):
                    _fail("表达关系至少有一个端点须对应本条证据的知识节点。")
                relation = _text(item.get("relation"), "表达的关系", 200)
                quote = _text(item.get("quote"), "关系原话", 4000)
                if quote not in text:
                    _fail("关系原话必须逐字出现在本条原始证据中，不能代写或引用课程参考关系。")
                expressed_relations.append({"source": source, "target": target, "relation": relation, "quote": quote})
            learner = self._read_learner(student_id)
            self._expected(learner, payload.get("expected_version"))
            record = {"id": uuid.uuid4().hex, "student_id": student_id, "course_id": graph["id"],
                      "course_version": version, "node_id": node["id"], "node_fingerprint": _fingerprint(node),
                      "source_type": source_type, "origin": origin, "prompt_level": prompt,
                      "text": text, "context": context, "expressed_relations": expressed_relations, "created_at": self._stamp()}
            learner["evidence"].append(record)
            self._commit(learner)
        return self._mutation_result(learner, record, "evidence")

    def add_diagnosis(self, payload):
        _dict(payload, "诊断")
        student_id = safe_id(payload.get("student_id"), "匿名编号")
        version = _integer(payload.get("course_version"), "课程版本", 1)
        status = payload.get("status")
        if status not in tuple(STATUSES):
            _fail("诊断状态不正确。")
        basis = _text(payload.get("basis"), "判断依据", 4000)
        review = payload.get("review_status")
        if review not in ("draft", "reviewed"):
            _fail("诊断复核状态须为 draft 或 reviewed。")
        reviewer = _text(payload.get("reviewer", ""), "诊断复核人", 200, review == "reviewed")
        is_retest = payload.get("is_retest", False)
        if type(is_retest) is not bool:
            _fail("是否复测须为布尔值。")
        with self._writer():
            graph = self._require_graph(version)
            node = self._node(graph, payload.get("node_id"))
            learner = self._read_learner(student_id)
            self._expected(learner, payload.get("expected_version"))
            raw = {e["id"]: e for e in learner["evidence"]}
            refs = payload.get("evidence_ids")
            _refs(refs, set(raw), "诊断证据引用")
            if not refs:
                _fail("诊断至少需要引用一条原始证据。")
            evidence = [raw[ref] for ref in refs]
            if any(e["node_id"] != node["id"] or e["course_version"] != version or e["course_id"] != graph["id"] for e in evidence):
                _fail("诊断引用必须对应同一知识节点及课程版本。")
            previous = [d for d in learner["diagnoses"] if d["node_id"] == node["id"] and d["course_id"] == graph["id"]]
            resolves = payload.get("resolves_diagnosis_ids", [])
            _refs(resolves, {d["id"] for d in previous}, "待调和诊断")
            if resolves and review != "reviewed":
                _fail("调和历史诊断须经人工复核并填写依据。")
            actual = [e for e in evidence if self._actual(e)]
            if status in {"mastered", "needs_review"} and not actual:
                _fail("系统补全、模型推断或技术异常不能单独支持掌握或补学判断。")
            support = [e for e in actual if self._task_bound(e)]
            if status in {"mastered", "needs_review"} and not support:
                _fail("掌握或补学判断需要关联任务 ID 和版本的真实证据；实训证据还需关联骨架 ID 和版本。未关联的手记可保留为待核验起点。")
            independent = [e for e in support if self._independent(e)]
            if status == "mastered" and (review != "reviewed" or not independent):
                _fail("标记掌握需要人工复核及独立完成（提示 0 级）的真实作答；自评不能单独证明掌握。")
            action_ref = payload.get("follow_up_action_id", "")
            _text(action_ref, "教学动作引用", 64, False)
            if action_ref:
                safe_id(action_ref, "教学动作引用")
                action = next((a for a in learner["actions"] if a.get("id") == action_ref), None)
                if (not action or action.get("course_id") != graph["id"]
                        or action.get("course_version") != version
                        or node["id"] not in action.get("target_node_ids", [action.get("node_id")])):
                    _fail("后续核验须关联本学习者、同课程版本及对应目标节点的教学动作。")
                if "observed_evidence_ids" not in action:
                    _fail("该历史动作没有完整的决策快照，不能追补为本次效果核验。请先生成新的教学建议。")
                old_refs = set(action["observed_evidence_ids"])
                if (review != "reviewed" or not any(e["source_type"] not in {"self_assessment", "annotation"} for e in support)
                        or any(e["id"] in old_refs or _date(e["created_at"], "证据时间") < _date(action["created_at"], "动作时间") for e in evidence)):
                    _fail("后续核验需要动作之后新记录的任务作答和人工复核；旧证据、点击、自评或技术异常不能代替。")
            previous_mastery = [d for d in previous if d["status"] == "mastered" and self._confirmed(d)]
            stage = previous_mastery[-1].get("review_stage", 0) if previous_mastery else 0
            if status == "mastered" and previous_mastery:
                used = {ref for d in previous for ref in d["evidence_ids"]}
                if not any(e["id"] not in used for e in independent):
                    _fail("再次确认掌握需要新的独立作答，不能用旧证据刷新掌握时间或复习间隔。")
            if status == "mastered" and is_retest:
                used = {ref for d in previous for ref in d["evidence_ids"]}
                if not any(e["id"] not in used for e in independent):
                    _fail("复测通过需要新的独立作答，不能重复使用此前已诊断的证据。")
                if previous_mastery:
                    stage = min(stage + 1, len(graph["review_policy"]["intervals_days"]) - 1)
            elif status == "mastered":
                stage = 0
            record = {"id": uuid.uuid4().hex, "student_id": student_id, "course_id": graph["id"],
                      "course_version": version, "node_id": node["id"], "node_fingerprint": _fingerprint(node),
                      "evidence_ids": list(refs), "status": status, "basis": basis,
                      "review_status": review, "reviewer": reviewer, "reviewed_at": self._stamp() if review == "reviewed" else None,
                      "is_retest": is_retest, "resolves_diagnosis_ids": list(resolves),
                      "mastered_at": max((e["created_at"] for e in independent), default=None) if status == "mastered" else None,
                      "review_stage": stage, "created_at": self._stamp()}
            if action_ref:
                record["follow_up_action_id"] = action_ref
            learner["diagnoses"].append(record)
            self._commit(learner)
        return self._mutation_result(learner, record, "diagnosis")

    def save_profile(self, payload):
        _dict(payload, "学习者资料")
        student_id = safe_id(payload.get("student_id"), "匿名编号")
        with self._writer():
            learner = self._read_learner(student_id)
            self._expected(learner, payload.get("expected_version"))
            profile = copy.deepcopy(learner["profile"])
            for field, label in (("background", "学习背景"), ("goals", "学习目标")):
                if field in payload:
                    profile[field] = _text(payload[field], label, 2000, False)
            if "interests" in payload:
                interests = _list(payload["interests"], "兴趣偏好", 30)
                profile["interests"] = [_text(value, "兴趣偏好", 100) for value in interests]
            if "current_position" in payload:
                position = payload["current_position"]
                if position is not None:
                    _dict(position, "学习位置")
                    graph = self._require_graph(_integer(position.get("course_version"), "课程版本", 1))
                    node = self._node(graph, position.get("node_id"))
                    if position.get("course_id") != graph["id"] or position.get("chapter_id") != node["chapter_id"]:
                        _fail("恢复位置的课程、章节与节点不一致。")
                    _text(position.get("context_ref", ""), "上下文引用", 1000, False)
                    position = {key: position.get(key, "") for key in ("course_id", "course_version", "chapter_id", "node_id", "context_ref")}
                profile["current_position"] = position
            learner["profile"] = profile
            self._commit(learner)
        return self._mutation_result(learner)

    def learning_path(self, target_id, student_id="", view="published"):
        graph = self.load_graph(view)
        if graph is None:
            return {"target_id": target_id, "steps": [], "ready": False, "notice": "课程尚未发布，暂不能生成正式学习路径。", "preview_only": False}
        self._node(graph, target_id)
        learner = self._derive(self._empty(), graph) if view == "draft" else self.load_learner(student_id, graph)
        nodes = {n["id"]: n for n in graph["nodes"]}
        directed = nx.DiGraph()
        directed.add_nodes_from(nodes)
        directed.add_edges_from((e["source"], e["target"]) for e in graph["edges"] if e["type"] == "prerequisite")
        required, pending, visited = {target_id}, [target_id], set()
        while pending:
            ident = pending.pop()
            if ident in visited:
                continue
            visited.add(ident)
            if learner["states"][ident]["status"] == "mastered":
                continue
            for prerequisite in directed.predecessors(ident):
                if learner["states"][prerequisite]["status"] != "mastered":
                    required.add(prerequisite)
                    pending.append(prerequisite)
        steps = [{"node_id": ident, "title": nodes[ident]["title"], "status": learner["states"][ident]["status"],
                  "reason": ("目标知识点；" if ident == target_id else "相关先修知识；") + learner["states"][ident]["reason"]}
                 for ident in nx.lexicographical_topological_sort(directed.subgraph(required), key=lambda n: (nodes[n]["chapter_id"], n))]
        return {"target_id": target_id, "steps": steps, "ready": required == {target_id},
                "preview_only": view == "draft", "notice": "草稿预览" if view == "draft" else ""}

    def recommendations(self, node_id, student_id="", view="published"):
        graph = self.load_graph(view)
        if graph is None:
            return {"actions": [], "resources": [], "notice": "课程尚未发布，暂不推荐正式教学资源。"}
        self._node(graph, node_id)
        with self._writer() if student_id and view == "published" else self._lock:
            learner = self._derive(self._empty(), graph) if view == "draft" else self.load_learner(student_id, graph)
            state = learner["states"][node_id]
            path = self.learning_path(node_id, student_id if view == "published" else "", view)
            missing = [s for s in path["steps"] if s["node_id"] != node_id]
            selection = recommend_resources(graph, learner["states"], node_id)
            resource_targets = set(selection["frontier_node_ids"]) or {node_id}
            available = selection["resources"] if view == "published" else []
            node_titles = {n["id"]: n["title"] for n in graph["nodes"]}
            if view == "draft":
                action_type, reason, follow = "preview", "草稿结构预览，不形成正式教学判断。", "由教师审核节点、关系和资源。"
            elif state["due"]:
                action_type, reason, follow = "spaced_retest", state["reason"], "完成独立简短复测，再依据证据更新诊断。"
            elif state["status"] == "mastered":
                action_type, reason, follow = "continue", state["reason"], "进入后续节点；保留间隔复测计划。"
            elif missing:
                action_type, reason, follow = "check_prerequisites", "当前任务还有待核验的先修知识。", "这一步先核验：" + "、".join(node_titles[ident] for ident in selection["frontier_node_ids"]) + "；其余依赖在后续证据更新后再安排。"
            elif state["status"] == "needs_review":
                action_type, reason, follow = "remediate", state["reason"], "选择关联的审核材料补学，再完成减少提示的新任务。"
            else:
                action_type, reason, follow = "diagnose", state["reason"], "提交独立解释或作答，并引用原始证据形成诊断。"
            relevant_states = [learner["states"][ident] for ident in resource_targets | {node_id}]
            action = {"type": action_type, "node_id": node_id, "course_id": graph["id"], "course_version": graph["version"],
                      "reason": reason, "follow_up": follow,
                      "evidence_ids": sorted({ref for s in relevant_states for ref in s["evidence_ids"]}),
                      "diagnosis_ids": sorted({ref for s in relevant_states for ref in s["diagnosis_ids"]}), "resource_ids": [r["id"] for r in available],
                      "target_node_ids": sorted(resource_targets if action_type == "check_prerequisites" else {node_id}),
                      "policy_version": selection["rule_version"],
                      "state_snapshot": copy.deepcopy(learner["states"]),
                      "selection_trace": copy.deepcopy(selection)}
            key = hashlib.sha256(json.dumps(action, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()
            if student_id and view == "published":
                existing = next((a for a in learner["actions"] if a.get("idempotency_key") == key), None)
                if existing:
                    action = existing
                else:
                    action.update(id=uuid.uuid4().hex, idempotency_key=key, created_at=self._stamp(),
                                  learner_revision=learner["version"], observed_evidence_ids=[e["id"] for e in learner["evidence"]])
                    learner["actions"].append(action)
                    self._commit(learner)
            return {"actions": [action], "resources": available, "learner_version": learner["version"],
                    "learner": learner,
                    "selection": selection, "action_history": self._action_history(learner, graph, node_id),
                    "unavailable_count": len(selection["excluded_resources"]),
                    "notice": "草稿预览" if view == "draft" else ""}

    @staticmethod
    def _action_history(learner, graph, node_id):
        """Read-only temporal observations, never inferred causal effectiveness."""
        result = []
        for action in reversed(learner["actions"]):
            if action.get("course_id") != graph["id"] or node_id not in {action.get("node_id"), *action.get("target_node_ids", [])}:
                continue
            observations = [d for d in learner["diagnoses"] if d.get("follow_up_action_id") == action.get("id")]
            same_version = action.get("course_version") == graph["version"]
            result.append({"action_id": action.get("id"), "created_at": action.get("created_at"),
                           "type": action["type"], "course_version": action["course_version"],
                           "policy_version": action.get("policy_version", "legacy"),
                           "outcome": "version_changed" if not same_version else "observed" if observations else "pending",
                           "observations": [{"diagnosis_id": d["id"], "node_id": d["node_id"], "status": d["status"],
                                             "basis": d["basis"], "evidence_ids": d["evidence_ids"],
                                             "current_status": learner["states"].get(d["node_id"], {}).get("status", "unknown")}
                                            for d in observations],
                           "notice": "后续表现是时序关联记录，不证明由本次推荐导致；无后续核验不记失败。"})
            if len(result) == 10:
                break
        return result

    def record_resource_use(self, payload):
        _dict(payload, "资源使用记录")
        student_id = safe_id(payload.get("student_id"), "匿名编号")
        version = _integer(payload.get("course_version"), "课程版本", 1)
        with self._writer():
            graph = self._require_graph(version)
            node = self._node(graph, payload.get("node_id"))
            resource = next((r for r in graph["resources"] if r["id"] == payload.get("resource_id")), None)
            if not resource or node["id"] not in resource["node_ids"] or resource["review_status"] != "reviewed":
                _fail("该资源未审核或未关联当前知识节点。")
            learner = self._read_learner(student_id)
            self._expected(learner, payload.get("expected_version"))
            record = {"id": uuid.uuid4().hex, "student_id": student_id, "course_id": graph["id"], "course_version": version,
                      "node_id": node["id"], "resource_id": resource["id"], "created_at": self._stamp()}
            learner["resource_uses"].append(record)
            self._commit(learner)
        return self._mutation_result(learner, record, "resource_use")


store = CourseGraphStore()
