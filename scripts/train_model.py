"""Evaluate before optional explicit model export. Default run writes reports only."""
try:
    from .evaluation import parser, run_report
except ImportError:
    from evaluation import parser, run_report
import pandas as pd
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
FEATURE_COLS = [
    "title_len", "abstract_len", "n_sentences", "avg_sentence_len",
    "n_authors", "n_affiliations", "n_grants", "n_references",
    "is_english", "year", "n_exaggeration", "n_certainty", "n_hedge",
    "n_stats", "digits_per_1000", "single_author",
    "design_meta", "design_rct", "design_case_report", "design_cohort",
    "design_basic", "design_review",
]


def get_models():
    from sklearn.linear_model import LogisticRegression
    from sklearn.ensemble import RandomForestClassifier
    try:
        from .evaluate_ablation import make_model
    except ImportError:
        from evaluate_ablation import make_model
    return {
        "逻辑回归": LogisticRegression(max_iter=2000, class_weight="balanced", C=0.5),
        "LightGBM": make_model(),
        "随机森林": RandomForestClassifier(n_estimators=300, max_depth=5,
                           class_weight="balanced", random_state=42, n_jobs=2),
    }


def main():
    ap = parser(__doc__, ROOT/'data/features.csv', ROOT/'data/model_report_v2.md')
    ap.add_argument("--models-dir", help="Explicit opt-in export directory; evaluation never updates models by default")
    args = ap.parse_args()
    df = pd.read_csv(args.features, dtype={"pmid": "string"})
    models = get_models()
    run_report(df, {name: (model, FEATURE_COLS) for name, model in models.items()}, args, "模型评估 v2")
    if args.models_dir:
        if args.protocol != "publication-cohort":
            raise ValueError("dated-horizon export requires separate deployment review")
        import joblib
        from sklearn.preprocessing import StandardScaler
        out = Path(args.models_dir)
        out.mkdir(parents=True, exist_ok=True)
        scaler = StandardScaler()
        X = scaler.fit_transform(df[FEATURE_COLS].to_numpy(dtype=float))
        for key, name in [("lgb", "LightGBM"), ("lr", "逻辑回归")]:
            models[name].fit(X, df.label.to_numpy())
            joblib.dump(models[name], out/f"{key}.joblib")
        joblib.dump(scaler, out/'scaler.joblib')

if __name__ == "__main__":
    main()
