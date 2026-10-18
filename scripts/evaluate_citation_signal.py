"""Citation snapshot association study; current counts cannot establish past availability."""
try:
    from .evaluation import parser, run_report
except ImportError:
    from evaluation import parser, run_report
import pandas as pd
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]

import json
import numpy as np
try:
    from .evaluate_ablation import make_model
    from .evaluation import validate_frame
except ImportError:
    from evaluate_ablation import make_model
    from evaluation import validate_frame

CITE_FEATURES = ["cited_by_count", "oa_n_authors"]


def load_signals(path):
    signals = {}
    with open(path, encoding="utf-8") as source:
        for line in source:
            row = json.loads(line)
            pmid = str(row.get("pmid", ""))
            if not pmid.isdecimal() or int(pmid) <= 0 or pmid in signals:
                raise ValueError("invalid/duplicate signal PMID")
            signals[pmid] = row
    return signals


def align_signals(df, signals):
    validate_frame(df)
    merged = df[df.pmid.map(lambda p: signals.get(str(p), {}).get("oa_found") is True)].copy()
    for feature in CITE_FEATURES:
        merged[feature] = merged.pmid.map(lambda p: signals[str(p)].get(feature))
        values = pd.to_numeric(merged[feature], errors="coerce").to_numpy(dtype=float)
        if not np.isfinite(values).all() or (values < 0).any():
            raise ValueError("missing/invalid citation signal; do not impute unknown as zero")
        merged[feature] = values
    merged["log_cited"] = np.log1p(merged.cited_by_count)
    return merged.reset_index(drop=True)


def main():
    ap = parser(__doc__, ROOT/'data/features_large.csv', ROOT/'data/citation_signal_report_v2.md')
    ap.add_argument("--signals", default=str(ROOT/'data/integrity_signals.jsonl'))
    args = ap.parse_args()
    if args.protocol != "publication-cohort":
        ap.error("current citation snapshots have no audited as-of provenance; dated-horizon disallowed")
    df = pd.read_csv(args.features, dtype={"pmid": "string"})
    merged = align_signals(df, load_signals(args.signals))
    experiments = {"仅年份": (make_model(), ["year"]),
                   "仅引文": (make_model(), ["log_cited", "oa_n_authors"]),
                   "年份与引文": (make_model(), ["year", "log_cited", "oa_n_authors"])}
    run_report(merged, experiments, args, "引文信号回顾性关联评估 v2")

if __name__ == "__main__":
    main()
