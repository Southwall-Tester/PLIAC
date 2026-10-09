"""Package an existing textbook candidate snapshot and authored course guides.

This is a lossless snapshot importer, not a concept/relationship generator.
Original OCR and candidate graph stay separate from the authored lesson graph.
"""
from __future__ import annotations

import argparse
import asyncio
import gzip
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import time
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from learning_agent.course_graph import validate_graph
from learnmargin.models import Concept, Lesson, LessonSection, Overview, Practice, SourceCitation, StudyPrompt
from learnmargin.rendering import render_lesson
from learnmargin.storage import atomic_json

DEST = ROOT / "data/courses/computer_organization_demo"
NOTICE = "历史候选图谱：共现表示原文同段出现，不作为先修或掌握依据；候选术语保留原始抽取结果。"


def digest(data):
    return hashlib.sha256(data).hexdigest()


def job_id(course_id, chapter):
    return hashlib.sha256(f"{course_id}:v1:{chapter}".encode()).hexdigest()[:32]


def chapter_ids(node, sections):
    pages = {e["page"] for e in node["evidence"]}
    return [s["id"] for s in sections if any(s["start_page"] <= p <= s["end_page"] for p in pages)]


def project_candidates(raw, sections, document_id, chapter=""):
    nodes = []
    for original in raw["nodes"]:
        memberships = chapter_ids(original, sections)
        # Front matter remains visible in the full snapshot, without inventing a chapter.
        if chapter and chapter not in memberships:
            continue
        evidence = original["evidence"]
        if chapter:
            selected = next(s for s in sections if s["id"] == chapter)
            evidence = [e for e in evidence if selected["start_page"] <= e["page"] <= selected["end_page"]]
        refs = list(dict.fromkeys(f'{document_id}:{e["page"]}' for e in evidence))
        nodes.append(dict(id=original["id"], title=original["title"],
                          definition=evidence[0]["quote"], quote=evidence[0]["quote"],
                          family_index=next((i for i,s in enumerate(sections) if s["id"] in memberships),0),
                          section_ids=memberships, source_refs=refs[:8], evidence_count=len(evidence),
                          review_status="draft", origin="legacy_candidate_snapshot"))
    ids = {n["id"] for n in nodes}
    edges = []
    for original in raw["edges"]:
        if original["source"] not in ids or original["target"] not in ids:
            continue
        evidence = original["evidence"]
        if chapter:
            selected = next(s for s in sections if s["id"] == chapter)
            evidence = [e for e in evidence if selected["start_page"] <= e["page"] <= selected["end_page"]]
        if not evidence:
            continue
        cooccurs = original["type"] == "cooccurs"
        edges.append(dict(source=original["source"], target=original["target"],
                          predicate="同段共现" if cooccurs else "原文包含候选", directed=not cooccurs,
                          quote=evidence[0]["quote"], relation_type=original["type"],
                          source_refs=list(dict.fromkeys(f'{document_id}:{e["page"]}' for e in evidence))[:8],
                          review_status="draft", original_id=original["id"]))
    return dict(nodes=nodes, edges=edges, provenance="legacy_candidate_snapshot", notice=NOTICE)


def course_graph(guide, document_id):
    sections = guide["sections"]
    graph = dict(schema_version=1, id=guide["id"], version=1, title=guide["title"],
                 overview=guide["overview"], delivery_mode="source_demo", resources=[], edges=[],
                 chapters=[dict(id=s["id"], title=s["title"], description=s["objective"],
                     source_ranges=[dict(document_id=document_id,start_page=s["start_page"],end_page=s["end_page"])]) for s in sections],
                 sources=[dict(id="textbook", title=guide["source_title"], kind="uploaded_textbook", url="", locator="上传教材的 PDF 物理页码；OCR 原文随课程快照保存。")],
                 review_policy={"intervals_days": [1, 7, 30]}, nodes=[])
    for section in sections:
        ident = section["id"]
        graph["nodes"].append(dict(id=ident, chapter_id=ident, title=section["title"],
            description=section["explanation"], objectives=[section["objective"]], aliases=[],
            misconception=section["pitfall"], source_ids=["textbook"], review_status="draft",
            check_question=section["question"], expected_answer=section["answer"],
            check_task=dict(id="check_"+ident, version=1, rubric=[section["answer"]],
                            hint_levels=[section["hint"], section["objective"], section["pitfall"], section["answer"]]),
            document_id=document_id, document_evidence=[{"page":p} for p in section["source_pages"]],
            lesson_content=[dict(id="explanation",heading="教材导读",text=section["explanation"]),
                            dict(id="example",heading="自编算例",text=section["worked_example"])]))
    validate_graph(graph)
    return graph


def lesson_for(guide, selected, document_id, title):
    refs = sorted({page for s in selected for page in s["source_pages"]})
    return Lesson(title=title, subtitle=guide.get("subtitle", "教材导读"), scope_note=guide.get("scope_note", ""),
        overview=Overview(summary=guide["overview"], concepts=[Concept(name=s["title"],explanation=s["objective"],connections=s["pitfall"]) for s in selected],
                          learning_path=[s["objective"] for s in selected],
                          prerequisites=guide.get("prerequisites", [])),
        sections=[LessonSection(id=s["id"], title=s["title"], source_refs=[f"{document_id}:{p}" for p in s["source_pages"]],
            explanation=s["explanation"], worked_example=s["worked_example"],
            practice=[Practice(id="practice_"+s["id"],prompt=s["question"],hint=s["hint"],answer=s["answer"])],
            study_prompts=[StudyPrompt(id="check_"+s["id"],kind="action",placement="after_example",
                when="核对算例后",task="先独立完成自检题，再翻到参考答案核对。记录你漏掉的条件，返回原材料确认。",check="把计算结果与成立条件分开写；阅读完成不代表已掌握。")]) for s in selected],
        review_plan=guide.get("review_plan", []),
        method_chapters=[1, 4], sources=[SourceCitation(ref=f"{document_id}:{p}",document=guide["source_title"],label=f"PDF 第 {p} 页") for p in refs])


async def build(source, destination):
    started = time.perf_counter()
    guide = json.loads((destination / "guide.json").read_text(encoding="utf-8"))
    raw_bytes = (source / "graph.json").read_bytes()
    raw = json.loads(raw_bytes)
    job = json.loads((source / "job.json").read_text(encoding="utf-8"))
    pages = [json.loads(p.read_text(encoding="utf-8")) for p in (source / "pages").glob("*.json")]
    pages.sort(key=lambda p:p["page"])
    texts = {p["page"]:p["text"] for p in pages}
    assert len(texts) == job["stats"]["pages"], "Incomplete source page cache"
    checked = 0
    for item in raw["nodes"]+raw["edges"]:
        for evidence in item["evidence"]:
            assert evidence["quote"] in texts[evidence["page"]], (item.get("id"), evidence["page"])
            checked += 1
    snapshot = dict(job=job, graph=raw, pages=pages,
                    outline=json.loads((source/"outline.json").read_text(encoding="utf-8")))
    snapshot_bytes = gzip.compress(json.dumps(snapshot,ensure_ascii=False,separators=(",", ":")).encode("utf-8"),mtime=0)
    (destination / "source-snapshot.json.gz").write_bytes(snapshot_bytes)
    atomic_json(destination / "course.json", course_graph(guide,raw["id"]))
    manifest = dict(schema_version=1,id=guide["id"],version=1,source_document_id=raw["id"],
        source_title=raw["title"],source_graph_sha256=digest(raw_bytes),snapshot_sha256=digest(snapshot_bytes),
        source_pages=len(pages),source_characters=sum(map(len,texts.values())),candidate_nodes=len(raw["nodes"]),
        candidate_edges=len(raw["edges"]),cooccurrence_edges=sum(e["type"]=="cooccurs" for e in raw["edges"]),
        verified_quotes=checked,guide_sections=len(guide["sections"]),notice=NOTICE, jobs=[])
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        for chapter in ["", *[s["id"] for s in guide["sections"]]]:
            selected = [s for s in guide["sections"] if not chapter or s["id"]==chapter]
            title = selected[0]["title"] if chapter else guide["title"]
            ident = job_id(guide["id"],chapter)
            folder = root/"jobs"/ident
            folder.mkdir(parents=True)
            lesson = lesson_for(guide,selected,raw["id"],title)
            rendered = await render_lesson(lesson,folder)
            projected = project_candidates(raw,guide["sections"],raw["id"],chapter)
            atomic_json(folder/"knowledge-map.json",projected)
            units = [{"index":p["page"],"label":f'PDF 第 {p["page"]} 页',"text":p["text"]} for p in pages]
            # A cross-chapter concept can reference any original evidence page.
            atomic_json(folder/"materials.json",dict(documents=[dict(id=raw["id"],name=raw["title"],units=units)],origins={}))
            metadata=dict(id=ident,course_id=guide["id"],course_version=1,source_view="source_demo",chapter_id=chapter,
                status="completed",created_at="2026-10-09T00:00:00Z",title=title,page_count=rendered["page_count"],
                origin="authored_guide_and_legacy_snapshot",candidate_nodes=len(projected["nodes"]),candidate_edges=len(projected["edges"]))
            atomic_json(folder/"job.json",metadata)
            manifest["jobs"].append(metadata)
            print(f'{title}: {len(projected["nodes"])} nodes, {len(projected["edges"])} edges, {rendered["page_count"]} PDF pages',flush=True)
        with zipfile.ZipFile(destination/"handouts.zip","w",compression=zipfile.ZIP_DEFLATED,compresslevel=9) as archive:
            for path in sorted(root.glob("jobs/*/*")):
                if path.name in {"job.json","lesson.json","lesson.html","lesson.pdf","validation.json","knowledge-map.json","materials.json"}:
                    archive.write(path,path.relative_to(root).as_posix())
    manifest["handouts_sha256"] = digest((destination/"handouts.zip").read_bytes())
    manifest["build_seconds"] = round(time.perf_counter()-started,3)
    atomic_json(destination/"manifest.json",manifest)
    # Every packaged source course registers through the same descriptor format.
    # Existing descriptors preserve their historical learner-record paths.
    descriptor = destination / "package.json"
    if not descriptor.exists():
        atomic_json(descriptor, dict(schema_version=1, id=guide["id"], version=1, graph="course.json",
            runtime_path=f"packages/{guide['id']}/v1", delivery_mode="source_demo",
            notice="教材导读；作答保留为原始证据，需教师复核后判断掌握。",
            presentation=guide.get("presentation", {}), source_snapshot="source-snapshot.json.gz",
            handouts=dict(archive="handouts.zip", manifest="manifest.json")))
    print(json.dumps({k:v for k,v in manifest.items() if k!="jobs"},ensure_ascii=False),flush=True)


if __name__ == "__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source",type=Path,required=True)
    parser.add_argument("--destination",type=Path,default=DEST)
    args=parser.parse_args()
    asyncio.run(build(args.source,args.destination))
