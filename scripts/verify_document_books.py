"""Run a selected book range through ingestion and check every source span.

Writes a compact report for human content review. Uses a temporary store so the
check never changes the user's document library or course draft.
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import shutil
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from learning_agent.documents import DocumentStore  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description="核验书籍所选页的解析、建图和逐字引用")
    parser.add_argument("source", type=Path)
    parser.add_argument("--start", type=int, required=True, help="起始 PDF 物理页码，从 1 开始")
    parser.add_argument("--end", type=int, required=True, help="结束 PDF 物理页码，包含此页")
    parser.add_argument("--output", type=Path, required=True, help="本机核验报告 JSON 路径")
    args = parser.parse_args()
    source = args.source.resolve(strict=True)
    if args.output.resolve() == source:
        parser.error("报告路径须与原书不同")
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="pliac-book-check-") as tmp:
        store = DocumentStore(Path(tmp))
        job = store.create(source.name, "local", args.start, args.end)
        ident = job["id"]
        shutil.copyfile(source, store.source(ident))
        store.run(ident)
        status = store.status(ident)
        if status["status"] != "completed":
            raise RuntimeError(status.get("error") or status["status"])
        graph = store.graph(ident)
        pages = {page: store.page(ident, page) for page in range(args.start, args.end + 1)}
        checked = 0
        failures = []
        for kind in ("nodes", "edges"):
            for item in graph[kind]:
                for evidence in item["evidence"]:
                    checked += 1
                    text = pages[evidence["page"]]["text"]
                    if text[evidence["start"]:evidence["end"]] != evidence["quote"]:
                        failures.append({"kind": kind, "id": item["id"], "evidence": evidence})
        names = {node["id"]: node["title"] for node in graph["nodes"]}
        report = {
            "source_filename": source.name,
            "page_range": [args.start, args.end],
            "seconds": round(time.monotonic() - started, 2),
            "status": status["status"],
            "stats": status["stats"],
            "warnings": status["warnings"],
            "checked_source_spans": checked,
            "invalid_source_spans": failures,
            "concept_titles": list(names.values()),
            "edge_types": dict(Counter(edge["type"] for edge in graph["edges"])),
            "explicit_relations": [
                {"source": names[edge["source"]], "target": names[edge["target"]],
                 "type": edge["type"], "evidence": edge["evidence"]}
                for edge in graph["edges"] if edge["type"] != "cooccurs"
            ],
            "hierarchy": graph.get("hierarchy"),
            "graph": graph,
            "page_samples": [{"page": page, "ocr": data["ocr"], "text": data["text"]}
                             for page, data in pages.items()],
            "human_review": {"status": "pending", "note": "逐字定位通过后仍需人工检查概念与关系语义"},
        }
        store.executor.shutdown(wait=True)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: report[key] for key in ("source_filename", "page_range", "seconds", "stats", "checked_source_spans", "edge_types")}, ensure_ascii=False))
    print(str(args.output.resolve()))
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
