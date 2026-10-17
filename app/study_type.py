"""研究类型保守识别：明确发表类型优先，标题和自身方法描述辅助。

分级仅是研究设计的粗略映射，不是文献质量或临床结论正确率。
"""
import re
import unicodedata

from .integrity import integrity_details, normalize_terms

GRADE_ORDER = {"High": 0, "Moderate": 1, "Low": 2, "Very low": 3, "N/A": 4}
GRADES = {
    "meta_analysis": "High", "systematic_review": "High", "guideline": "High",
    "randomized_controlled_trial": "Moderate", "clinical_trial": "Moderate",
    "cohort": "Low", "case_control": "Low", "case_report": "Very low",
    "review": "N/A", "basic": "N/A", "other": "N/A", "notice": "N/A",
}
PT_TYPES = {
    "meta-analysis": "meta_analysis", "systematic review": "systematic_review",
    "guideline": "guideline", "practice guideline": "guideline",
    "consensus development conference": "guideline",
    "consensus development conference, nih": "guideline",
    "randomized controlled trial": "randomized_controlled_trial",
    "controlled clinical trial": "clinical_trial", "clinical trial": "clinical_trial",
    "adaptive clinical trial": "clinical_trial", "pragmatic clinical trial": "clinical_trial",
    "clinical trial, phase i": "clinical_trial", "clinical trial, phase ii": "clinical_trial",
    "clinical trial, phase iii": "clinical_trial", "clinical trial, phase iv": "clinical_trial",
    "case reports": "case_report", "review": "review",
}
NON_RESEARCH = {"editorial", "comment", "letter", "news", "clinical trial protocol"}
PATTERNS = {
    "meta_analysis": r"\b(?:meta[- ]analys(?:is|es)|network meta[- ]analysis)\b",
    "systematic_review": r"\bsystematic (?:literature )?review\b",
    "guideline": r"\b(?:clinical practice guideline|practice guideline|consensus (?:statement|recommendation))s?\b",
    "randomized_controlled_trial": r"\b(?:randomi[sz]ed(?: controlled)? (?:clinical )?trial|rct|randomly assigned)\b",
    "clinical_trial": r"\b(?:clinical trial|phase (?:[1-4]|i{1,3}|iv) (?:trial|study)|open[- ]label (?:trial|study))\b",
    "cohort": r"\bcohort (?:study|analysis|design)\b",
    "case_control": r"\bcase[- ]control (?:study|analysis|design)\b",
    "case_report": r"\bcase (?:report|series|study)\b",
    "basic": r"\b(?:in vitro|in vivo|mouse model|murine|cell line|preclinical)\b",
    "review": r"\b(?:narrative review|literature review|review)\b",
}
_SECTION = re.compile(
    r"(?:^|\n|(?<=[.!?])\s+)(background|introduction|objectives?|aims?|purpose|"
    r"methods?|design|materials and methods|patients and methods|results?|"
    r"conclusions?|discussion|limitations?):\s*", re.I,
)
_SELF = re.compile(
    r"^(?:we (?:performed|conducted|undertook|report|present|designed)\b|"
    r"(?:patients|participants|subjects) were (?:randomly assigned|randomi[sz]ed)\b|"
    r"(?:a|an|this) (?:(?:prospective|retrospective|randomi[sz]ed|controlled|clinical|"
    r"systematic|literature|cohort|case|meta[- ]analysis|open[- ]label)\b))", re.I,
)
_REFERRED = re.compile(r"\b(?:prior|previous|earlier|published|other|existing|future)\b", re.I)
_PROTOCOL = re.compile(r"\b(?:study protocol|trial protocol|protocol for|protocol of|planned|proposed|will conduct|will perform)\b", re.I)
_TITLE_REFERENCE = re.compile(r"^(?:comment(?:ary)? on|response to|reply to|letter to|erratum|correction|retraction|expression of concern)\b", re.I)


def _normalize(text):
    text = unicodedata.normalize("NFKC", text or "").lower()
    text = re.sub(r"[\u2010-\u2015]", "-", text)
    # 否定/非随机不能被 randomized 子串误判。
    return re.sub(r"\b(?:non[- ]?|not )randomi[sz]ed\b", "nonrandomized", text)


def _resolve(labels):
    labels = set(labels)
    if "meta_analysis" in labels:
        labels.difference_update({"systematic_review", "review"})
    elif "systematic_review" in labels:
        labels.discard("review")
    if "randomized_controlled_trial" in labels:
        labels.discard("clinical_trial")
    # 病例报告附带叙述性文献回顾，不升级为高等级综述。
    if "case_report" in labels:
        labels.discard("review")
    return next(iter(labels)) if len(labels) == 1 else "other"


def _from_description(text):
    text = _normalize(text)
    if _PROTOCOL.search(text) or _REFERRED.search(text) or _TITLE_REFERENCE.search(text):
        return "other"
    return _resolve(label for label, pattern in PATTERNS.items() if re.search(pattern, text))


def _from_title(title):
    """设计须作为标题或冒号后小标题的自述，提及某类研究不够。"""
    labels = []
    for part in re.split(r":\s*|\s+[\u2010-\u2015-]\s+", title):
        part = _normalize(part).strip()
        prefix = re.sub(r"^(?:(?:a|an|the)\s+)?(?:(?:prospective|retrospective|longitudinal)\s+)?", "", part)
        own = {label for label, pattern in PATTERNS.items() if re.match(pattern, prefix)}
        if not own:
            continue
        label = _from_description(part)
        # 叙述性 review 讨论 meta-analysis，不因此变成 meta-analysis 本身。
        if own == {"review"}:
            label = "review"
        if label == "other":
            return "other"
        labels.append(label)
    return _resolve(labels) if labels else None


def _own_methods(text):
    """仅检查方法/设计小节，或明确自述本研究的句子；背景与讨论不扫描。"""
    matches = list(_SECTION.finditer(text))
    if matches:
        for i, match in enumerate(matches):
            if match.group(1).lower() in {"method", "methods", "design", "materials and methods", "patients and methods"}:
                yield text[match.end():matches[i + 1].start() if i + 1 < len(matches) else len(text)]
    else:
        for sentence in re.split(r"(?<=[.!?])\s+|\n+", text):
            if _SELF.search(sentence.strip()):
                yield sentence.strip()


def classify(text, pubtypes=None, *, title=None):
    """返回 (类型, 参考分级)。text 为摘要，title 单独传入以免背景污染标题判定。"""
    pts = normalize_terms(pubtypes)
    if integrity_details(pts)["is_notice"]:
        return "notice", "N/A"
    if "clinical trial protocol" in pts or _PROTOCOL.search(title or ""):
        return "other", "N/A"
    metadata = {PT_TYPES[p] for p in pts if p in PT_TYPES}
    if metadata:
        label = _resolve(metadata)
        return label, GRADES[label]
    if pts & NON_RESEARCH:
        return "other", "N/A"
    if title:
        label = _from_title(title)
        if "observational study" in pts and label not in {"cohort", "case_control"}:
            label = "other" if label else None
        if label and label != "other":
            return label, GRADES[label]
        if label == "other":
            return "other", "N/A"  # 标题设计冲突或只在讨论其他研究，不由摘要强行升级。
    descriptions = []
    for section in _own_methods(text or ""):
        for sentence in re.split(r"(?<=[.!?])\s+|\n+", section):
            # 不从“既往研究/未来计划”的描述推断本研究设计。
            if not _REFERRED.search(sentence):
                label = _from_description(sentence)
                if label != "other":
                    descriptions.append(label)
    label = _resolve(descriptions)
    if "observational study" in pts and label not in {"cohort", "case_control"}:
        label = "other"
    return label, GRADES[label]
