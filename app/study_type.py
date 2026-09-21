"""研究设计识别与证据等级分级。

依据标题 + 摘要 + 发表类型里的关键词做规则判定，从最具体的类型开始匹配。
证据等级参考循证医学金字塔（近似）：
  High      = Meta 分析 / 系统综述 / 指南
  Moderate  = 随机对照试验
  Low       = 队列 / 病例对照
  Very low  = 病例报告
  N/A       = 综述 / 基础研究 / 其他
"""

# (label, grade, keywords) 顺序即优先级，先匹配最具体的类型
RULES = [
    ("meta_analysis", "High", [
        "meta-analysis", "meta analysis", "network meta", "meta-analyses",
        "pooled analysis of randomized", "systematic review and meta",
    ]),
    ("systematic_review", "High", [
        "systematic review", "systematic literature review",
    ]),
    ("guideline", "High", [
        "guideline", "clinical practice guideline", "consensus statement",
        "consensus recommendation",
    ]),
    ("randomized_controlled_trial", "Moderate", [
        "randomized", "randomised", "randomized controlled", "randomly assigned",
        "rct",
    ]),
    ("clinical_trial", "Moderate", [
        "clinical trial", "phase 1", "phase 2", "phase 3", "phase 4",
        "phase i", "phase ii", "phase iii", "phase iv", "open-label",
    ]),
    ("cohort", "Low", [
        "cohort", "prospective", "retrospective", "follow-up", "longitudinal",
        "observational",
    ]),
    ("case_control", "Low", ["case-control", "case control"]),
    ("case_report", "Very low", ["case report", "case series", "case study"]),
    ("review", "N/A", ["review"]),
    ("basic", "N/A", [
        "in vitro", "in vivo", "mouse model", "murine", "cell line", "preclinical",
    ]),
]

GRADE_ORDER = {"High": 0, "Moderate": 1, "Low": 2, "Very low": 3, "N/A": 4}


def classify(text, pubtypes=None):
    """返回 (study_type_label, grade)。"""
    t = (text or "").lower()
    if pubtypes:
        t = t + " " + " ".join(str(p) for p in pubtypes).lower()
    for label, grade, keys in RULES:
        for k in keys:
            if k in t:
                return label, grade
    return "other", "N/A"
