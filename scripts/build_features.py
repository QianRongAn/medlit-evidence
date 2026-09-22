"""撤稿风险预测的特征工程（防标签泄漏）。

原则：只用"发表时点可得"的信号预测"未来是否翻车"。
- 文本风格：标题/摘要的长度、句长、夸张词、确定性措辞、模糊限定词、统计术语密度
- 文献计量：作者数、机构数、资助数、参考文献数、语言、发表年份
- 研究设计：从标题+摘要文本重新推断（review / RCT / 病例报告 / 队列 / 基础研究）

严禁：把 pubtypes 里的 "Retracted Publication" / "Expression of Concern" 当特征，
那是标签本身，用了就是泄漏，模型会学到"标题写着撤稿=撤稿"这种废话。
"""
import json
import os
import re

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
RAW = os.path.join(ROOT, "data", "corpus_raw.jsonl")
OUT = os.path.join(ROOT, "data", "features.csv")

# 语言风格词表
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

# 研究设计关键词（从标题摘要文本推断）
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


def design_flags(text):
    t = (text or "").lower()
    out = {}
    for name, keys in DESIGN_RULES:
        out[f"design_{name}"] = 1 if any(k in t for k in keys) else 0
    return out


def count_words(text, words):
    t = (text or "").lower()
    return sum(t.count(w) for w in words)


def build():
    rows = [json.loads(l) for l in open(RAW, encoding="utf-8")]
    records = []
    for r in rows:
        title = r.get("title") or ""
        abstract = r.get("abstract") or ""
        text = f"{title}\n{abstract}"
        n_sent = len(re.findall(r"[.!?]", abstract))
        year = r.get("year") or "0"
        year = int(year) if str(year).isdigit() else 0

        rec = {
            "pmid": r.get("pmid"),
            "label": r.get("label"),
            "label_name": r.get("label_name"),
            "title_len": len(title),
            "abstract_len": len(abstract),
            "n_sentences": n_sent,
            "avg_sentence_len": round(len(abstract) / max(n_sent, 1), 1),
            "n_authors": r.get("n_authors") or 0,
            "n_affiliations": r.get("n_affiliations") or 0,
            "n_grants": r.get("n_grants") or 0,
            "n_references": r.get("n_references") or 0,
            "is_english": 1 if (r.get("language") or "").lower() == "eng" else 0,
            "year": year,
            "n_exaggeration": count_words(text, EXAGGERATION),
            "n_certainty": count_words(text, CERTAINTY),
            "n_hedge": count_words(text, HEDGE),
            "n_stats": count_words(text, STAT_TERMS),
            "digit_ratio": round(
                sum(c.isdigit() for c in abstract) / max(len(abstract), 1), 4
            ),
            "single_author": 1 if (r.get("n_authors") or 0) == 1 else 0,
        }
        rec.update(design_flags(text))
        records.append(rec)

    df = pd.DataFrame(records)
    df.to_csv(OUT, index=False)
    print(f"特征表已写入 {OUT}，样本 {len(df)}，正样本 {int(df['label'].sum())}，负样本 {int((df['label'] == 0).sum())}")
    print("特征列:", [c for c in df.columns if c not in ("pmid", "label", "label_name")])


if __name__ == "__main__":
    build()
