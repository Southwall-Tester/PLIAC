"""Grounded concept navigation over a LearnMargin lesson, independent of its TOC."""
import json
import hashlib
import re
from typing import Literal

from pydantic import Field
from learnmargin.models import Model


class ConceptNode(Model):
    id: str = Field(min_length=1, max_length=80)
    title: str = Field(min_length=1, max_length=100)
    definition: str = Field(min_length=1, max_length=2000)
    kind: Literal["concept", "entity", "method", "metric", "parameter"] = "concept"
    section_ids: list[str] = Field(min_length=1)
    evidence_section: str
    quote: str = Field(min_length=8, max_length=2000)


class ConceptRelation(Model):
    source: str
    target: str
    predicate: str = Field(min_length=1, max_length=100)
    directed: bool = False
    evidence_section: str
    quote: str = Field(min_length=8, max_length=2000)


class ConceptGraph(Model):
    nodes: list[ConceptNode] = Field(min_length=1, max_length=200)
    edges: list[ConceptRelation] = Field(max_length=600)


def section_text(section):
    return '\n'.join([section.title, section.explanation, section.worked_example,
                      *(n.explanation for n in section.source_notes)])


def validate_map(graph, lesson):
    sections = {s.id: s for s in lesson.sections}
    ids = {n.id for n in graph.nodes}
    if len(ids) != len(graph.nodes):
        raise ValueError('知识图谱的概念标识重复。')
    for node in graph.nodes:
        if not set(node.section_ids) <= sections.keys() or node.evidence_section not in node.section_ids:
            raise ValueError('知识图谱引用了不存在的讲义位置。')
    for edge in graph.edges:
        if edge.source not in ids or edge.target not in ids or edge.source == edge.target:
            raise ValueError('知识图谱关系的端点无效。')
    for item in [*graph.nodes, *graph.edges]:
        section = sections.get(item.evidence_section)
        if section is None or item.quote not in section_text(section):
            raise ValueError('知识图谱的引用无法在讲义中逐字定位。')
    result = graph.model_dump()
    result['provenance'] = 'lesson-grounded'
    for item in [*result['nodes'], *result['edges']]:
        item['source_refs'] = sections[item['evidence_section']].source_refs
    return result


class IndexedNode(Model):
    id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,79}$")
    title: str = Field(min_length=1, max_length=100)
    definition: str = Field(min_length=1, max_length=2000)
    kind: Literal["concept", "entity", "method", "metric", "parameter"] = "concept"
    section_ids: list[str] = Field(min_length=1)
    evidence_id: str


class IndexedRelation(Model):
    source: str
    target: str
    predicate: str = Field(min_length=1, max_length=100)
    directed: bool = False
    evidence_id: str


class IndexedGraph(Model):
    nodes: list[IndexedNode] = Field(min_length=1, max_length=200)
    edges: list[IndexedRelation] = Field(max_length=600)


class Vocabulary(Model):
    nodes: list[IndexedNode] = Field(min_length=1, max_length=200)


class TermDecision(Model):
    id: str
    atomic: bool
    domain_term: bool
    reason: str = Field(min_length=1, max_length=500)


class VocabularyAudit(Model):
    decisions: list[TermDecision] = Field(min_length=1, max_length=200)


class Relations(Model):
    edges: list[IndexedRelation] = Field(max_length=600)


async def generate_map(lesson, provider):
    passages = {}
    for section in lesson.sections:
        for paragraph in section_text(section).split("\n\n"):
            for start in range(0, len(paragraph), 1800):
                text = paragraph[start:start+1800]
                if len(text) >= 8:
                    passages[f"p{len(passages)+1}"] = {"section_id":section.id, "text":text}
    material = json.dumps({"sections":[{"id":s.id,"title":s.title} for s in lesson.sections],
                           "passages":passages}, ensure_ascii=False)
    instructions = ('先构建学科术语表，不画图、不提关系。每项是一种能独立定义的学科概念、对象、'
        '命名方法、指标或参数，kind 从指定类型中选。title 使用依据段落中实际出现的简短术语，'
        '不得用一句结论、操作指令、注意事项、目录标题或泛词来充当术语。'
        '并列概念分开，具体数值留在定义或例子里，不能为每个段落凑一个节点。'
        'section_ids 列相关小节；evidence_id 选出定义或解释这个术语的原文段落。'
        '只使用提供的资料，用讲义语言输出。')
    for attempt in range(2):
        vocabulary = await provider.generate(Vocabulary, instructions, material)
        try:
            ids = [n.id for n in vocabulary.nodes]
            if len(ids) != len(set(ids)):
                raise ValueError('概念标识重复')
            for node in vocabulary.nodes:
                evidence = passages[node.evidence_id]
                section = next((s for s in lesson.sections if s.id == evidence['section_id']), None)
                if section is None or node.title not in section_text(section):
                    raise ValueError('术语未出现在依据小节中')
                if evidence['section_id'] not in node.section_ids:
                    raise ValueError('术语依据与讲义映射不一致')
            break
        except (KeyError, ValueError):
            if attempt:
                raise ValueError('术语表未通过来源校验，讲义已保存，可重试。') from None
            instructions += ' 上次来源校验未通过：title 必须是所选段落所属小节中的原文术语，不能自行改写或扩写名称；依据小节必须在 section_ids 中。'
    audit = await provider.generate(VocabularyAudit,
        '独立审查术语表，不改写图谱。逐项判断 atomic（是否单一知识对象而非多个概念拼接）和 '
        'domain_term（是否可独立定义的学科术语）。目录安排、完整结论句、提醒、操作指令、'
        '泛词、具体例题数值均不能成为节点。每个候选 id 必须有且仅有一条决定，给出具体理由。'
        '判断不通过应明确 false，不因为有原文出处就当作合格概念。',
        material+'\n候选术语：'+vocabulary.model_dump_json())
    decisions = {d.id:d for d in audit.decisions}
    if len(decisions) != len(audit.decisions) or decisions.keys() != set(ids):
        raise ValueError('术语审校未覆盖全部候选，讲义已保存，可重试。')
    accepted, seen = [], set()
    for node in vocabulary.nodes:
        decision = decisions[node.id]
        title = re.sub(r"\s+", "", node.title).casefold()
        if decision.atomic and decision.domain_term and title not in seen:
            accepted.append(node)
            seen.add(title)
    if not accepted:
        raise ValueError('没有通过审校的知识概念，讲义已保存，可重试。')
    relations = await provider.generate(Relations,
        '仅在给定的已审核术语之间提取资料明确支持的语义关系。source/target 只能选术语 id。'
        'predicate 写具体关系，方向按实际含义，使用讲义语言（'+lesson.language+'）的简短动词短语，例如“用于评估”“决定”“导致”，不要用其他语言。evidence_id 选能支持整条关系的段落。'
        '同段出现、相邻章节、目录顺序不是语义关系，不自动连成先修链；无依据的边省略，'
        '允许孤立节点。不要增加、改名或恢复被剔除的术语，也不要求固定边数。',
        material+'\n已审核术语：'+json.dumps([n.model_dump() for n in accepted],ensure_ascii=False))
    result = {'nodes':[n.model_dump() for n in accepted], 'edges':[e.model_dump() for e in relations.edges]}
    try:
        for item in [*result['nodes'], *result['edges']]:
            evidence = passages[item.pop('evidence_id')]
            item.update(evidence_section=evidence['section_id'], quote=evidence['text'])
        result = validate_map(ConceptGraph.model_validate(result), lesson)
    except (KeyError, ValueError):
        raise ValueError('图谱关系或引用未通过校验，讲义已保存，可重试。') from None
    result.update(policy_version='concept-first-v3', vocabulary_audit=audit.model_dump())
    return result


def overview_map(lesson):
    """Read old lessons without another API call; never turn section order into edges."""
    nodes = []
    for concept in lesson.overview.concepts:
        related = [s for s in lesson.sections if concept.name.casefold() in section_text(s).casefold()]
        # Keep an overview-only concept navigable even when its wording differs in the body.
        ident = 'concept_' + hashlib.sha256(concept.name.encode()).hexdigest()[:12]
        nodes.append(dict(id=ident, title=concept.name, definition=concept.explanation,
                          section_ids=[s.id for s in related], evidence_section=None,
                          quote=concept.connections, source_refs=list(dict.fromkeys(
                              ref for s in related for ref in s.source_refs))))
    return dict(nodes=nodes, edges=[], provenance='authored-overview')
