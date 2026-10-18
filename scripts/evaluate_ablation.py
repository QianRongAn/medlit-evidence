"""Shared-protocol feature ablation; differences are exploratory, not causal proof."""
try:
    from .evaluation import parser, run_report
except ImportError:
    from evaluation import parser, run_report
import pandas as pd
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
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
    from lightgbm import LGBMClassifier
    return LGBMClassifier(n_estimators=200, max_depth=4, num_leaves=15,
                          learning_rate=0.05, subsample=0.8, colsample_bytree=0.8,
                          random_state=42, verbosity=-1, n_jobs=2)

def main():
    ap = parser(__doc__, ROOT/'data/features_large.csv', ROOT/'data/ablation_report_v2.md')
    args = ap.parse_args()
    df = pd.read_csv(args.features, dtype={"pmid": "string"})
    experiments = {"全部特征": (make_model(), ALL_FEATURES)}
    for name, features in FEATURE_GROUPS.items():
        experiments["去掉"+name] = (make_model(), [f for f in ALL_FEATURES if f not in features])
        experiments["仅用"+name] = (make_model(), features)
    run_report(df, experiments, args, "特征消融评估 v2")

if __name__ == "__main__":
    main()
