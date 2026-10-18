import argparse
import json
from pathlib import Path
import tempfile
import unittest
import subprocess
import sys

import numpy as np
import pandas as pd
from sklearn.dummy import DummyClassifier
from sklearn.linear_model import LogisticRegression

from scripts.evaluation import (metrics, year_split, cv_splits, evaluate,
                                prospective_split, run_report, validate_frame)
from scripts.evaluate_citation_signal import align_signals, load_signals


def cohort():
    return pd.DataFrame({"pmid": [str(i+1) for i in range(20)],
                         "year": [2020]*10 + [2022]*10,
                         "label": [0, 1]*10, "x": list(range(20))})


def dated():
    df = cohort().iloc[:6].copy()
    df["prediction_date"] = ["2018-01-01"]*2 + ["2022-01-01"]*2 + ["2024-12-01"]*2
    df["features_observed_at"] = df.prediction_date
    df["followup_end"] = "2024-12-31"
    df["label_available_at"] = ["2019-01-01"]*2 + ["2023-01-01"]*2 + ["2024-12-31"]*2
    df["event_date"] = ["", "2018-02-01", "", "2022-02-01", "", "2024-12-15"]
    return df


class EvaluationTests(unittest.TestCase):
    def test_constant_ap_is_prevalence_not_trapezoid(self):
        result = metrics([0]*8+[1]*2, [0.9]*10)
        self.assertAlmostEqual(result["ap"], .2)
        self.assertAlmostEqual(result["roc_auc"], .5)
        self.assertAlmostEqual(result["pr_trapezoid"], .6)

    def test_metrics_reject_invalid(self):
        for y, p in [([0, 0], [.1, .2]), ([0, 2], [.1, .2]),
                     ([0, 1], [np.nan, .2]), ([0, 1], [1.1, .2]), ([0, 1], [.2])]:
            with self.subTest(y=y, p=p), self.assertRaises(ValueError):
                metrics(y, p)

    def test_perfect_ranking(self):
        self.assertEqual(metrics([0, 1], [0, 1])["ap"], 1)

    def test_year_boundary_and_gap(self):
        df = cohort()
        tr, te = year_split(df, 2020, 1)
        self.assertEqual(tr.tolist(), list(range(10)))
        self.assertEqual(te.tolist(), list(range(10, 20)))
        self.assertFalse(set(tr) & set(te))

    def test_no_percentile_or_empty_fallback(self):
        for cutoff in [None, 2022, 1999]:
            with self.subTest(cutoff=cutoff), self.assertRaises(ValueError):
                year_split(cohort(), cutoff)

    def test_invalid_years(self):
        for year in [None, "unknown", 2020.5, 0, np.inf]:
            df = cohort().astype({"year": object})
            df.loc[0, "year"] = year
            with self.subTest(year=year), self.assertRaises(ValueError):
                year_split(df, 2020)

    def test_duplicate_or_missing_pmids(self):
        for pmid in ["2", "", None, "nan"]:
            df = cohort()
            df.loc[0, "pmid"] = pmid
            with self.subTest(pmid=pmid), self.assertRaises(ValueError):
                validate_frame(df)

    def test_single_class_side_rejected(self):
        df = cohort()
        df.loc[:9, "label"] = 0
        with self.assertRaises(ValueError):
            year_split(df, 2020)

    def test_cv_minority_and_determinism(self):
        df = cohort()
        a, b = cv_splits(df), cv_splits(df)
        for first, second in zip(a, b):
            np.testing.assert_array_equal(first[1], second[1])
        df.loc[:18, "label"] = 0
        with self.assertRaises(ValueError):
            cv_splits(df)

    def test_train_prevalence_baseline_not_test(self):
        y = np.array([0, 0, 0, 1, 0, 1, 1, 1])
        folds = evaluate(DummyClassifier(strategy="prior"), np.arange(8).reshape(-1, 1),
                         y, [(np.arange(4), np.arange(4, 8))], range(8))
        f = folds[0]
        self.assertEqual(f["train_prevalence"], .25)
        self.assertEqual(f["constant_train_prevalence"]["prevalence"], .75)
        self.assertAlmostEqual(f["constant_train_prevalence"]["brier"], .4375)
        self.assertEqual(f["delta_ap"], 0)
        self.assertEqual(f["delta_brier"], 0)

    def test_overlap_and_invalid_indices(self):
        for tr, te in [([0, 1], [1, 2]), ([0, 0, 1], [2, 3]), ([0, 1], [2, 9])]:
            with self.subTest(tr=tr), self.assertRaises(ValueError):
                evaluate(DummyClassifier(), np.zeros((4, 1)), [0, 1, 0, 1], [(tr, te)], range(4))

    def test_original_estimator_is_not_fitted(self):
        df = cohort()
        model = LogisticRegression()
        evaluate(model, df[["x"]], df.label, cv_splits(df), df.pmid)
        self.assertFalse(hasattr(model, "coef_"))

    def test_scaler_only_sees_training(self):
        from unittest.mock import patch
        from sklearn.preprocessing import StandardScaler
        observed = []
        original = StandardScaler.fit
        def record(scaler, X, *args, **kwargs):
            observed.append(np.asarray(X).copy())
            return original(scaler, X, *args, **kwargs)
        df = cohort()
        with patch.object(StandardScaler, "fit", record):
            evaluate(DummyClassifier(), df[["x"]], df.label, [year_split(df, 2020)], df.pmid)
        np.testing.assert_array_equal(observed[0].ravel(), np.arange(10))

    def test_missing_dates_block_prospective(self):
        with self.assertRaisesRegex(ValueError, "missing temporal metadata"):
            prospective_split(cohort(), "2020-01-01", "2024-12-31", 365)

    def test_horizon_labels_override_current_status(self):
        df = dated()
        df["label"] = 0
        # Immature rows have future label availability; mark as unknown as-of
        # instead of fabricating followup into the future.
        df.loc[4:, "prediction_date"] = "2024-01-01"
        df.loc[4:, "features_observed_at"] = "2024-01-01"
        df.loc[4:, "label_available_at"] = "2024-12-31"
        y, (tr, te), excluded = prospective_split(df, "2020-01-01", "2024-12-31", 365)
        self.assertEqual(y.tolist(), [0, 1, 0, 1, 0, 1])
        self.assertEqual(tr.tolist(), [0, 1])
        self.assertEqual(te.tolist(), [2, 3, 4, 5])
        self.assertEqual(excluded, [])

    def test_immature_followup_excluded_instead_of_negative(self):
        df = dated()
        df.loc[4:, "label_available_at"] = ""
        y, (tr, te), excluded = prospective_split(df, "2020-01-01", "2024-12-31", 365)
        self.assertEqual(excluded, [4, 5])
        self.assertEqual(te.tolist(), [2, 3])
        self.assertEqual(tr.tolist(), [0, 1])

    def test_temporal_gap_excludes_boundary(self):
        df = dated().iloc[:4].copy()
        extra = df.iloc[2:].copy()
        extra["pmid"] = ["90", "91"]
        extra["prediction_date"] = "2020-01-02"
        extra["features_observed_at"] = "2020-01-02"
        extra["event_date"] = ["", "2020-02-01"]
        df = pd.concat([df, extra], ignore_index=True)
        _, (_, te), excluded = prospective_split(df, "2020-01-01", "2024-12-31", 365, 30)
        self.assertEqual(te.tolist(), [2, 3])
        self.assertEqual(excluded, [4, 5])

    def test_unmatured_or_late_known_labels_excluded(self):
        df = dated().iloc[:4].copy()
        extra = df.iloc[:2].copy()
        extra["pmid"] = ["90", "91"]
        extra["label_available_at"] = "2021-01-01"
        df = pd.concat([df, extra], ignore_index=True)
        _, (tr, te), excluded = prospective_split(df, "2020-01-01", "2024-12-31", 365)
        self.assertEqual(tr.tolist(), [0, 1])
        self.assertEqual(te.tolist(), [2, 3])
        self.assertEqual(excluded, [4, 5])

    def test_future_features_preexisting_events_and_bad_dates_rejected(self):
        for col, value in [("features_observed_at", "2020-01-01"),
                           ("event_date", "2017-12-31"), ("event_date", "2025-01-01"),
                           ("prediction_date", "2018"), ("followup_end", "2025-01-01"),
                           ("label_available_at", "2018-01-02")]:
            df = dated().iloc[:4].copy()
            df.loc[0, col] = value
            with self.subTest(col=col, value=value), self.assertRaises(ValueError):
                prospective_split(df, "2020-01-01", "2024-12-31", 365)

    def test_signal_missing_is_not_zero(self):
        df = cohort()
        signals = {p: {"oa_found": True, "cited_by_count": 0, "oa_n_authors": 2} for p in df.pmid}
        self.assertEqual(len(align_signals(df, signals)), 20)
        signals["1"]["cited_by_count"] = None
        with self.assertRaises(ValueError):
            align_signals(df, signals)

    def test_duplicate_signal_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/"signals.jsonl"
            path.write_text('{"pmid":"1"}\n{"pmid":"1"}\n')
            with self.assertRaises(ValueError):
                load_signals(path)

    def test_report_has_paired_baselines_and_reproducible_split_hashes(self):
        with tempfile.TemporaryDirectory() as tmp:
            df = cohort()
            source, report = Path(tmp)/"data.csv", Path(tmp)/"report.md"
            df.to_csv(source, index=False)
            args = argparse.Namespace(features=str(source), report=str(report),
                protocol="publication-cohort", cutoff_year=2020, gap_years=0)
            result = run_report(df, {"dummy": (DummyClassifier(strategy="prior"), ["x"])}, args, "test")
            folds = result["experiments"]["dummy"]["results"]["stratified_cv"]
            self.assertEqual(len(folds), 5)
            self.assertTrue(all(f["delta_ap"] == 0 for f in folds))
            self.assertEqual(len(result["features_sha256"]), 64)
            self.assertIn("回顾性", report.read_text(encoding="utf-8"))
            self.assertEqual(json.loads(report.with_suffix('.json').read_text(encoding='utf-8'))['protocol_version'], 2)

    def test_citation_cli_uses_shared_metrics_and_all_feature_groups(self):
        with tempfile.TemporaryDirectory() as tmp:
            df = cohort()
            source, signals, report = [Path(tmp)/name for name in ("features.csv", "signals.jsonl", "report.md")]
            df.to_csv(source, index=False)
            signals.write_text("\n".join(json.dumps({"pmid": p, "oa_found": True,
                "cited_by_count": i, "oa_n_authors": 2}) for i, p in enumerate(df.pmid)), encoding="utf-8")
            completed = subprocess.run([sys.executable, "scripts/evaluate_citation_signal.py",
                "--features", str(source), "--signals", str(signals), "--report", str(report),
                "--cutoff-year", "2020"], cwd=Path(__file__).resolve().parents[1],
                capture_output=True, text=True, timeout=60)
            self.assertEqual(completed.returncode, 0, completed.stderr)
            result = json.loads(report.with_suffix('.json').read_text(encoding='utf-8'))
            self.assertEqual(len(result['experiments']), 3)
            hashes = []
            for experiment in result['experiments'].values():
                fold = experiment['results']['publication_cohort'][0]
                self.assertAlmostEqual(fold['constant_train_prevalence']['ap'], .5)
                hashes.append(fold['test_ids_sha256'])
            self.assertEqual(len(set(hashes)), 1)
            self.assertEqual(len(result['signals_sha256']), 64)

    def test_strict_report_omits_random_cv(self):
        with tempfile.TemporaryDirectory() as tmp:
            df = dated().iloc[:4].copy()
            source = Path(tmp)/"dated.csv"
            df.to_csv(source, index=False)
            args = argparse.Namespace(features=str(source), report=str(Path(tmp)/"report.md"),
                protocol="dated-horizon", cutoff_date="2020-01-01", as_of="2024-12-31",
                horizon_days=365, gap_days=0)
            result = run_report(df, {"dummy": (DummyClassifier(), ["x"])}, args, "dated")
            self.assertEqual(list(result['experiments']['dummy']['results']), ['dated-horizon'])


if __name__ == "__main__":
    unittest.main()
