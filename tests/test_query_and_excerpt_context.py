"""Synthetic regression cases separate from the frozen clinical questions."""
import json
import unittest
from unittest.mock import AsyncMock, patch

import httpx

from app import main
from app.pico import extract_pico
from app.screening import build_query_plan, screen_document
from app.synthesizer import (CitationValidationError, _answer_sentences, _build_context,
                            _split_sentences, _validate_answer, extractive_answer, llm_answer)
from app.translate import translate_query


def doc(abstract, **kwargs):
    return {"pmid": "771", "title": "Randomized clinical trial", "abstract": abstract,
            "integrity": "ok", "grade": "High", **kwargs}


class QueryVocabularyTests(unittest.TestCase):
    def test_question_phrases_are_removed_as_whole_phrases(self):
        for phrase in ("有何影响", "有什么作用", "效果如何", "效果怎么样"):
            plan = build_query_plan("使用二甲双胍对糖尿病患者死亡率" + phrase)
            with self.subTest(phrase=phrase):
                self.assertEqual(plan["issues"], [])
                self.assertEqual(plan["unmapped_terms"], [])
                self.assertEqual(plan["lexical_terms"], [])

    def test_shared_drug_aliases_translate_and_parse(self):
        for zh, en in [("司美格鲁肽", "semaglutide"), ("替尔泊肽", "tirzepatide"),
                       ("非奈利酮", "finerenone"), ("杜匹鲁单抗", "dupilumab"),
                       ("仑卡奈单抗", "lecanemab"), ("达格列净", "dapagliflozin")]:
            with self.subTest(drug=zh):
                self.assertEqual(translate_query(zh), en)
                self.assertEqual(extract_pico(zh)["intervention"], [en])

    def test_comparison_role_keeps_active_drugs_distinct(self):
        pico = extract_pico("纳武利尤单抗与伊匹木单抗相比对黑色素瘤患者的疗效")
        self.assertEqual(pico["intervention"], ["nivolumab"])
        self.assertEqual(pico["comparison"], ["ipilimumab"])

    def test_longest_population_and_translation_preserve_early_stage(self):
        pico = extract_pico("早期阿尔茨海默病")
        self.assertEqual(pico["population"], ["early alzheimer's disease"])
        self.assertEqual(translate_query("早期阿尔茨海默病"), "early alzheimer's disease")

    def test_population_and_endpoint_aliases_cover_new_domains(self):
        pico = extract_pico("替尔泊肽 阻塞性睡眠呼吸暂停 呼吸暂停低通气指数")
        self.assertEqual(pico["population"], ["obstructive sleep apnea"])
        self.assertEqual(pico["outcome"], ["apnea-hypopnea index"])
        self.assertEqual(extract_pico("慢阻肺 急性加重")["population"], ["copd"])
        self.assertEqual(extract_pico("major bleeding")["outcome"], ["major hemorrhage"])

    def test_generic_weight_baseline_does_not_satisfy_weight_loss(self):
        plan = build_query_plan("semaglutide weight reduction")
        self.assertFalse(screen_document(doc("Semaglutide was dosed according to body weight."), plan)["eligible"])
        self.assertTrue(screen_document(doc("Semaglutide produced weight loss in the trial."), plan)["eligible"])

    def test_unknown_conditions_are_not_erased_with_question_fillers(self):
        for query in ("二甲双胍对支气管扩张患者有何作用", "司美格鲁肽与安慰剂相比在妊娠期有何作用"):
            with self.subTest(query=query):
                plan = build_query_plan(query)
                self.assertIn("unmapped_chinese_terms", plan["issues"])
                self.assertFalse(screen_document(doc("Metformin semaglutide placebo asthma pregnancy."), plan)["eligible"])

    def test_exclusion_and_numeric_constraints_still_abstain(self):
        for query, reason in [("司美格鲁肽用于无糖尿病患者", "negated_population_query"),
                              ("达格列净 心衰 死亡 12周", "unsupported_numeric_constraint")]:
            with self.subTest(query=query):
                self.assertIn(reason, build_query_plan(query)["issues"])


class ExcerptContextTests(unittest.TestCase):
    def test_all_background_sentences_keep_background_identity(self):
        text = ("BACKGROUND: Earlier trials were inconclusive. Whether aspirin reduces mortality was unknown. "
                "METHODS: Aspirin mortality comparisons were planned. Patients entered the trial. "
                "RESULTS: Mortality was not reduced by aspirin. No subgroup benefit was established.")
        answer = extractive_answer([doc(text)], ["aspirin", "mortality"],
                                  query_plan=build_query_plan("aspirin mortality"))
        self.assertEqual([s["sentence"] for s in answer], ["Mortality was not reduced by aspirin."])
        self.assertEqual(answer[0]["source_section"], "results")

    def test_structured_sections_work_on_multiple_lines_and_compound_labels(self):
        text = ("BACKGROUND AND AIMS: Mortality effects are unknown. Another background sentence.\n"
                "DESIGN, SETTING, AND PARTICIPANTS: A mortality comparison was planned.\n"
                "MAIN OUTCOMES AND MEASURES: Mortality was the endpoint.\n"
                "FINDINGS: Mortality did not differ between groups.\n"
                "INTERPRETATION: The mortality effect remains uncertain.")
        sentences = list(_answer_sentences(text))
        self.assertEqual([label for label, _ in sentences], ["findings", "interpretation"])

    def test_result_uncertainty_and_negation_are_preserved(self):
        text = "CONCLUSIONS: Whether mortality improves remains unknown because estimates are imprecise."
        answer = extractive_answer([doc(text)], ["mortality"])
        self.assertEqual(answer[0]["sentence"], text.removeprefix("CONCLUSIONS: "))

    def test_unstructured_research_question_is_not_an_outcome(self):
        text = "Whether aspirin reduces mortality is unknown. Aspirin did not reduce mortality in this trial."
        answer = extractive_answer([doc(text)], ["aspirin", "mortality"])
        self.assertEqual([s["sentence"] for s in answer], ["Aspirin did not reduce mortality in this trial."])

    def test_methods_only_abstract_does_not_create_answer_or_llm_context(self):
        text = "METHODS: Mortality will be assessed in a planned randomized comparison."
        self.assertEqual(extractive_answer([doc(text)], ["mortality"]), [])
        self.assertEqual(_build_context([doc(text)])[1], {})

    def test_abbreviations_and_decimals_do_not_cut_comparisons(self):
        comparison = "Bleeding affected 7.2% vs. 5.1% of participants (HR 1.41; 95% CI 1.02 to 1.95)."
        text = comparison + " No mortality difference was demonstrated."
        self.assertEqual(_split_sentences(text), [comparison, "No mortality difference was demonstrated."])

    def test_other_abbreviations_remain_intact(self):
        for sentence in ("Smith et al. reported no change in mortality.",
                         "Adverse events, e.g. bleeding, were counted in both groups.",
                         "Dr. Chan reviewed all fatal adverse events."):
            with self.subTest(sentence=sentence):
                self.assertEqual(_split_sentences(sentence), [sentence])

    def test_question_and_exclamation_sentence_boundaries_remain(self):
        self.assertEqual(len(_split_sentences("Was mortality reduced? No benefit was established! Follow-up remains ongoing.")), 3)

    def test_context_reaches_complete_results_after_long_background(self):
        result = "Aspirin did not reduce mortality compared with placebo."
        source = doc("BACKGROUND: " + "Earlier literature was inconclusive. "*40 + "RESULTS: " + result)
        _, sources = _build_context([source])
        self.assertIn(result, sources["771"]["abstract"])
        self.assertNotIn("inconclusive", sources["771"]["abstract"])

    def test_context_budget_never_sends_partial_sentence(self):
        giant = "The primary comparison " + "was examined "*60 + "and showed no benefit."
        short = "No serious adverse events were attributed to study treatment."
        _, sources = _build_context([doc("RESULTS: " + giant + " " + short)])
        self.assertNotIn("primary comparison", sources["771"]["abstract"])
        self.assertIn(short, sources["771"]["abstract"])
        self.assertLessEqual(len(sources["771"]["abstract"]), 600)

    def test_llm_quote_cannot_use_a_partial_numeric_comparison(self):
        sentence = "Bleeding affected 7.2% vs. 5.1% of participants (HR 1.41)."
        sources = {"771": {"title": "Trial", "abstract": "RESULTS: " + sentence}}
        def content(quote):
            return json.dumps({"items": [{"pmid": "771", "text": "Source result.", "quote": quote}]})
        self.assertEqual(_validate_answer(content(sentence), sources)[0]["quote"], sentence)
        with self.assertRaisesRegex(CitationValidationError, "complete_result_sentence"):
            _validate_answer(content("Bleeding affected 7.2% vs."), sources)

    def test_llm_background_quote_is_rejected_even_if_it_is_verbatim(self):
        quote = "Whether aspirin changes mortality was unknown."
        source = {"771": {"title": "Trial", "abstract": "BACKGROUND: " + quote + " RESULTS: Mortality was unchanged."}}
        output = json.dumps({"items": [{"pmid": "771", "text": "Source summary.", "quote": quote}]})
        with self.assertRaises(CitationValidationError):
            _validate_answer(output, source)


class QueryContextIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_chinese_natural_question_reaches_real_search_and_answer(self):
        source = doc("METHODS: Semaglutide was assigned in a trial of obesity. "
                     "RESULTS: Semaglutide produced weight loss compared with placebo.")
        with patch.object(main, "_retrieve", AsyncMock(return_value=([source], True, 1))), \
             patch.object(main, "predict_risk", return_value=None), patch.object(main, "LLM_API_KEY", ""):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url="http://test") as client:
                q = {"query": "司美格鲁肽与安慰剂相比对肥胖患者减重有何作用"}
                search = (await client.post("/api/search", json=q)).json()
                answer = (await client.post("/api/answer", json=q)).json()
        self.assertEqual(search["screening"]["issues"], [])
        self.assertEqual([d["pmid"] for d in search["results"]], ["771"])
        self.assertTrue(answer["sentences"])
        self.assertTrue(all(s["source_section"] == "results" for s in answer["sentences"]))

    async def test_actual_llm_transport_receives_result_not_stale_background(self):
        result = "Mortality did not differ between aspirin and placebo."
        source = doc("BACKGROUND: Whether aspirin reduces mortality was unknown. "
                     "METHODS: Patients received aspirin. RESULTS: " + result)
        requests = []
        original_client = httpx.AsyncClient
        def handler(request):
            requests.append(json.loads(request.content))
            output = {"items": [{"pmid": "771", "text": "两组死亡率未见差异。", "quote": result}]}
            return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(output)}}]})
        def client(**kwargs):
            return original_client(transport=httpx.MockTransport(handler))
        with patch("app.synthesizer.httpx.AsyncClient", side_effect=client):
            answer = await llm_answer("aspirin placebo mortality", [source])
        self.assertEqual(answer[0]["quote"], result)
        self.assertNotIn("was unknown", requests[0]["messages"][1]["content"])
