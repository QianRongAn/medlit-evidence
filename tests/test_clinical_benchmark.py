"""Protocol/denominator tests; no clinical labels derived from application output."""
from copy import deepcopy
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch, AsyncMock

from scripts.evaluate_clinical import (ROOT, claim_id, load_benchmark, payload_hash,
    ratio, read_json, run_benchmark, score_benchmark, score_cases, write_json)

BENCHMARK = ROOT / "evaluation/clinical_v1"


def synthetic():
    q = {"id": "test-question", "language": "en", "gold_pico": {
        "population": ["population-A"], "intervention": ["drug-A"],
        "comparison": [], "outcome": ["outcome-A"]},
        "topic_relevant_pmids": ["1", "2"], "pico_matched_pmids": ["1"]}
    c = {"query_id": q["id"], "pico": deepcopy(q["gold_pico"]),
         "results": ["1", "2"], "mode": "extractive", "sentences": []}
    return q, c


class ClinicalMetricsTests(unittest.TestCase):
    def test_empty_denominator_is_unavailable(self):
        self.assertIsNone(ratio(0, 0)["rate"])

    def test_topic_relevance_does_not_imply_pico_match(self):
        q, c = synthetic()
        result = score_cases([q], [c], {})
        self.assertEqual(result["topic_precision_at_5"]["rate"], 1)
        self.assertEqual(result["pico_document_match_at_5"]["rate"], .5)
        self.assertEqual(result["closed_pool_recall_at_5"]["rate"], 1)
        self.assertEqual(result["answer_coverage"]["rate"], 0)

    def test_abstention_cannot_inflate_precision_or_answer_success(self):
        q, c = synthetic()
        c["results"] = []
        result = score_cases([q], [c], {})
        self.assertIsNone(result["topic_precision_at_5"]["rate"])
        self.assertEqual(result["answerable_query_hit_at_5"]["rate"], 0)
        self.assertEqual(result["supported_answer_coverage"]["rate"], 0)

    def test_empty_expected_fields_do_not_hide_missing_intervention(self):
        q, c = synthetic()
        c["pico"]["intervention"] = []
        result = score_cases([q], [c], {})
        self.assertEqual(result["pico_query_exact"]["rate"], 0)
        self.assertEqual(result["pico_fields"]["intervention"]["fn"], 1)

    def test_incomplete_claim_reviews_never_report_faithfulness(self):
        q, c = synthetic()
        c["sentences"] = [{"pmid": "1", "sentence": "A complete result."}]
        result = score_cases([q], [c], {})
        self.assertEqual(result["claim_review_coverage"]["rate"], 0)
        self.assertIsNone(result["summary_faithfulness"])

    def test_faithful_wrong_population_is_not_supported_answer(self):
        q, c = synthetic()
        sentence = {"pmid": "2", "sentence": "A faithfully quoted result for a different population."}
        c["sentences"] = [sentence]
        reviews = {claim_id(q["id"], sentence): {"faithful": True, "answers_question": False}}
        result = score_cases([q], [c], reviews)
        self.assertEqual(result["summary_faithfulness"]["rate"], 1)
        self.assertEqual(result["supported_answer_coverage"]["rate"], 0)

    def test_relevant_but_unfaithful_claim_is_not_supported_answer(self):
        q, c = synthetic()
        sentence = {"pmid": "1", "sentence": "A reversed treatment effect."}
        c["sentences"] = [sentence]
        review = {claim_id(q["id"], sentence): {"faithful": False, "answers_question": True}}
        self.assertEqual(score_cases([q], [c], review)["supported_answer_coverage"]["rate"], 0)

    def test_complete_frozen_labels_and_provenance(self):
        manifest, corpus, queries = load_benchmark(BENCHMARK)
        self.assertEqual(manifest["expert_review_status"], "pending")
        self.assertEqual(manifest["annotation_kind"], "model_authored_source_review")
        self.assertTrue(corpus and queries)

    def test_changed_source_hash_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)/"benchmark"
            shutil.copytree(BENCHMARK, target)
            (target/"queries.json").write_text("[]", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "frozen benchmark changed"):
                load_benchmark(target)

    def test_published_run_and_reviews_are_consistent(self):
        result = score_benchmark(BENCHMARK, BENCHMARK/"baseline_run.json", BENCHMARK/"baseline_run.review.json")
        self.assertEqual(result["summary_reviewer_kind"], "model_authored_source_review")
        self.assertIsNone(result["llm_faithfulness"])
        self.assertEqual(result["llm_success_queries"], 0)

    def test_stale_duplicate_or_unjudged_reviews_fail_closed(self):
        original = read_json(BENCHMARK/"baseline_run.review.json")
        for kind in ("stale", "duplicate", "unjudged", "changed_text"):
            review = deepcopy(original)
            if kind == "stale":
                review["run_sha256"] = "wrong"
            elif kind == "duplicate":
                review["items"][0] = review["items"][1]
            elif kind == "unjudged":
                review["items"][0]["faithful"] = None
            else:
                review["items"][0]["sentence"]["sentence"] = "changed"
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp)/"review.json"
                write_json(path, review)
                with self.assertRaises(ValueError):
                    score_benchmark(BENCHMARK, BENCHMARK/"baseline_run.json", path)

    def test_changed_or_incomplete_runs_fail_closed(self):
        original = read_json(BENCHMARK/"baseline_run.json")
        for kind in ("unhashed", "missing", "foreign_source", "duplicate_source"):
            run = deepcopy(original)
            if kind == "unhashed":
                run["retmax"] = 99
            elif kind == "missing":
                run["cases"].pop()
            elif kind == "foreign_source":
                run["cases"][0]["results"].append("99999999")
            else:
                run["cases"][0]["results"] *= 2
            if kind != "unhashed":
                run["run_sha256"] = payload_hash(run)
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp)/"run.json"
                write_json(path, run)
                with self.assertRaises(ValueError):
                    score_benchmark(BENCHMARK, path)


class ClinicalRunnerTests(unittest.IsolatedAsyncioTestCase):
    async def test_actual_asgi_pipeline_extracts_without_network_or_llm(self):
        from app import main
        original_retrieve = main._retrieve
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp)/"run.json"
            with patch.object(main, "llm_answer", AsyncMock()) as llm:
                run = await run_benchmark(BENCHMARK, output)
                llm.assert_not_called()
            self.assertTrue(all(c["mode"] == "extractive" for c in run["cases"]))
            self.assertEqual(len(run["cases"]), len(read_json(BENCHMARK/"queries.json")))
            self.assertIs(main._retrieve, original_retrieve)
            with self.assertRaises(FileExistsError):
                await run_benchmark(BENCHMARK, output)

    async def test_llm_mode_without_credentials_cannot_be_reported_as_measured(self):
        from app import main
        with tempfile.TemporaryDirectory() as tmp, patch.object(main, "LLM_API_KEY", ""):
            with self.assertRaisesRegex(ValueError, "LLM mode requires"):
                await run_benchmark(BENCHMARK, Path(tmp)/"run.json", "llm")


if __name__ == "__main__":
    unittest.main()
