"""Compact model review with exact, bounded edits; structural changes use full review."""
import re
from typing import Literal

from pydantic import Field, model_validator

from .models import GeneratedLessonSection, Model


class TextCorrection(Model):
    path: str = Field(max_length=100, description="点分路径，例如explanation、practice.0.answer。仅修改文字，不改编号、引用或结构。")
    before: str = Field(min_length=1, max_length=30000, description="原字段中唯一出现的原文片段，必须精确匹配。")
    after: str = Field(max_length=30000, description="替换片段；只修正问题，保留其余正确讲解。")
    reason: str = Field(min_length=1, max_length=400)


class SectionAudit(Model):
    verdict: Literal["accept", "correct", "full_review"]
    findings: str = Field(min_length=1, max_length=600,
        description="简述实质问题；全部通过时一句话说明。不要逐段复述正确内容。")
    corrections: list[TextCorrection] = Field(max_length=12)

    @model_validator(mode="after")
    def consistent(self):
        if self.verdict == "accept" and self.corrections:
            raise ValueError("通过的审校不应包含修订。")
        if self.verdict == "correct" and not self.corrections:
            raise ValueError("局部修订须提供修正片段。")
        return self


EDITABLE = re.compile(
    r"(?:title|explanation|worked_example|"
    r"source_notes\.\d+\.(?:explanation|relation)|"
    r"practice\.\d+\.(?:prompt|hint|answer|answer_key|options\.\d+\.text)|"
    r"study_prompts\.\d+\.(?:when|task|check|answer|answer_key|options\.\d+\.text)|"
    r"pause\.(?:when|activity|resume)|study_load\.rationale)\Z")


def apply_audit(section: GeneratedLessonSection, audit: SectionAudit) -> GeneratedLessonSection:
    if audit.verdict == "full_review":
        raise ValueError("需要完整审校。")
    data = section.model_dump()
    for correction in audit.corrections:
        if not EDITABLE.fullmatch(correction.path):
            raise ValueError("审校修订路径不在允许范围内。")
        parts = correction.path.split(".")
        target = data
        try:
            for part in parts[:-1]:
                target = target[int(part)] if isinstance(target, list) else target[part]
            value = target[parts[-1]]
            if not isinstance(value, str) or value.count(correction.before) != 1:
                raise ValueError("审校原文须唯一且精确匹配。")
            target[parts[-1]] = value.replace(correction.before, correction.after, 1)
        except (KeyError, IndexError, TypeError) as exc:
            raise ValueError("审校修订路径无效。") from exc
    # Revalidate options, answers, load and every other generated-content invariant.
    return GeneratedLessonSection.model_validate(data)


def audit_prompt(language, planned, plan, material, draft):
    return (
        f"审校讲义，输出语言{language}。逐项核查定义、推理、计算、适用条件、量词、边界、"
        "来源归因与练习答案；核查讲解是否解释了目标，使用术语之前是否解释其含义和作用，"
        "是否给出完整示范，是否有把关键知识缺口推给读者的占位话。"
        "核查学习提示的位置与难度、选项唯一性、答案正确性、预计负荷和休息安排是否合理。"
        "必要定义、条件或依赖结论缺乏材料依据时，必须full_review并说明缺口。"
        "按教学目标检查质量，不为润色而重写正确内容。findings只列实质问题，检查通过一句话说明。"
        "全部正确时accept且corrections=[]；"
        "少量文字或答案问题用correct，提供精确路径及唯一原文片段，覆盖全部发现的问题；"
        "任何结构性修改、缺少练习/必要讲解、无法通过局部文字修复或复杂论证需进一步推敲时用full_review。"
        "不得改id、source_refs、引用编号或数据结构。不得把猜测当来源事实。"
        f"\n本节计划：{planned.model_dump_json()}\n全篇分工：{plan}"
        f"\n真实材料：{material}\n待审校JSON：{draft}"
    )
