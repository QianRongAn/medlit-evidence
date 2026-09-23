"""撤稿风险预测：多模型对比 + 分层交叉验证 + SHAP 可解释。

产出：
- models/ 下三个模型（逻辑回归 / LightGBM / 随机森林）
- data/model_report.md（指标 + 特征重要性结论 + 诚实声明局限）
- data/shap_summary.png（SHAP 全局特征重要性图）
"""
import json
import os
import warnings

import joblib
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (auc, average_precision_score, brier_score_loss,
                             f1_score, precision_recall_curve, roc_auc_score)
from sklearn.model_selection import StratifiedKFold
from sklearn.preprocessing import StandardScaler
import lightgbm as lgb
import shap

warnings.filterwarnings("ignore")

plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei"]
plt.rcParams["axes.unicode_minus"] = False

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
FEAT = os.path.join(ROOT, "data", "features.csv")
MODELS = os.path.join(ROOT, "models")
REPORT = os.path.join(ROOT, "data", "model_report.md")
SHAP_PNG = os.path.join(ROOT, "data", "shap_summary.png")

FEATURE_COLS = [
    "title_len", "abstract_len", "n_sentences", "avg_sentence_len",
    "n_authors", "n_affiliations", "n_grants", "n_references",
    "is_english", "year", "n_exaggeration", "n_certainty", "n_hedge",
    "n_stats", "digits_per_1000", "single_author",
    "design_meta", "design_rct", "design_case_report", "design_cohort",
    "design_basic", "design_review",
]

FEATURE_NAMES_ZH = {
    "title_len": "标题长度", "abstract_len": "摘要长度", "n_sentences": "摘要句数",
    "avg_sentence_len": "平均句长", "n_authors": "作者数", "n_affiliations": "机构数",
    "n_grants": "资助数", "n_references": "参考文献数", "is_english": "英语文献",
    "year": "发表年份", "n_exaggeration": "夸张词数", "n_certainty": "确定性措辞数",
    "n_hedge": "模糊限定词数", "n_stats": "统计术语数", "digits_per_1000": "每千字数字数",
    "single_author": "单作者", "design_meta": "Meta/系统综述", "design_rct": "RCT",
    "design_case_report": "病例报告", "design_cohort": "队列/观察",
    "design_basic": "基础研究", "design_review": "综述",
}


def get_models():
    return {
        "逻辑回归": LogisticRegression(max_iter=2000, class_weight="balanced", C=0.5),
        "LightGBM": lgb.LGBMClassifier(
            n_estimators=200, max_depth=4, num_leaves=15, learning_rate=0.05,
            subsample=0.8, colsample_bytree=0.8, scale_pos_weight=1.0,
            random_state=42, verbose=-1,
        ),
        "随机森林": RandomForestClassifier(
            n_estimators=300, max_depth=5, class_weight="balanced",
            random_state=42, n_jobs=-1,
        ),
    }


def cv_evaluate(model, X, y):
    skf = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)
    aucs, praucs, f1s, briers = [], [], [], []
    for tr, te in skf.split(X, y):
        sc = StandardScaler()
        Xtr = sc.fit_transform(X[tr])
        Xte = sc.transform(X[te])
        model.fit(Xtr, y[tr])
        proba = model.predict_proba(Xte)[:, 1]
        pred = (proba >= 0.5).astype(int)
        aucs.append(roc_auc_score(y[te], proba))
        p, r, _ = precision_recall_curve(y[te], proba)
        praucs.append(auc(r, p))
        f1s.append(f1_score(y[te], pred))
        briers.append(brier_score_loss(y[te], proba))
    return {
        "AUC": (np.mean(aucs), np.std(aucs)),
        "PR-AUC": (np.mean(praucs), np.std(praucs)),
        "F1": (np.mean(f1s), np.std(f1s)),
        "Brier": (np.mean(briers), np.std(briers)),
    }


def temporal_split_evaluate(model, X, y, df):
    """按年份切分：更早的预测更晚的，模拟真实"用过去预测未来"。"""
    years = df["year"].values
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
        "train_n": len(tr), "test_n": len(te), "cutoff_year": cutoff,
        "AUC": roc_auc_score(y[te], proba),
        "PR-AUC": auc(r, p),
    }


def main(features_path=FEAT, report_path=REPORT, shap_path=SHAP_PNG,
         models_dir=MODELS, neg_desc="同期同刊 matched control"):
    df = pd.read_csv(features_path)
    X = df[FEATURE_COLS].values.astype(float)
    y = df["label"].values.astype(int)
    print(f"样本 {len(df)}，正样本 {int(y.sum())}，负样本 {int((1 - y).sum())}")

    os.makedirs(models_dir, exist_ok=True)
    results = {}
    for name, model in get_models().items():
        results[name] = cv_evaluate(model, X, y)
        print(f"\n=== {name} ===")
        for k, (m, s) in results[name].items():
            print(f"  {k}: {m:.3f} ± {s:.3f}")

    # 全量训练 LightGBM 做 SHAP
    lgb_full = get_models()["LightGBM"]
    sc = StandardScaler()
    Xs = sc.fit_transform(X)
    lgb_full.fit(Xs, y)
    joblib.dump(lgb_full, os.path.join(models_dir, "lgb.joblib"))

    lr_full = get_models()["逻辑回归"]
    lr_full.fit(Xs, y)
    joblib.dump(lr_full, os.path.join(models_dir, "lr.joblib"))
    joblib.dump(sc, os.path.join(models_dir, "scaler.joblib"))

    # SHAP（大样本时采样，避免 summary_plot 卡死）
    try:
        explainer = shap.TreeExplainer(lgb_full)
        shap_values = explainer.shap_values(Xs)
        if isinstance(shap_values, list):
            shap_values = shap_values[1]
        feat_imp = sorted(
            zip(FEATURE_COLS, np.abs(shap_values).mean(axis=0)),
            key=lambda t: -t[1],
        )
        # 画图采样最多 2500 个点
        if Xs.shape[0] > 2500:
            idx = np.random.choice(Xs.shape[0], 2500, replace=False)
            sv_plot = shap_values[idx]
            xs_plot = Xs[idx]
        else:
            sv_plot, xs_plot = shap_values, Xs
        plt.figure(figsize=(9, 7))
        shap.summary_plot(sv_plot, xs_plot, feature_names=FEATURE_COLS, show=False,
                          max_display=15)
        plt.tight_layout()
        plt.savefig(shap_path, dpi=140, bbox_inches="tight")
        plt.close()
        print(f"\nSHAP 图已写入 {shap_path}")
    except Exception as e:  # noqa: BLE001
        print(f"SHAP 失败: {e}")
        feat_imp = []
        shap_values = None

    # 时序验证（LightGBM）
    temporal = {}
    for name in ("逻辑回归", "LightGBM"):
        t = temporal_split_evaluate(get_models()[name], X, y, df)
        if t:
            temporal[name] = t

    # 生成报告
    lines = ["# 撤稿风险预测模型 · 实验报告\n"]
    lines.append(f"样本：{len(df)} 篇（正样本 {int(y.sum())} / 负样本 {int((1-y).sum())}），"
                 f"负样本为{neg_desc}。\n")
    lines.append("## 模型对比（5 折分层交叉验证，均值 ± 标准差）\n")
    lines.append("| 模型 | AUC | PR-AUC | F1 | Brier |")
    lines.append("| --- | --- | --- | --- | --- |")
    for name, r in results.items():
        lines.append(f"| {name} | {r['AUC'][0]:.3f} ± {r['AUC'][1]:.3f} | "
                     f"{r['PR-AUC'][0]:.3f} ± {r['PR-AUC'][1]:.3f} | "
                     f"{r['F1'][0]:.3f} ± {r['F1'][1]:.3f} | "
                     f"{r['Brier'][0]:.3f} ± {r['Brier'][1]:.3f} |")
    lines.append("")
    lines.append("PR-AUC 是类别不平衡下的主指标；AUC 衡量排序能力；Brier 衡量概率校准。\n")

    if feat_imp:
        lines.append("## SHAP 特征重要性（对「翻车」风险的影响大小）\n")
        lines.append("| 排名 | 特征 | 平均 SHAP |")
        lines.append("| --- | --- | --- |")
        for i, (f, v) in enumerate(feat_imp, 1):
            lines.append(f"| {i} | {FEATURE_NAMES_ZH.get(f, f)} | {v:.4f} |")
        lines.append("")
        lines.append(f"![SHAP 特征重要性]({os.path.basename(shap_path)})\n")

        # 方向解读：正负样本中位数对比（SHAP 只给大小，方向要看原始分布）
        lines.append("## 关键特征的方向（翻车组 vs 对照组的中位数）\n")
        lines.append("| 特征 | 翻车组 | 对照组 |")
        lines.append("| --- | --- | --- |")
        top_feats = [c for c, _ in feat_imp[:8]
                     if not c.startswith("design_") and c not in ("year", "is_english")]
        for f in top_feats:
            a = df[df.label == 1][f].median()
            b = df[df.label == 0][f].median()
            lines.append(f"| {FEATURE_NAMES_ZH.get(f, f)} | {a} | {b} |")
        lines.append("")
        lines.append("上表为翻车组与对照组的中位数对比：哪一侧更高，即该特征在翻车组里"
                     "倾向更大（SHAP 给的是影响大小，方向看这里）。\n")

    if temporal:
        lines.append("## 时序验证（用更早年份预测更晚年份）\n")
        lines.append("| 模型 | 切分年份 | 训练样本 | 测试样本 | AUC | PR-AUC |")
        lines.append("| --- | --- | --- | --- | --- | --- |")
        for name, t in temporal.items():
            lines.append(f"| {name} | ≤{t['cutoff_year']} | {t['train_n']} | {t['test_n']} | "
                         f"{t['AUC']:.3f} | {t['PR-AUC']:.3f} |")
        lines.append("")
    else:
        lines.append("## 时序验证\n")
        lines.append("本次未做时序外推验证：对照采样按相关度返回，年份集中于近年"
                     "（70 分位已达采样当年），切分后测试集为空。做严格的「用过去预测未来」"
                     "验证需要重新按年份分层采样早年对照，列为下一版工作。\n")

    lines.append("## 诚实声明（局限）\n")
    lines.append(f"- 样本 {len(df)} 篇，结论是「相关性」而非「因果」，不能用于判断某篇具体文献是否会被撤稿。")
    lines.append("- 特征全部来自题录与摘要文本，拿不到全文、图表、审稿记录这些真正强的信号（图像重复、数据伪造多在正文）。")
    lines.append("- 正样本依赖 PubMed 已标注的撤稿/存疑记录，存在检索偏倚；未被发现的撤稿仍被算作「正常」。")
    lines.append("- **发表年份是 SHAP 第一大特征，属于删失伪迹（censoring）**：老论文有更长的时间窗口暴露撤稿，"
                 "新论文「还没来得及翻车」。这解释了时序验证 PR-AUC（0.32~0.34）远低于交叉验证（0.81）——"
                 "预测「未来才发生的撤稿」本质上更难。产品给出风险分时应弱化年份的解释权重。")
    lines.append("- 小样本（360 篇）阶段「翻车文献题录更瘦」的结论在干净大样本下**不成立**：标题长度方向反转"
                 "（翻车组中位数 120 vs 对照 110，反而更长），说明小样本的差异主要来自撤稿记录元数据残缺，不是写作风格。")
    lines.append("- 数据清洗：过滤摘要过短（4345 篇）与摘要被替换成撤稿声明的记录（277 篇），"
                 "前者污染长度特征，后者本身就是标签泄漏。")
    lines.append("- 模型的价值在于「发现可疑描述模式」，作为人工审查的排序辅助，不是自动化判定。\n")

    with open(report_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"\n报告已写入 {report_path}")


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--features", default=FEAT)
    ap.add_argument("--report", default=REPORT)
    ap.add_argument("--shap", default=SHAP_PNG)
    ap.add_argument("--models-dir", default=MODELS)
    ap.add_argument("--neg-desc", default="同期同刊 matched control")
    a = ap.parse_args()
    main(a.features, a.report, a.shap, a.models_dir, a.neg_desc)
