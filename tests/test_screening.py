"""相关性及 PICO 筛选回归，合成摘要不代表真实临床结论。"""
import unittest

from app.screening import build_query_plan, screen_document, sentence_relevant
from app.synthesizer import extractive_answer, _validate_answer, CitationValidationError


def document(text, title="Treatment study"):
    return {"pmid": "123", "title": title, "abstract": text, "integrity": "ok", "grade": "Moderate"}


class TestScreening(unittest.TestCase):
    def test_known_population_intervention_comparison_and_outcome_are_all_required(self):
        query = "metformin versus placebo in adults with type 2 diabetes mortality"
        plan = build_query_plan(query)
        self.assertEqual(plan["issues"], [])
        good = "Adults with type 2 diabetes received metformin or placebo. Mortality was measured."
        self.assertTrue(screen_document(document(good), plan)["eligible"])
        for original, replacement, field in (("metformin", "aspirin", "intervention"),
                ("placebo", "standard care", "comparison"), ("type 2 diabetes", "type 1 diabetes", "population"),
                ("Mortality", "Hospitalization", "outcome"), ("Adults", "Children", "population")):
            with self.subTest(field=field, original=original):
                result = screen_document(document(good.replace(original, replacement)), plan)
                self.assertFalse(result["eligible"])
                self.assertIn("missing_" + field, result["reasons"])

    def test_chinese_and_english_questions_apply_same_constraints(self):
        english = build_query_plan("metformin type 2 diabetes cardiovascular risk")
        chinese = build_query_plan("二甲双胍能降低2型糖尿病患者的心血管风险吗")
        self.assertEqual(chinese["issues"], [])
        self.assertEqual(english["pico"], chinese["pico"])
        text = "Metformin was studied in type 2 diabetes. Cardiovascular events were measured."
        self.assertTrue(screen_document(document(text), chinese)["eligible"])
        self.assertFalse(screen_document(document(text.replace("Metformin", "Aspirin")), chinese)["eligible"])

    def test_outcome_diabetes_is_not_a_diabetic_population(self):
        plan = build_query_plan("他汀会增加新发糖尿病风险吗")
        self.assertEqual(plan["pico"]["population"], [])
        self.assertEqual(plan["pico"]["outcome"], ["incident diabetes"])
        self.assertTrue(screen_document(document("Statins were studied. The risk of new-onset diabetes was measured."), plan)["eligible"])
        self.assertFalse(screen_document(document("Statins reduced cardiovascular events."), plan)["eligible"])

    def test_disease_as_baseline_population_cannot_satisfy_incidence_outcome(self):
        plan = build_query_plan("他汀会增加糖尿病风险吗")
        baseline = "Statins reduced cardiovascular risk in patients with diabetes."
        self.assertFalse(screen_document(document(baseline), plan)["eligible"])
        self.assertFalse(sentence_relevant(baseline, plan))
        self.assertTrue(screen_document(document("Statins increased the risk of diabetes."), plan)["eligible"])

    def test_generic_diabetes_does_not_invent_type_two(self):
        plan = build_query_plan("metformin 糖尿病 死亡率")
        self.assertEqual(plan["pico"]["population"], ["diabetes"])
        self.assertTrue(screen_document(document("Metformin mortality was measured in type 1 diabetes."), plan)["eligible"])
        typed = build_query_plan("metformin type 2 diabetes mortality")
        self.assertFalse(screen_document(document("Metformin mortality was measured in type 1 diabetes."), typed)["eligible"])

    def test_active_comparator_requires_both_drugs_without_collapsing_drug_names(self):
        plan = build_query_plan("nivolumab versus pembrolizumab overall survival")
        self.assertEqual(plan["pico"]["intervention"], ["nivolumab"])
        self.assertEqual(plan["pico"]["comparison"], ["pembrolizumab"])
        good = "Nivolumab was compared with pembrolizumab. Overall survival was measured."
        self.assertTrue(screen_document(document(good), plan)["eligible"])
        self.assertFalse(screen_document(document(good.replace("pembrolizumab", "placebo")), plan)["eligible"])

    def test_unknown_terms_are_not_lost_when_a_known_drug_is_present(self):
        plan = build_query_plan("metformin asthma exacerbations")
        self.assertEqual(set(plan["lexical_terms"]), {"asthma"})
        self.assertEqual(plan["pico"]["outcome"], ["exacerbations"])
        self.assertFalse(screen_document(document("Metformin reduced mortality in diabetes."), plan)["eligible"])
        self.assertTrue(screen_document(document("Metformin asthma exacerbations were assessed."), plan)["eligible"])

    def test_unstructured_query_requires_coverage_not_one_common_word(self):
        plan = build_query_plan("budesonide asthma exacerbations")
        partial = screen_document(document("An asthma study with unrelated therapy."), plan)
        self.assertFalse(partial["eligible"])
        self.assertLess(partial["coverage"], 100)
        self.assertTrue(screen_document(document("Budesonide asthma exacerbations were assessed."), plan)["eligible"])
        self.assertFalse(screen_document(document("Asthma exacerbations were assessed with another therapy."), plan)["eligible"])

    def test_substrings_are_not_word_or_entity_matches(self):
        self.assertEqual(build_query_plan("nystatin")["pico"]["intervention"], [])
        self.assertFalse(screen_document(document("Nystatin treatment was studied."), build_query_plan("statin"))["eligible"])
        self.assertFalse(screen_document(document("Statin treatment was studied."), build_query_plan("nystatin"))["eligible"])
        self.assertFalse(screen_document(document("A preview was prepared."), build_query_plan("reviewer"))["eligible"])

    def test_document_excluded_population_does_not_count_as_positive_match(self):
        plan = build_query_plan("metformin type 2 diabetes mortality")
        text = "Metformin was assessed in adults without type 2 diabetes. Mortality was measured."
        self.assertFalse(screen_document(document(text), plan)["eligible"])
        comparator = build_query_plan("metformin versus placebo mortality")
        self.assertFalse(screen_document(document("Metformin was not compared with placebo. Mortality was assessed."), comparator)["eligible"])
        self.assertTrue(screen_document(document("Metformin was compared with placebo. No significant difference in mortality was found."), comparator)["eligible"])

    def test_missing_fields_do_not_relax_constraints_or_crash(self):
        plan = build_query_plan("metformin mortality")
        for doc in ({}, {"title": "Metformin mortality"}, {"abstract": None, "title": None}):
            with self.subTest(doc=doc):
                result = screen_document(doc, plan)
                self.assertFalse(result["eligible"])
                self.assertIn("missing_abstract", result["reasons"])
        self.assertTrue(screen_document({"abstract": "Metformin mortality was measured."}, plan)["eligible"])
        self.assertFalse(screen_document(document("Metformin glucose was measured.", "Metformin mortality"), plan)["eligible"])

    def test_unparsed_constraints_abstain_instead_of_being_dropped(self):
        cases = [("metformin 5 year mortality", "unsupported_numeric_constraint"),
                 ("metformin without diabetes mortality", "negated_population_query"),
                 ("metformin or aspirin mortality", "ambiguous_alternatives"),
                 ("二甲双胍治疗哮喘", "unmapped_chinese_terms"), ("the effect of treatment", "no_content_terms")]
        for query, issue in cases:
            with self.subTest(query=query):
                plan = build_query_plan(query)
                self.assertIn(issue, plan["issues"])
                self.assertFalse(screen_document(document("Metformin aspirin mortality diabetes asthma."), plan)["eligible"])

    def test_ranking_terms_are_deduplicated(self):
        tokens = build_query_plan("metformin metformin type 2 diabetes mortality")["ranking_tokens"]
        self.assertEqual(len(tokens), len(set(tokens)))

    def test_mixed_ascii_and_chinese_do_not_swallow_untranslated_condition(self):
        from app.translate import translate_query
        from app.main import _search_text
        translated = translate_query("2型糖尿病患者使用metformin降低死亡率")
        self.assertIn("diabetes", translated)
        self.assertNotIn("型", translated)
        search = _search_text("二甲双胍能降低2型糖尿病患者的死亡率吗")
        self.assertIn("type 2 diabetes", search)
        self.assertIn("mortality", search)
        self.assertEqual(search.split().count("metformin"), 1)


class TestExcerptRelevance(unittest.TestCase):
    def test_other_outcome_sentence_cannot_win_by_drug_name_density(self):
        plan = build_query_plan("metformin mortality")
        doc = document("RESULTS: Metformin metformin metformin improved glucose. CONCLUSIONS: Mortality was reduced.")
        result = extractive_answer([doc], plan["ranking_tokens"], query_plan=plan)
        self.assertTrue(result)
        self.assertTrue(all("Mortality" in s["sentence"] for s in result))

    def test_real_but_off_topic_llm_quote_is_rejected(self):
        import json
        plan = build_query_plan("metformin mortality")
        quote = "Metformin improved glucose measurements."
        source = {"123": {"title": "Metformin mortality study", "abstract": quote}}
        answer = json.dumps({"items": [{"pmid": "123", "text": "A summary.", "quote": quote}]})
        with self.assertRaises(CitationValidationError):
            _validate_answer(answer, source, plan)

    def test_sentence_matching_does_not_use_arbitrary_substrings(self):
        self.assertFalse(sentence_relevant("A nystatin study was conducted.", build_query_plan("statin")))
