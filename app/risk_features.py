"""撤稿风险模型的特征构建（训练与推理共用，保证两边特征完全一致）。

从 scripts/build_features.py 提取而来。词表和规则一旦改动，
必须重新训练模型，否则推理特征与训练特征错位。
"""
import re

# 与训练时完全一致的语言风格词表
EXAGGERATION = [
    "novel", "first", "unprecedented", "breakthrough", "robust", "innovative",
    "pioneering", "paradigm", "landmark", "transformative", "groundbreaking",
    "revolutionary", "cutting-edge",
]
CERTAINTY = [
    "prove", "proven", "definitively", "conclusively", "certainly", "undoubtedly",
    "clearly demonstrated", "demonstrate", "confirmed",
]
HEDGE = [
    "may", "might", "could", "suggest", "possible", "potential", "appears",
    "seems", "unclear", "perhaps", "likely",
]
STAT_TERMS = [
    "significant", "p value", "p <", "confidence interval", "odds ratio",
    "hazard ratio", "multivariate", "univariate", "adjusted", "regression",
    "statistically",
]

DESIGN_RULES = [
    ("meta", ["meta-analysis", "meta analysis", "network meta", "systematic review",
              "systematic literature review", "pooled analysis"]),
    ("rct", ["randomized", "randomised", "randomly assigned", "randomized controlled"]),
    ("case_report", ["case report", "case series", "case study", "cases of"]),
    ("cohort", ["cohort", "prospective", "retrospective", "longitudinal", "follow-up",
                "observational", "case-control", "case control"]),
    ("basic", ["in vitro", "in vivo", "mouse model", "murine", "cell line",
               "preclinical", "animal model", "rat model"]),
    ("review", ["review"]),
]

# 训练时的特征顺序，推理必须严格一致
FEATURE_COLS = [
    "title_len", "abstract_len", "n_sentences", "avg_sentence_len",
    "n_authors", "n_affiliations", "n_grants", "n_references",
    "is_english", "year", "n_exaggeration", "n_certainty", "n_hedge",
    "n_stats", "digits_per_1000", "single_author",
    "design_meta", "design_rct", "design_case_report", "design_cohort",
    "design_basic", "design_review",
]


def count_words(text, words):
    t = (text or "").lower()
    return sum(t.count(w) for w in words)


def design_flags(text):
    t = (text or "").lower()
    return {f"design_{name}": 1 if any(k in t for k in keys) else 0
            for name, keys in DESIGN_RULES}


def build_feature_row(rec):
    """从一条文献记录构建特征 dict。rec 需要：
    title / abstract / year / n_authors / n_affiliations / n_grants /
    n_references / language
    """
    title = rec.get("title") or ""
    abstract = rec.get("abstract") or ""
    text = f"{title}\n{abstract}"
    n_sent = len(re.findall(r"[.!?]", abstract))
    year = rec.get("year") or "0"
    year = int(year) if str(year).isdigit() else 0
    n_authors = rec.get("n_authors") or 0

    row = {
        "title_len": len(title),
        "abstract_len": len(abstract),
        "n_sentences": n_sent,
        "avg_sentence_len": round(len(abstract) / max(n_sent, 1), 1),
        "n_authors": n_authors,
        "n_affiliations": rec.get("n_affiliations") or 0,
        "n_grants": rec.get("n_grants") or 0,
        "n_references": rec.get("n_references") or 0,
        "is_english": 1 if (rec.get("language") or "").lower() == "eng" else 0,
        "year": year,
        "n_exaggeration": count_words(text, EXAGGERATION),
        "n_certainty": count_words(text, CERTAINTY),
        "n_hedge": count_words(text, HEDGE),
        "n_stats": count_words(text, STAT_TERMS),
        "digits_per_1000": round(
            sum(c.isdigit() for c in abstract) * 1000 / max(len(abstract), 1), 1
        ),
        "single_author": 1 if n_authors == 1 else 0,
    }
    row.update(design_flags(text))
    return row


def feature_vector(rec):
    """按训练时的特征顺序输出向量。"""
    row = build_feature_row(rec)
    return [float(row[c]) for c in FEATURE_COLS]
