"""结论极性识别、证据冲突检测与置信度评分。

这是本产品相对通用大模型的核心差异点：不给出"标准答案"，
而是显式识别每篇文献结论的方向（支持 / 反对 / 中立），
检测同一问题下是否存在对立的结论（证据冲突），并给出证据置信度。
"""

import re
from datetime import date

from .study_type import GRADE_ORDER

# 强正向短语（明确有益，含"未增加风险"类安全性结论）
STRONG_POS = [
    "reduced risk", "reduced mortality", "improved survival", "lower risk",
    "prolonged survival", "superior", "non-inferior", "noninferior",
    "no increase in", "did not increase",
]

# 强负向短语（明确无效 / 有害 / 有争议）
STRONG_NEG = [
    "no significant", "no benefit", "no difference", "did not", "failed to",
    "not associated", "no association", "inconclusive", "conflicting",
    "controversial", "increased risk", "increased mortality", "higher risk",
    "higher mortality", "worse", "adverse",
]

# 弱正向词（可被否定词抵消）
WEAK_POS = [
    "reduce", "reduces", "reduced", "reduction", "lower", "lowered",
    "decrease", "decreased", "improve", "improved", "improvement",
    "benefit", "beneficial", "effective", "efficacy", "prolong", "prolonged",
    "fewer", "better", "safe",
]

NEGATORS = ["no ", "not ", "did not", "failed to", "without", "lack of", "absence of"]

_SENT_SPLIT = re.compile(r"(?<=[.!?])\s+")
_CONCLUSION_PREFIX = (
    "conclusion", "conclusions", "findings", "finding", "interpretation",
    "in summary", "overall",
)
_SKIP_PREFIX = ("discussion", "limitation", "limitations", "registration")

GRADE_BASE = {"High": 90, "Moderate": 70, "Low": 50, "Very low": 30, "N/A": 40}


def _sentences(text):
    return [s.strip() for s in _SENT_SPLIT.split(text or "") if len(s.strip()) > 15]


def classify_polarity(text):
    """返回 support / against / neutral。强短语优先，弱正向词受否定词抵消。"""
    t = (text or "").lower()
    if any(w in t for w in STRONG_POS):
        return "support"
    if any(w in t for w in STRONG_NEG):
        return "against"
    if any(w in t for w in WEAK_POS):
        if any(w in t for w in NEGATORS):
            return "neutral"
        return "support"
    if any(w in t for w in NEGATORS):
        return "against"
    return "neutral"


def extract_conclusion(doc):
    """抽取一篇文献的结论句（优先结论标签，否则跳过讨论/局限段取末句）。"""
    text = (doc.get("abstract") or "").strip()
    sents = _sentences(text)
    if not sents:
        return (doc.get("title") or "")
    for s in reversed(sents):
        if s.lower().startswith(_CONCLUSION_PREFIX):
            return s
    for s in reversed(sents):
        if not s.lower().startswith(_SKIP_PREFIX):
            return s
    return sents[-1]


def _year_int(d):
    y = d.get("year")
    if not y:
        return 0
    m = re.match(r"(\d{4})", str(y))
    return int(m.group(1)) if m else 0


def compute_confidence(docs, conflict):
    """0-100 分：证据等级 + 结论一致性 + 文献量 + 时效。"""
    best = max((GRADE_BASE.get(d.get("grade", "N/A"), 40) for d in docs), default=40)
    score = float(best)
    score += -15 if conflict else 10
    n = len(docs)
    if n >= 6:
        score += 8
    elif n >= 3:
        score += 5
    cur = date.today().year
    if any(_year_int(d) and _year_int(d) >= cur - 5 for d in docs):
        score += 5
    return max(0, min(100, int(round(score))))


def analyze_evidence(docs):
    """对 top docs 做结论极性、冲突检测、置信度评分。"""
    items = []
    for d in docs:
        concl = extract_conclusion(d)
        items.append({
            "pmid": d.get("pmid"),
            "title": d.get("title"),
            "polarity": classify_polarity(concl),
            "conclusion": concl,
            "grade": d.get("grade"),
            "year": d.get("year"),
        })

    support = sum(1 for it in items if it["polarity"] == "support")
    against = sum(1 for it in items if it["polarity"] == "against")
    neutral = len(items) - support - against
    conflict = support > 0 and against > 0

    if conflict:
        verdict = "证据存在分歧"
    elif support > 0 and against == 0:
        verdict = "证据倾向支持"
    elif against > 0 and support == 0:
        verdict = "证据倾向不支持"
    else:
        verdict = "证据不足或未明确"

    confidence = compute_confidence(docs, conflict)

    return {
        "verdict": verdict,
        "conflict": conflict,
        "confidence": confidence,
        "support_count": support,
        "against_count": against,
        "neutral_count": neutral,
        "conclusions": items,
    }
