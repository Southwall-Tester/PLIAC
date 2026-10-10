"""Team-curated public resources kept outside course knowledge data.

Course knowledge (including the immutable acceptance fixture) is never edited here. A catalog adds
selected public materials (official videos, documentation) for an existing course's nodes. Entries are
labelled ``curated_catalog``: chosen by the project team, not automatically source-validated and never
presented as human review of the course.
"""
from __future__ import annotations

import json
import re
from functools import lru_cache

from learning_agent.course_graph import ROOT, RESOURCE_FORMATS

CATALOG_DIR = ROOT / "data" / "resource_catalog"
ORIGIN = "curated_catalog"


@lru_cache(maxsize=32)
def _load(course_id: str, mtime: float):
    path = CATALOG_DIR / f"{course_id}.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("course_id") != course_id:
        return ()
    return tuple(data.get("resources", []))


def catalog_resources(graph):
    """Valid catalog entries for this course; entries pointing at unknown nodes or formats are skipped."""
    course_id = graph.get("id")
    if not isinstance(course_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", course_id):
        return []
    path = CATALOG_DIR / f"{course_id}.json"
    if not path.is_file():
        return []
    nodes = {node["id"] for node in graph["nodes"]}
    result = []
    for item in _load(course_id, path.stat().st_mtime):
        url = item.get("url", "")
        if (not isinstance(item.get("id"), str) or item.get("format") not in RESOURCE_FORMATS
                or not url.startswith("https://") or not item.get("title")):
            continue
        node_ids = [n for n in item.get("node_ids", []) if n in nodes]
        if not node_ids:
            continue
        result.append({**item, "node_ids": node_ids, "prerequisite_ids": [n for n in item.get("prerequisite_ids", []) if n in nodes],
                       "review_status": ORIGIN})
    return result


def usable_resources(graph):
    """Course resources that passed review or automatic validation, plus the curated catalog."""
    own = [item for item in graph.get("resources", []) if item.get("review_status") in ("reviewed", "auto_validated")]
    seen = {item["id"] for item in own}
    return own + [item for item in catalog_resources(graph) if item["id"] not in seen]
