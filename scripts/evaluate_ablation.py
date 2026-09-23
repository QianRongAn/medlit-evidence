"""撤稿风险模型 · 验证与消融框架（发论文的评估骨架）。

三件事：
1. 5 折分层 CV（基线）
2. 时序外推（≤2024 训练 → 2025+ 测试），诚实标注删失伪迹影响
3. 信号消融：按特征组逐个拿掉，看 PR-AUC 掉多少，证明每个信号组的贡献

用法：python scripts/evaluate_ablation.py
"""
import os
import warnings

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import auc, average_precision_score, precision_recall_curve, roc_auc_score
from sklearn.model_selection import StratifiedKFold
from sklearn.preprocessing import StandardScaler
import lightgbm as lgb

warnings.filterwarnings("ignore")

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
FEAT = os.path.join(ROOT, "data", "features_large.csv")
OUT = os.path.join(ROOT, "data", "ablation_report.md")

# 特征分组（用于消融）
FEATURE_GROUPS = {
    "文本风格": ["n_exaggeration", "n_certainty", "n_hedge", "n_stats", "digits_per_1000"],
    "题录长度": ["title_len", "abstract_len", "n_sentences", "avg_sentence_len"],
    "文献计量": ["n_authors", "n_affiliations", "n_grants", "n_references", "single_author", "is_english"],
    "研究设计": ["design_meta", "design_rct", "design_case_report", "design_cohort", "design_basic", "design_review"],
    "时间": ["year"],
}

ALL_FEATURES = [
    "title_len", "abstract_len", "n_sentences", "avg_sentence_len",
    "n_authors", "n_affiliations", "n_grants", "n_references",
    "is_english", "year", "n_exaggeration", "n_certainty", "n_hedge",
    "n_stats", "digits_per_1000", "single_author",
    "design_meta", "design_rct", "design_case_report", "design_cohort",
    "design_basic", "design_review",
]


def make_model():
    return lgb.LGBMClassifier(
        n_estimators=200, max_depth=4, num_leaves=15, learning_rate=0.05,
        subsample=0.8, colsample_bytree=0.8, random_state=42, verbose=-1,
    )


def cv_score(X, y):
    skf = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)
    aucs, praucs = [], []
    for tr, te in skf.split(X, y):
        sc = StandardScaler()
        Xtr = sc.fit_transform(X[tr]); Xte = sc.transform(X[te])
        m = make_model(); m.fit(Xtr, y[tr])
        p = m.predict_proba(Xte)[:, 1]
        aucs.append(roc_auc_score(y[te], p))
        pr, rc, _ = precision_recall_curve(y[te], p)
        praucs.append(auc(rc, pr))
    return np.mean(aucs), np.mean(praucs)


def temporal_score(X, y, df):
    years = df["year"].values
    cutoff = 2024
    tr = np.where(years <= cutoff)[0]
    te = np.where(years > cutoff)[0]
    if len(tr) < 30 or len(te) < 30:
        return None
    sc = StandardScaler()
    Xtr = sc.fit_transform(X[tr]); Xte = sc.transform(X[te])
    m = make_model(); m.fit(Xtr, y[tr])
    p = m.predict_proba(Xte)[:, 1]
    pr, rc, _ = precision_recall_curve(y[te], p)
    return {
        "train_n": len(tr), "test_n": len(te),
        "auc": roc_auc_score(y[te], p), "prauc": auc(rc, pr),
    }


def main():
    df = pd.read_csv(FEAT)
    X_all = df[ALL_FEATURES].values.astype(float)
    y = df["label"].values.astype(int)

    lines = ["# 撤稿风险模型 · 验证与消融报告\n"]
    lines.append(f"样本 {len(df)}（正 {int(y.sum())} / 负 {int((1-y).sum())}）\n")

    # ① 全特征基线
    auc, prauc = cv_score(X_all, y)
    lines.append("## ① 全特征基线（5 折 CV）\n")
    lines.append(f"- AUC {auc:.3f} / PR-AUC {prauc:.3f}\n")

    # ② 时序外推
    t = temporal_score(X_all, y, df)
    lines.append("## ② 时序外推（≤2024 训练 → 2025+ 测试）\n")
    if t:
        lines.append(f"- 训练 {t['train_n']} / 测试 {t['test_n']}，AUC {t['auc']:.3f} / PR-AUC {t['prauc']:.3f}")
        lines.append("- 注意：此数被「删失伪迹」污染，新论文尚未暴露撤稿，天然低风险，不能直接当泛化能力。\n")
    else:
        lines.append("- 无法切分（年份过于集中）。\n")

    # ③ 消融：逐个拿掉特征组
    lines.append("## ③ 信号消融（拿掉某组特征，看 PR-AUC 掉多少）\n")
    lines.append("| 拿掉的特征组 | AUC | PR-AUC | ΔPR-AUC |")
    lines.append("| --- | --- | --- | --- |")
    for group_name, feats in FEATURE_GROUPS.items():
        keep = [f for f in ALL_FEATURES if f not in feats]
        X_abl = df[keep].values.astype(float)
        a, p = cv_score(X_abl, y)
        lines.append(f"| {group_name} | {a:.3f} | {p:.3f} | {p - prauc:+.3f} |")
    lines.append("")
    lines.append("ΔPR-AUC 越负，说明该组特征越重要（拿掉后性能掉得越多）。\n")

    # ④ 单组特征（只有这一组能到多少）
    lines.append("## ④ 单组特征独立预测力\n")
    lines.append("| 只用这组特征 | AUC | PR-AUC |")
    lines.append("| --- | --- | --- |")
    for group_name, feats in FEATURE_GROUPS.items():
        a, p = cv_score(df[feats].values.astype(float), y)
        lines.append(f"| {group_name} | {a:.3f} | {p:.3f} |")
    lines.append("")
    lines.append("单组预测力越低、但拿掉后掉得越多，说明该组特征「锦上添花」（与别组互补）；反之说明「单打独斗」。\n")

    with open(OUT, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"消融报告已写入 {OUT}")


if __name__ == "__main__":
    main()
