"""Shared, fail-closed evaluation protocol. No production model writes."""
import argparse
from datetime import date, timedelta
import hashlib
import json
from pathlib import Path
import re

import numpy as np
import pandas as pd
from sklearn.base import clone
from sklearn.metrics import (auc, average_precision_score, brier_score_loss,
                             precision_recall_curve, roc_auc_score)
from sklearn.model_selection import StratifiedKFold
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler


def validate_frame(df):
    if "pmid" not in df or df.empty:
        raise ValueError("nonempty data with PMID required")
    ids = df.pmid.astype("string")
    if ids.isna().any() or not ids.str.fullmatch(r"[1-9][0-9]*").all():
        raise ValueError("invalid PMID")
    if ids.duplicated().any():
        raise ValueError("duplicate PMID: deduplicate before evaluation")


def labels(y):
    y = np.asarray(y)
    if y.ndim != 1 or not np.isin(y, [0, 1]).all() or set(y) != {0, 1}:
        raise ValueError("both binary classes required")
    return y.astype(int)


def metrics(y, scores):
    y = labels(y)
    scores = np.asarray(scores, dtype=float)
    if scores.shape != y.shape or not np.isfinite(scores).all() or ((scores < 0) | (scores > 1)).any():
        raise ValueError("finite probabilities in [0,1] required")
    p, r, _ = precision_recall_curve(y, scores)
    return {"roc_auc": float(roc_auc_score(y, scores)),
            "ap": float(average_precision_score(y, scores)),
            "pr_trapezoid": float(auc(r, p)),
            "brier": float(brier_score_loss(y, scores)),
            "prevalence": float(y.mean())}


def check_split(y, tr, te):
    n = len(y)
    for idx in (tr, te):
        if len(idx) == 0 or len(set(idx)) != len(idx) or min(idx) < 0 or max(idx) >= n:
            raise ValueError("empty, duplicate or out-of-bounds split")
        labels(np.asarray(y)[idx])
    if set(tr) & set(te):
        raise ValueError("train/test overlap")


def cv_splits(df, folds=5):
    validate_frame(df)
    y = labels(df.label.to_numpy())
    if not isinstance(folds, int) or folds < 2 or min(np.bincount(y)) < folds:
        raise ValueError("each class needs at least folds samples")
    return list(StratifiedKFold(folds, shuffle=True, random_state=42).split(df, y))


def year_split(df, cutoff_year, gap_years=0):
    """Retrospective publication cohorts ONLY; never a prospective claim."""
    validate_frame(df)
    if not isinstance(cutoff_year, int) or not 1000 <= cutoff_year <= 9998:
        raise ValueError("explicit cutoff year required")
    if not isinstance(gap_years, int) or gap_years < 0:
        raise ValueError("nonnegative integer gap required")
    years = pd.to_numeric(df.year, errors="coerce").to_numpy(dtype=float)
    if not np.isfinite(years).all() or (years != np.floor(years)).any() or ((years < 1000) | (years > 9999)).any():
        raise ValueError("valid integer publication years required")
    tr = np.flatnonzero(years <= cutoff_year)
    te = np.flatnonzero(years > cutoff_year + gap_years)
    check_split(labels(df.label.to_numpy()), tr, te)
    return tr, te


def exact_date(value):
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise ValueError("exact ISO date YYYY-MM-DD required")
    return date.fromisoformat(value)


def prospective_split(df, cutoff_date, as_of, horizon_days, gap_days=0):
    """Horizon labels derived from dated events, not today's status label.

    Features must be reconstructed as of prediction_date. The schema checks
    chronology; provenance of each source snapshot must still be audited.
    """
    validate_frame(df)
    required = {"prediction_date", "features_observed_at", "event_date",
                "followup_end", "label_available_at"}
    if not required <= set(df.columns):
        raise ValueError("missing temporal metadata: " + ", ".join(sorted(required - set(df.columns))))
    if not isinstance(horizon_days, int) or horizon_days <= 0 or not isinstance(gap_days, int) or gap_days < 0:
        raise ValueError("positive horizon and nonnegative gap required")
    cutoff, end = exact_date(cutoff_date), exact_date(as_of)
    if cutoff >= end:
        raise ValueError("cutoff must precede dataset as-of date")
    y, tr, te, excluded = [], [], [], []
    for i, row in enumerate(df.to_dict("records")):
        pred = exact_date(row["prediction_date"])
        observed = exact_date(row["features_observed_at"])
        followup = exact_date(row["followup_end"])
        raw_available = row["label_available_at"]
        available = None if pd.isna(raw_available) or raw_available == "" else exact_date(raw_available)
        raw_event = row["event_date"]
        event = None if pd.isna(raw_event) or raw_event == "" else exact_date(raw_event)
        target_end = pred + timedelta(days=horizon_days)
        if observed > pred or followup < pred or followup > end or (available is not None and available > end):
            raise ValueError("feature/followup/availability chronology violation")
        if event is not None and (event <= pred or event > followup):
            raise ValueError("already affected at prediction or event outside followup")
        outcome = int(event is not None and event <= target_end)
        # Full fixed observation window for both classes; immature rows cannot
        # become negatives, and later-known positives cannot enter training.
        mature = target_end <= end and followup >= target_end
        if (available is not None and available < target_end) or (mature and available is None):
            raise ValueError("horizon label cannot be available before horizon ends")
        y.append(outcome)
        if mature and pred <= cutoff and available <= cutoff and target_end <= cutoff:
            tr.append(i)
        elif mature and pred > cutoff + timedelta(days=gap_days):
            te.append(i)
        else:
            excluded.append(i)
    y = labels(y)
    tr, te = np.asarray(tr, dtype=int), np.asarray(te, dtype=int)
    check_split(y, tr, te)
    return y, (tr, te), excluded


def evaluate(model, X, y, splits, pmids):
    y = labels(y)
    X = np.asarray(X, dtype=float)
    if X.ndim != 2 or len(X) != len(y) or not np.isfinite(X).all():
        raise ValueError("aligned finite feature matrix required")
    ids = list(map(str, pmids))
    if len(ids) != len(y) or len(set(ids)) != len(ids):
        raise ValueError("aligned unique IDs required")
    results = []
    for tr, te in splits:
        check_split(y, tr, te)
        pipe = make_pipeline(StandardScaler(), clone(model))
        pipe.fit(X[tr], y[tr])
        score = pipe.predict_proba(X[te])[:, 1]
        baseline = metrics(y[te], np.full(len(te), y[tr].mean()))
        measured = metrics(y[te], score)
        digest = lambda idx: hashlib.sha256("\n".join(ids[i] for i in idx).encode()).hexdigest()
        results.append({"train_n": len(tr), "test_n": len(te),
                        "train_prevalence": float(y[tr].mean()),
                        "train_ids_sha256": digest(tr), "test_ids_sha256": digest(te),
                        "model": measured, "constant_train_prevalence": baseline,
                        "delta_ap": measured["ap"] - baseline["ap"],
                        "delta_brier": measured["brier"] - baseline["brier"]})
    if not results:
        raise ValueError("at least one split required")
    return results


def parser(description, default_features, default_report):
    ap = argparse.ArgumentParser(description=description)
    ap.add_argument("--features", default=str(default_features))
    ap.add_argument("--report", default=str(default_report))
    ap.add_argument("--protocol", choices=["publication-cohort", "dated-horizon"], default="publication-cohort")
    ap.add_argument("--cutoff-year", type=int)
    ap.add_argument("--gap-years", type=int, default=0)
    ap.add_argument("--cutoff-date")
    ap.add_argument("--as-of")
    ap.add_argument("--horizon-days", type=int)
    ap.add_argument("--gap-days", type=int, default=0)
    return ap


def run_report(df, experiments, args, title):
    validate_frame(df)
    configuration = vars(args).copy()
    for key in ("features", "report", "signals", "models_dir"):
        if configuration.get(key):
            path = Path(configuration[key]).resolve()
            try:
                configuration[key] = path.relative_to(Path(__file__).resolve().parents[1]).as_posix()
            except ValueError:
                configuration[key] = str(path)
    if args.protocol == "dated-horizon":
        y, temporal, excluded = prospective_split(df, args.cutoff_date, args.as_of, args.horizon_days, args.gap_days)
        # Random CV is deliberately omitted for the dated protocol.
        protocols = {"dated-horizon": [temporal]}
        note = "固定观察窗历史模拟：须另审快照来源；不等于真实前瞻部署验证。"
    else:
        y = labels(df.label.to_numpy())
        temporal = year_split(df, args.cutoff_year, args.gap_years)
        excluded = sorted(set(range(len(df))) - set(temporal[0]) - set(temporal[1]))
        protocols = {"stratified_cv": cv_splits(df), "publication_cohort": [temporal]}
        note = "仅回顾性发表年份分组；缺少时点特征/事件/随访数据时，未来撤稿预测不可评估。"
    report = {"protocol_version": 2, "configuration": configuration, "note": note,
              "excluded_temporal_n": len(excluded), "seed": 42, "experiments": {}}
    lines = [f"# {title}", "", note, "",
             "AP 为主指标；PR 梯形面积仅用于核对旧结果。常量分数取训练集阳性比例，所有对比共用切分。",
             "Brier 越低越好；Δ 为模型减常量。CV 折间标准差不是置信区间。样本为病例/对照采样，指标不能解释为总体撤稿概率。",
             "", f"时间切分排除样本：{len(excluded)}。参数：`{json.dumps(configuration, ensure_ascii=False)}`", "",
             "| 实验 / 协议 | 训练/测试 N（首折） | 测试阳性率 | ROC AUC | AP | 常量 AP | ΔAP | PR 梯形面积 | 常量梯形面积 | Brier | 常量 Brier | ΔBrier |",
             "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
    for name, (model, features) in experiments.items():
        X = df[features].to_numpy(dtype=float)
        report["experiments"][name] = {"features": features, "model_params": model.get_params(), "results": {}}
        for protocol, splits in protocols.items():
            folds = evaluate(model, X, y, splits, df.pmid)
            report["experiments"][name]["results"][protocol] = folds
            def mean(key, field="model"):
                vals = [f[field][key] for f in folds]
                return f"{np.mean(vals):.4f} ± {np.std(vals):.4f}" if len(vals) > 1 else f"{vals[0]:.4f}"
            delta = lambda key: f"{np.mean([f[key] for f in folds]):+.4f}"
            lines.append(f"| {name} / {protocol} | {folds[0]['train_n']}/{folds[0]['test_n']} | " + " | ".join([
                mean("prevalence"), mean("roc_auc"), mean("ap"), mean("ap", "constant_train_prevalence"),
                delta("delta_ap"), mean("pr_trapezoid"), mean("pr_trapezoid", "constant_train_prevalence"),
                mean("brier"), mean("brier", "constant_train_prevalence"), delta("delta_brier")]) + " |")
    source = Path(args.features)
    report["features_sha256"] = hashlib.sha256(source.read_bytes()).hexdigest()
    if getattr(args, "signals", None):
        report["signals_sha256"] = hashlib.sha256(Path(args.signals).read_bytes()).hexdigest()
    import sklearn
    report["versions"] = {"numpy": np.__version__, "pandas": pd.__version__, "sklearn": sklearn.__version__}
    try:
        import lightgbm
        report["versions"]["lightgbm"] = lightgbm.__version__
    except ImportError:
        pass
    out = Path(args.report)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    out.with_suffix(".json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report
