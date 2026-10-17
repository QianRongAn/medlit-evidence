"""抽取摘要结论并报告完整性；未经验证的语义判定明确弃权。

获益/伤害措辞不能推导对用户命题的支持/反对，研究类型也不能推导结论
正确率。在问题与文献的 PICO 对齐及独立评估就绪前，不计算方向或置信度。
"""
import re
from .integrity import document_integrity, is_usable_evidence

ASSESSMENT_VERSION = "2"
ASSESSMENT_NOTE = (
    "尚未验证问题与文献的人群、干预、对照和结局是否一致；"
    "不自动判断支持、反对或证据冲突，也不计算结论置信度。"
)
_SENT_SPLIT = re.compile(r"(?<=[.!?])\s+")
_CONCLUSION_PREFIX = (
    "conclusion", "conclusions", "findings", "finding", "interpretation",
    "in summary", "overall",
)
_SKIP_PREFIX = ("discussion", "limitation", "limitations", "registration")


def extract_conclusion(doc):
    """摘录候选结论原句；不保证该句回答了用户的问题。"""
    text = (doc.get("abstract") or "").strip()
    sents = [s.strip() for s in _SENT_SPLIT.split(text) if len(s.strip()) > 15]
    if not sents:
        return doc.get("title") or ""
    for s in reversed(sents):
        if s.lower().startswith(_CONCLUSION_PREFIX):
            return s
    for s in reversed(sents):
        if not s.lower().startswith(_SKIP_PREFIX):
            return s
    return sents[-1]


def analyze_evidence(docs):
    """返回候选结论、完整性计数和显式的未评估状态。

    保留旧字段名便于客户端迁移：confidence/conflict 为 None，表示未评估，
    而非低置信度或已证明无冲突；未评估文献不得计为中立或无效。
    """
    items = []
    counts = {"retracted": 0, "concern": 0, "corrected": 0}
    notices = 0
    for d in docs:
        details = document_integrity(d)
        integrity = details["integrity"]
        flags = set(details["integrity_flags"])
        for flag in counts:
            counts[flag] += flag in flags
        notices += details["is_notice"]
        items.append({
            "pmid": d.get("pmid"),
            "title": d.get("title"),
            "polarity": "unassessed",
            "conclusion": extract_conclusion(d),
            "grade": d.get("grade"),
            "year": d.get("year"),
            "integrity": integrity,
            "integrity_flags": [flag for flag in counts if flag in flags],
            "is_notice": details["is_notice"],
        })

    usable_count = sum(is_usable_evidence(it) for it in items)
    warnings = []
    if counts["retracted"]:
        warnings.append(f"有 {counts['retracted']} 篇文献已撤稿，不用于回答")
    if counts["concern"]:
        warnings.append(f"有 {counts['concern']} 篇文献被标记存疑（Expression of Concern）")
    if counts["corrected"]:
        warnings.append(f"有 {counts['corrected']} 篇文献存在更正/重发记录，请核对关联版本")
    if notices:
        warnings.append(f"有 {notices} 篇学术通知，仅供核查关联记录，不用于回答")

    return {
        "assessment_version": ASSESSMENT_VERSION,
        "assessment_status": "unassessed" if usable_count else "no_usable_evidence",
        "assessment_note": ASSESSMENT_NOTE,
        "verdict": "证据方向待核对" if usable_count else "无可用相关证据",
        "conflict": None,
        "confidence": None,
        "support_count": 0,
        "against_count": 0,
        "neutral_count": 0,
        "unassessed_count": usable_count,
        "conclusions": items,
        "retracted_count": counts["retracted"],
        "concern_count": counts["concern"],
        "corrected_count": counts["corrected"],
        "notice_count": notices,
        "integrity_warning": "；".join(warnings) or None,
    }
