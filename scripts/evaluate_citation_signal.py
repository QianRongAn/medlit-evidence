#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""引文信号 vs 年份伪迹 对照实验（量级一核心）。

问题：撤稿风险模型的「年份」是删失伪迹（老论文有时间暴露撤稿），
时序外推时 PR-AUC 掉到 0.32。引文信号（OpenAlex 的被引次数、独立撤稿标记、
作者数、期刊）是「别人留下的客观痕迹」，理论上能跨时间泛化。

本实验回答：引文信号能不能顶掉年份伪迹、提升「预测未来撤稿」的真实能力。

方法：
1. 读训练特征 features_large.csv（含 pmid + label + 22 特征）
2. 读引文信号 integrity_signals.jsonl（pmid -> cited_by_count 等）
3. 按 pmid 对齐，得到带引文信号的数据子集
4. 三组对比，都用「时序外推」（≤cutoff 年训练，>cutoff 年测试）：
   A. 只用年份
   B. 只用引文信号（不含年份）
   C. 年份 + 引文信号
   同时给 5 折交叉验证做参照。
"""
import json
import os
import warnings

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (auc, average_precision_score, precision_recall_curve,
                             roc_auc_score)
from sklearn.model_selection import StratifiedKFold
from sklearn.preprocessing import StandardScaler
import lightgbm as lgb

warnings.filterwarnings("ignore")

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
FEAT = os.path.join(ROOT, "data", "features_large.csv")
SIG = os.path.join(ROOT, "data", "integrity_signals.jsonl")
OUT = os.path.join(ROOT, "data", "citation_signal_report.md")

# 引文信号特征（OpenAlex）——注意：oa_is_retracted 是「OpenAlex 是否已标记撤稿」，
# 与训练标签 label 高度同源，属于标签泄漏（开卷考试），必须排除。
# 只保留真正独立于标签的客观信号：被引次数、作者数。
CITE_FEATURES = ["cited_by_count", "oa_n_authors"]


def load_signals(path):
    d = {}
    for l in open(path, encoding="utf-8"):
        r = json.loads(l)
        pmid = str(r.get("pmid", ""))
        if not pmid:
            continue
        d[pmid] = r
    return d


def load_features(path):
    df = pd.read_csv(path)
    df["pmid"] = df["pmid"].astype(str)
    return df


def temporal_eval(X, y, years, model):
    """时序外推：≤cutoff 训练，>cutoff 测试。返回 (auc, prauc, n_train, n_test)。"""
    cutoff = int(np.percentile(years, 70))
    tr = np.where(years <= cutoff)[0]
    te = np.where(years > cutoff)[0]
    if len(tr) < 30 or len(te) < 30:
        return None
    sc = StandardScaler()
    Xtr = sc.fit_transform(X[tr]); Xte = sc.transform(X[te])
    model.fit(Xtr, y[tr])
    proba = model.predict_proba(Xte)[:, 1]
    p, r, _ = precision_recall_curve(y[te], proba)
    return {
        "cutoff": cutoff, "n_train": len(tr), "n_test": len(te),
        "auc": roc_auc_score(y[te], proba), "prauc": auc(r, p),
    }


def cv_eval(X, y, model):
    skf = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)
    aucs, praucs = [], []
    for tr, te in skf.split(X, y):
        sc = StandardScaler()
        Xtr = sc.fit_transform(X[tr]); Xte = sc.transform(X[te])
        model.fit(Xtr, y[tr])
        proba = model.predict_proba(Xte)[:, 1]
        aucs.append(roc_auc_score(y[te], proba))
        p, r, _ = precision_recall_curve(y[te], proba)
        praucs.append(auc(r, p))
    return {"auc": float(np.mean(aucs)), "prauc": float(np.mean(praucs))}


def make_model():
    return lgb.LGBMClassifier(
        n_estimators=200, max_depth=4, num_leaves=15, learning_rate=0.05,
        subsample=0.8, colsample_bytree=0.8, random_state=42, verbose=-1,
    )


def main():
    sig = load_signals(SIG)
    df = load_features(FEAT)
    print(f"训练特征 {len(df)} 篇；引文信号命中 {len(sig)} 篇")

    # 对齐：只保留「OpenAlex 真正命中」（oa_found=true）的训练样本
    def has_true_signal(p):
        r = sig.get(p)
        return r is not None and r.get("oa_found")
    df["has_signal"] = df["pmid"].map(has_true_signal)
    merged = df[df["has_signal"]].copy()
    print(f"对齐后（OpenAlex 真命中）: {len(merged)} 篇，"
          f"正 {int(merged['label'].sum())} / 负 {int((1-merged['label']).sum())}")

    # 补充引文信号列
    for c in CITE_FEATURES:
        merged[c] = merged["pmid"].map(lambda p: sig[p].get(c, 0))
    merged["cited_by_count"] = merged["cited_by_count"].fillna(0).astype(float)
    # 引用数取对数，抑制长尾
    merged["log_cited"] = np.log1p(merged["cited_by_count"])
    merged["oa_n_authors"] = merged["oa_n_authors"].fillna(0).astype(float)

    y = merged["label"].values.astype(int)
    years = merged["year"].values.astype(float)

    # 三组特征
    X_year = merged[["year"]].values.astype(float)
    X_cite = merged[["log_cited", "oa_n_authors"]].values.astype(float)
    X_both = merged[["year", "log_cited", "oa_n_authors"]].values.astype(float)

    lines = ["# 引文信号 vs 年份伪迹 · 对照实验报告\n"]
    lines.append(f"对齐样本：{len(merged)} 篇（正 {int(y.sum())} / 负 {int((1-y).sum())}），"
                 f"均为 OpenAlex 真正命中的训练样本。\n")
    lines.append("**方法说明（关键）**：OpenAlex 的 `is_retracted`（是否已标记撤稿）字段与训练标签"
                 "高度同源，属于标签泄漏（开卷考试），本实验已排除。引文信号只保留真正独立于标签的客观信号："
                 "**被引次数**、**作者数**。\n")
    lines.append("核心检验：**时序外推**（≤70分位年份训练，>70分位测试），"
                 "这才是「预测未来撤稿」的真实能力，交叉验证会因年份伪迹虚高。\n")

    lines.append("## 时序外推（预测未来撤稿）\n")
    lines.append("| 特征组 | 切分年份 | 训练 | 测试 | AUC | PR-AUC |")
    lines.append("| --- | --- | --- | --- | --- | --- |")
    temporal_results = {}
    for name, X in [("A. 只用年份", X_year), ("B. 只用引文信号", X_cite),
                    ("C. 年份+引文信号", X_both)]:
        t = temporal_eval(X, y, years, make_model())
        if t:
            temporal_results[name] = t
            lines.append(f"| {name} | ≤{t['cutoff']} | {t['n_train']} | {t['n_test']} | "
                         f"{t['auc']:.3f} | {t['prauc']:.3f} |")
    lines.append("")

    lines.append("## 5 折交叉验证（参照，注意会因年份伪迹虚高）\n")
    lines.append("| 特征组 | AUC | PR-AUC |")
    lines.append("| --- | --- | --- |")
    for name, X in [("A. 只用年份", X_year), ("B. 只用引文信号", X_cite),
                    ("C. 年份+引文信号", X_both)]:
        r = cv_eval(X, y, make_model())
        lines.append(f"| {name} | {r['auc']:.3f} | {r['prauc']:.3f} |")
    lines.append("")

    # 引文信号的区分度（正负样本中位数对比）
    lines.append("## 引文信号在翻车组 vs 对照组的分布\n")
    lines.append("| 信号 | 翻车组中位数 | 对照组中位数 |")
    lines.append("| --- | --- | --- |")
    for c in ["cited_by_count", "oa_n_authors"]:
        a = merged[merged.label == 1][c].median()
        b = merged[merged.label == 0][c].median()
        lines.append(f"| {c} | {a} | {b} |")
    lines.append("")

    # 结论
    lines.append("## 结论\n")
    if temporal_results:
        A = temporal_results.get("A. 只用年份")
        B = temporal_results.get("B. 只用引文信号")
        C = temporal_results.get("C. 年份+引文信号")
        lines.append("- 只看**时序外推**（预测未来）这一列：")
        if A:
            lines.append(f"  - 只用年份 PR-AUC = {A['prauc']:.3f}（这是删失伪迹，虚高但不可泛化）")
        if B:
            lines.append(f"  - 只用引文信号 PR-AUC = {B['prauc']:.3f}")
        if C:
            lines.append(f"  - 年份+引文信号 PR-AUC = {C['prauc']:.3f}")
        if B and A and B["prauc"] > A["prauc"]:
            lines.append("\n**引文信号在时序外推上超过了年份伪迹**，说明它是真正能跨时间泛化的证据，"
                         "这一步证明了量级一的核心假设。")
        elif C and A and C["prauc"] > A["prauc"]:
            lines.append("\n**引文信号加入后，时序外推 PR-AUC 相比纯年份有提升**，"
                         "说明引文信号贡献了年份之外的独立信息。")
        else:
            lines.append("\n**引文信号在时序外推上未超过年份**，可能因为：对齐样本中正样本的引文信号"
                         "仍被删失污染（老文献被引次数天然更高），或命中样本量不足。需进一步分层。")
    lines.append("")

    with open(OUT, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"\n报告已写入 {OUT}")


if __name__ == "__main__":
    main()
