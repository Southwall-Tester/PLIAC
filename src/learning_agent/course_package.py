"""Data-driven immutable course releases, using the shared learning workspace.

A package is a storage/provenance adapter, not a separate learning application.
Generated handouts and learner records live alongside installed artifacts.
"""
import gzip
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import zipfile

from .course_graph import ROOT, CourseGraphError, CourseGraphStore, validate_graph

PACKAGES = ROOT / "data/courses"


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def packages():
    result = {}
    for path in sorted(PACKAGES.glob("*/package.json")):
        config = read(path)
        if config["id"] in result:
            raise CourseGraphError("课程包编号重复。", 500)
        result[config["id"]] = path
    return result


class PackagedCourseStore(CourseGraphStore):
    content_editable = False

    def __init__(self, default_store, package_path):
        self.package_path = Path(package_path)
        self.config = read(self.package_path)
        self.assets = self.package_path.parent
        directory = (default_store.output_dir / self.config["runtime_path"]).resolve()
        if not directory.is_relative_to(default_store.output_dir) or directory == default_store.output_dir:
            raise CourseGraphError("课程包记录路径无效。", 500)
        super().__init__(seed_path=self.asset(self.config["graph"]), output_dir=directory, clock=default_store.clock)
        policy = self.config.get("assessment", {})
        if policy:
            from .assessment import ObjectiveChoiceAssessment
            if policy.get("engine") != "objective_choice" or not policy.get("rule_id"):
                raise CourseGraphError("课程评分契约无效。", 500)
            self.assessment = ObjectiveChoiceAssessment(self, policy["rule_id"])

    def asset(self, name):
        path = (self.assets / name).resolve()
        # Versioned descriptors may reference shared assets under data/.
        if not path.is_relative_to(PACKAGES.parent.resolve()):
            raise CourseGraphError("课程资源路径无效。", 500)
        return path

    def load_graph(self, view="published", version=None):
        fixed = self.config["version"]
        if view not in {"draft", "published"} or (version is not None and (type(version) is not int or version != fixed)):
            raise CourseGraphError(f"该课程包提供固定的 v{fixed} 内容。", 409)
        graph = read(self.seed_path)
        if graph["id"] != self.config["id"] or graph["version"] != fixed:
            raise CourseGraphError("课程包与图谱版本不一致。", 500)
        validate_graph(graph)
        # Extra authored policies are data, not course-ID branches. Nodes remain
        # unchanged so old learner evidence retains its original fingerprints.
        graph["study"] = self.config.get("study", {})
        graph["activities"] = self.config.get("activities", [])
        return graph

    def publication(self):
        return dict(draft_version=self.config["version"], published_version=None,
                    demo_version=self.config["version"], delivery_mode=self.config.get("delivery_mode", "packaged"),
                    notice=self.config.get("notice", ""))

    def concept_map(self):
        if not self.config.get("concept_map"):
            return None
        result = read(self.asset(self.config["concept_map"]))
        result["sources"] = [*self.load_graph()["sources"], *result.get("sources", [])]
        return result

    def save_graph(self, *args, **kwargs):
        raise CourseGraphError("该版本课程内容只读，请在独立课程中编辑。", 409)

    def publish(self, *args, **kwargs):
        raise CourseGraphError("预装课程不作为人工审核后的正式课程发布。", 409)

    def _published_history(self):
        return []

    def source_summary(self):
        bundle = self.config.get("handouts")
        if not bundle:
            return None
        info = read(self.asset(bundle["manifest"]))
        return {key: info[key] for key in ("source_pages", "source_characters", "candidate_nodes", "candidate_edges", "cooccurrence_edges", "verified_quotes") if key in info}

    def ensure_handouts(self):
        """Install a verified release once, preserving subsequent generated jobs."""
        target = self.output_dir / "handouts"
        bundle = self.config.get("handouts")
        if not bundle:
            return target
        info = read(self.asset(bundle["manifest"]))
        marker = target / "fixture.json"
        def installed():
            return marker.is_file() and read(marker).get("sha256") == info["handouts_sha256"]
        if installed():
            return target
        with self._writer():
            if installed():
                return target
            if target.exists():
                raise CourseGraphError("预装讲义版本不一致，请检查课程包。", 409)
            archive_path = self.asset(bundle["archive"])
            if hashlib.sha256(archive_path.read_bytes()).hexdigest() != info["handouts_sha256"]:
                raise CourseGraphError("课程资源校验失败。", 500)
            with tempfile.TemporaryDirectory(dir=self.output_dir) as tmp:
                stage = Path(tmp) / "handouts"
                stage.mkdir()
                with zipfile.ZipFile(archive_path) as archive:
                    for item in archive.infolist():
                        path = (stage / item.filename).resolve()
                        if not path.is_relative_to(stage.resolve()) or item.is_dir():
                            raise CourseGraphError("课程资源路径无效。", 500)
                        path.parent.mkdir(parents=True, exist_ok=True)
                        with archive.open(item) as source, path.open("wb") as destination:
                            shutil.copyfileobj(source, destination)
                (stage / "fixture.json").write_text(json.dumps({"sha256": info["handouts_sha256"]}), encoding="utf-8")
                stage.rename(target)
        return target

    def material_documents(self, documents):
        if not self.config.get("source_snapshot"):
            return documents
        snapshot = json.loads(gzip.decompress(self.asset(self.config["source_snapshot"]).read_bytes()))
        return SnapshotDocuments(snapshot, documents)


class SnapshotDocuments:
    """Use a course's archived source units, delegate other documents normally."""
    def __init__(self, snapshot, fallback):
        self.snapshot, self.fallback = snapshot, fallback
        self.pages = {page["page"]: page for page in snapshot["pages"]}

    def status(self, ident):
        job = self.snapshot["job"]
        return {**job, "archived_text": True} if ident == job["id"] else self.fallback.status(ident)

    def page(self, ident, index):
        if ident != self.snapshot["job"]["id"]:
            return self.fallback.page(ident, index)
        if index not in self.pages:
            raise CourseGraphError("课程资料中没有该页。", 404)
        return self.pages[index]
