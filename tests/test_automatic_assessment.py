"""Functional fixtures for automatic appraisal; not an expert clinical validation set."""
import unittest
from app.reported_assessment import reported_summary
from app.screening import build_query_plan


def doc(text, pmid="123", design="randomized_controlled_trial", **fields):
    return {"pmid": pmid, "title": "Study", "abstract": text, "study_type": design,
            "source": "pubmed", "integrity": "ok", **fields}


def evaluate(docs, query="metformin mortality"):
    summary = reported_summary(docs, build_query_plan(query))
    return summary, docs[0].get("reported_assessment", [])


class AutomaticAssessmentTests(unittest.TestCase):
    def test_explicit_five_domains_produce_a_preliminary_not_validated_grade(self):
        text = ("METHODS: All included studies had low risk of bias. There was low heterogeneity. "
                "We found no serious indirectness. We found no serious imprecision. We found no publication bias. "
                "RESULTS: Metformin reduced mortality.")
        _,reports = evaluate([doc(text)])
        self.assertEqual(reports[0]['automatic']['certainty']['status'],'preliminary')
        self.assertEqual(reports[0]['automatic']['certainty']['level'],'high')

    def test_concern_flag_cannot_be_ignored_by_automatic_certainty(self):
        _,reports = evaluate([doc("RESULTS: Metformin reduced mortality.",integrity_flags=['concern'])])
        self.assertEqual(reports[0]['automatic']['domains']['risk_of_bias']['status'],'serious')
        self.assertEqual(reports[0]['automatic']['certainty']['upper'],'中等')

    def test_no_form_or_llm_needed_for_direction_and_five_domains(self):
        summary, reports = evaluate([doc("RESULTS: Metformin reduced mortality (hazard ratio 0.8, 95% CI 0.7-0.9).")])
        self.assertEqual(summary["automatic_conclusions"][0]["direction"], "decrease")
        auto = reports[0]["automatic"]
        self.assertEqual(len(auto["domains"]), 5)
        self.assertEqual(auto["certainty"]["status"], "limited")
        self.assertIsNone(auto["certainty"]["level"])
        self.assertEqual(auto["certainty"]["upper"], "高")
        self.assertTrue(all(d["status"] == "unknown" for d in auto["domains"].values()))
        precision=auto['domains']['imprecision']
        self.assertEqual(precision['evidence'][0]['status'],'information')
        self.assertIn('置信区间',precision['reason'])

    def test_explicit_limitation_is_cited_and_reduces_upper_bound(self):
        text = "RESULTS: Metformin reduced mortality. LIMITATIONS: Residual confounding could influence our findings."
        _, reports = evaluate([doc(text)])
        auto = reports[0]["automatic"]
        signal = auto["domains"]["risk_of_bias"]["evidence"][0]
        self.assertIn(signal["quote"], text)
        self.assertEqual(signal["pmid"], "123")
        self.assertEqual(auto["certainty"]["upper"], "中等")

    def test_negated_high_bias_is_not_a_positive_downgrade(self):
        _, reports = evaluate([doc("RESULTS: Metformin reduced mortality. LIMITATIONS: We found no evidence of high risk of bias.")])
        self.assertEqual(reports[0]["automatic"]["domains"]["risk_of_bias"]["status"], "unknown")

    def test_negated_low_bias_is_not_a_pass(self):
        for sentence in ('We could not establish low risk of bias.', 'Low risk of bias was not established.'):
            _,reports=evaluate([doc('RESULTS: Metformin reduced mortality. LIMITATIONS: '+sentence)])
            self.assertEqual(reports[0]['automatic']['domains']['risk_of_bias']['status'],'unknown')

    def test_another_outcomes_limitations_do_not_transfer(self):
        _, reports = evaluate([doc("RESULTS: Metformin reduced mortality. Adverse events had wide confidence intervals.")])
        self.assertEqual(reports[0]["automatic"]["domains"]["imprecision"]["status"], "unknown")

    def test_source_grade_is_automatic_and_retains_provenance(self):
        _, reports = evaluate([doc("RESULTS: Moderate-certainty evidence showed that metformin reduced mortality.")])
        auto = reports[0]["automatic"]
        self.assertEqual(auto["certainty"]["status"], "source_reported")
        self.assertEqual(auto["certainty"]["label"], "中等")
        self.assertEqual(reports[0]["source_certainty"][0]["pmid"], "123")

    def test_most_narrative_reviews_do_not_outvote_a_trial(self):
        documents = [doc("RESULTS: Metformin reduced mortality.")]
        documents += [doc("CONCLUSION: Metformin increased mortality.",str(n),"review") for n in range(200,210)]
        summary, _ = evaluate(documents)
        self.assertEqual(summary["automatic_conclusions"][0]["direction"], "decrease")
        self.assertEqual(summary["automatic_conclusions"][0]["references"], ["123"])

    def test_conflicting_trials_remain_conflicting_not_majority_wins(self):
        documents = [doc("RESULTS: Metformin reduced mortality.",str(n)) for n in range(200,205)]
        documents += [doc("RESULTS: Metformin increased mortality.","300")]
        summary, _ = evaluate(documents)
        self.assertEqual(summary["automatic_conclusions"][0]["direction"], "mixed")

    def test_uncertain_report_is_not_an_opposite_direction(self):
        summary,_ = evaluate([doc("RESULTS: Metformin reduced mortality."),
                              doc("RESULTS: Metformin may reduce mortality.","456")])
        self.assertEqual(summary['automatic_conclusions'][0]['direction'],'decrease')
        self.assertTrue(summary['automatic_conclusions'][0]['has_uncertain_reports'])

    def test_retracted_demo_and_notices_cannot_establish_a_conclusion(self):
        for fields in ({"integrity":"retracted"},{"source":"offline"},{"is_notice":True}):
            with self.subTest(fields=fields):
                summary,reports = evaluate([doc("RESULTS: Metformin reduced mortality.",**fields)])
                self.assertFalse(reports)
                self.assertIsNone(summary["automatic_conclusions"][0]["direction"])

    def test_meta_analysis_is_not_automatically_high_certainty(self):
        _, reports = evaluate([doc("RESULTS: Metformin reduced mortality.",design="meta_analysis")])
        self.assertIsNone(reports[0]["automatic"]["initial"])
        self.assertIsNone(reports[0]["automatic"]["certainty"]["level"])

    def test_ratio_effect_is_extracted_without_an_active_voice_verb(self):
        summary,_ = evaluate([doc("RESULTS: Mortality with metformin had a hazard ratio 0.8 (95% CI 0.7-0.9).")])
        self.assertEqual(summary["automatic_conclusions"][0]["direction"], "decrease")

    def test_ratio_crossing_null_is_uncertain_and_reversed_comparison_abstains(self):
        summary,_ = evaluate([doc("RESULTS: Mortality with metformin had a hazard ratio 0.8 (95% CI 0.7-1.2).")])
        self.assertEqual(summary["automatic_conclusions"][0]["direction"], "uncertain")
        summary,_ = evaluate([doc("RESULTS: Mortality for placebo versus metformin had a hazard ratio 0.8 (95% CI 0.7-0.9).")])
        self.assertIsNone(summary["automatic_conclusions"][0]["direction"])

    def test_no_outcome_or_no_findings_does_not_fabricate_a_grade(self):
        summary,_ = evaluate([doc("METHODS: We studied metformin and mortality.")])
        self.assertIsNone(summary["automatic_conclusions"][0]["direction"])
        summary,reports = evaluate([doc("RESULTS: Metformin reduced mortality.")],"metformin")
        self.assertEqual(summary["automatic_conclusions"], [])
        self.assertEqual(reports, [])


class AutomaticAssessmentAPITests(unittest.IsolatedAsyncioTestCase):
    async def test_answer_and_search_ship_automatic_assessment_without_manual_input(self):
        from unittest.mock import patch, AsyncMock
        import httpx
        from app import main
        document=doc("METHODS: We conducted a randomized controlled trial. RESULTS: Metformin reduced mortality.")
        with patch.object(main,'_retrieve',AsyncMock(return_value=([document],True,1))), patch.object(main,'LLM_API_KEY',''):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app),base_url='http://test') as client:
                for route in ('/api/search','/api/answer'):
                    response=await client.post(route,json={'query':'metformin mortality'})
                    self.assertEqual(response.status_code,200,response.text)
                    data=response.json()
                    self.assertEqual(data['results'][0]['reported_assessment'][0]['automatic']['certainty']['status'],'limited')
                    if route == '/api/answer':
                        self.assertEqual(data['evidence']['reported_assessment']['automatic_conclusions'][0]['direction'],'decrease')

