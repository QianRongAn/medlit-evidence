"""从候选筛选到回答/LLM 的接口回归，不调用外部服务。"""
import unittest
from copy import deepcopy
from unittest.mock import AsyncMock, patch

import httpx

from app import main


def record(pmid, title, abstract, **kwargs):
    return {"pmid": pmid, "title": title, "abstract": abstract, "source": "pubmed", **kwargs}


class TestScreeningAPI(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url="http://test")
        self.risk_patch = patch.object(main, "predict_risk", return_value=None)
        self.risk_patch.start()
        self.addCleanup(self.risk_patch.stop)

    async def asyncTearDown(self):
        await self.client.aclose()

    async def test_search_and_answer_share_filters_and_do_not_mutate_candidates(self):
        records = [
            record("1", "Metformin study", "Metformin mortality was assessed in this study."),
            record("2", "Aspirin study", "Aspirin mortality was assessed in this study."),
            record("3", "Metformin glucose study", "Metformin glucose was assessed in this study."),
            record("4", "Metformin mortality", None),
            record("5", "Metformin correction", "Metformin mortality was assessed in the corrected study.",
                   pubtypes=["Published Erratum"]),
            record("6", "Metformin old study", "Metformin mortality was assessed in the old study.", integrity="retracted"),
        ]
        before = deepcopy(records)
        with patch.object(main, "_retrieve", new_callable=AsyncMock, return_value=(records, True, 100)), \
             patch.object(main, "LLM_API_KEY", ""):
            outputs = []
            for route in ("search", "answer"):
                response = await self.client.post("/api/" + route, json={"query": "metformin mortality"})
                self.assertEqual(response.status_code, 200)
                data = response.json()
                self.assertEqual({d["pmid"] for d in data["results"]}, {"1", "5", "6"})
                self.assertEqual({d["pmid"] for d in data["excluded_results"]}, {"2", "3", "4"})
                self.assertEqual(data["screening"]["candidate_count"], 6)
                self.assertEqual(data["screening"]["excluded_count"], 3)
                self.assertEqual(data["screening"]["included_count"], 3)
                self.assertEqual(data["total"], 100)  # PubMed 命中数与本地纳入数分开。
                self.assertEqual({d["pmid"] for d in data["results"] if d["answer_eligible"]}, {"1"})
                outputs.append(data)
            answer = outputs[-1]
            self.assertEqual({s["pmid"] for s in answer["sentences"]}, {"1"})
            self.assertEqual(answer["evidence"]["notice_count"], 1)
            self.assertEqual(answer["evidence"]["retracted_count"], 1)
            self.assertEqual(answer["evidence"]["unassessed_count"], 1)
        self.assertEqual(records, before)

    async def test_only_weak_matches_cannot_get_normalized_to_100_or_call_llm(self):
        records = [record("2", "Aspirin mortality", "Aspirin mortality was assessed.")]
        with patch.object(main, "_retrieve", new_callable=AsyncMock, return_value=(records, True, 1)), \
             patch.object(main, "LLM_API_KEY", "test"), \
             patch.object(main, "llm_answer", new_callable=AsyncMock) as llm:
            data = (await self.client.post("/api/answer", json={"query": "metformin mortality"})).json()
        llm.assert_not_awaited()
        self.assertEqual(data["results"], [])
        self.assertEqual(data["sentences"], [])
        self.assertEqual(data["screening"]["status"], "no_match")
        self.assertEqual(data["evidence"]["assessment_status"], "no_usable_evidence")
        self.assertLess(data["excluded_results"][0]["relevance"], 100)
        self.assertIn("missing_intervention", data["excluded_results"][0]["screening"]["reasons"])
        self.assertIn("未放宽条件", data["answer"])

    async def test_llm_receives_only_screened_and_integrity_eligible_sources(self):
        records = [record("1", "Metformin", "Metformin mortality was measured."),
                   record("2", "Aspirin", "Aspirin mortality was measured."),
                   record("3", "Metformin notice", "Metformin mortality was measured.", is_notice=True)]
        output = [{"pmid": "1", "sentence": "Summary", "quote": "Metformin mortality was measured.", "polarity": "unassessed"}]
        with patch.object(main, "_retrieve", new_callable=AsyncMock, return_value=(records, True, 3)), \
             patch.object(main, "LLM_API_KEY", "test"), \
             patch.object(main, "llm_answer", new_callable=AsyncMock, return_value=output) as llm:
            data = (await self.client.post("/api/answer", json={"query": "metformin mortality"})).json()
        self.assertEqual([d["pmid"] for d in llm.call_args.args[1]], ["1"])
        self.assertEqual(data["mode"], "llm")

    async def test_population_and_comparator_mismatches_are_explained(self):
        records = [
            record("1", "Metformin", "Adults with type 2 diabetes received metformin or placebo. Mortality was assessed."),
            record("2", "Metformin", "Adults with type 1 diabetes received metformin or placebo. Mortality was assessed."),
            record("3", "Metformin", "Adults with type 2 diabetes received metformin or standard care. Mortality was assessed."),
        ]
        query = "metformin versus placebo in adults with type 2 diabetes mortality"
        with patch.object(main, "_retrieve", new_callable=AsyncMock, return_value=(records, True, 3)), \
             patch.object(main, "LLM_API_KEY", ""):
            data = (await self.client.post("/api/answer", json={"query": query})).json()
        self.assertEqual({d["pmid"] for d in data["results"]}, {"1"})
        excluded = {d["pmid"]: d for d in data["excluded_results"]}
        self.assertIn("type 2 diabetes", excluded["2"]["screening"]["pico"]["population"]["missing"])
        self.assertIn("placebo", excluded["3"]["screening"]["pico"]["comparison"]["missing"])

    async def test_unsupported_query_abstains_with_traceable_reason(self):
        records = [record("1", "Metformin", "Metformin mortality was measured at five years.")]
        with patch.object(main, "_retrieve", new_callable=AsyncMock, return_value=(records, True, 1)), \
             patch.object(main, "LLM_API_KEY", "test"), \
             patch.object(main, "llm_answer", new_callable=AsyncMock) as llm:
            data = (await self.client.post("/api/answer", json={"query": "metformin 5 year mortality"})).json()
        llm.assert_not_awaited()
        self.assertEqual(data["screening"]["status"], "unsupported_query")
        self.assertIn("unsupported_numeric_constraint", data["screening"]["issues"])
        self.assertEqual(data["results"], [])
        self.assertIn("尚不能可靠解析", data["answer"])

    async def test_offline_screening_occurs_before_return_limit(self):
        wrong = record("2", "Metformin metformin", "Metformin metformin glucose metformin glucose.")
        right = record("1", "Clinical study", "Metformin mortality was assessed. " + "Additional details. " * 100)
        with patch.object(main, "esearch", new_callable=AsyncMock, side_effect=RuntimeError("offline")), \
             patch.object(main, "load_corpus", return_value=[wrong, right]), \
             patch.object(main, "LLM_API_KEY", ""):
            data = (await self.client.post("/api/answer", json={"query": "metformin mortality", "retmax": 1})).json()
        self.assertFalse(data["online"])
        self.assertEqual([d["pmid"] for d in data["results"]], ["1"])
        self.assertEqual(data["screening"]["candidate_count"], 2)

    async def test_unspecified_pico_fields_are_not_filled_in_or_required(self):
        records = [record("1", "Metformin", "Metformin concentrations were measured.")]
        with patch.object(main, "_retrieve", new_callable=AsyncMock, return_value=(records, True, 1)), \
             patch.object(main, "LLM_API_KEY", ""):
            data = (await self.client.post("/api/answer", json={"query": "metformin"})).json()
        self.assertEqual(data["pico"]["population"], [])
        self.assertEqual(data["pico"]["comparison"], [])
        self.assertEqual(data["pico"]["outcome"], [])
        self.assertEqual(len(data["results"]), 1)

    async def test_actual_llm_off_topic_quote_falls_back_to_requested_outcome_excerpt(self):
        import json
        original_client = httpx.AsyncClient
        off_topic = "Metformin improved glucose measurements."
        records = [record("1", "Metformin study", off_topic + " CONCLUSIONS: Mortality was reduced.")]
        def handler(request):
            content = json.dumps({"items": [{"pmid": "1", "text": "GENERATED_OFF_TOPIC", "quote": off_topic}]})
            return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})
        def client(**kwargs):
            return original_client(transport=httpx.MockTransport(handler))
        with patch.object(main, "_retrieve", new_callable=AsyncMock, return_value=(records, True, 1)), \
             patch.object(main, "LLM_API_KEY", "test"), \
             patch("app.synthesizer.httpx.AsyncClient", side_effect=client):
            data = (await self.client.post("/api/answer", json={"query": "metformin mortality"})).json()
        self.assertEqual(data["mode"], "extractive")
        self.assertEqual(data["llm_fallback_reason"], "citation_validation_failed")
        self.assertNotIn("GENERATED_OFF_TOPIC", data["answer"])
        self.assertNotIn("glucose", data["answer"])
        self.assertTrue(data["sentences"])
        self.assertTrue(all("Mortality" in s["sentence"] for s in data["sentences"]))

class TestExpandedCandidatePool(unittest.IsolatedAsyncioTestCase):
    async def test_all_matches_in_the_candidate_batch_are_returned_without_display_limit(self):
        wrong = [record(str(i), "Other intervention", "Aspirin mortality was measured.") for i in range(1,21)]
        right = [record(str(i), "Metformin", "Metformin mortality was reduced.") for i in range(21,51)]
        async def retrieve(query, limit):
            return (wrong + right)[:limit], True, 4626
        with patch.object(main, "_retrieve", new_callable=AsyncMock, side_effect=retrieve) as mocked:
            docs,excluded,online,total,plan,summary=await main._screened_retrieval("metformin mortality",20)
        self.assertEqual(mocked.call_args.args[1],100)
        self.assertEqual(len(docs),30)
        self.assertEqual(len(excluded),20)
        self.assertEqual(summary["candidate_count"],50)
        self.assertEqual(summary["matched_count"],30)
        self.assertEqual(summary["not_displayed_count"],0)
        self.assertEqual(total,4626)
        self.assertFalse(summary["search_exhausted"])
        self.assertTrue(all(doc["screening"]["eligible"] for doc in docs))

    async def test_candidate_budget_is_bounded_for_maximum_display_limit(self):
        with patch.object(main,"_retrieve",new_callable=AsyncMock,return_value=([],True,0)) as retrieve:
            result=await main._screened_retrieval("metformin",100)
        self.assertEqual(retrieve.call_args.args[1],500)
        self.assertTrue(result[-1]["search_exhausted"])

    async def test_structured_pico_affects_recall_screening_and_answer(self):
        records=[record("1","Metformin trial","Adults with asthma received metformin versus placebo. Mortality was reduced."),
                 record("2","Metformin trial","Children with asthma received metformin versus placebo. Mortality was reduced.")]
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app),base_url="http://test") as client:
            with patch.object(main,"_retrieve",new_callable=AsyncMock,return_value=(records,True,2)) as retrieve, \
                 patch.object(main,"predict_risk",return_value=None),patch.object(main,"LLM_API_KEY",""):
                response=await client.post('/api/answer',json={"query":"metformin mortality","pico":{"population":"adults、asthma","comparison":"placebo"}})
        self.assertEqual(response.status_code,200)
        data=response.json()
        self.assertEqual(data["pico"]["population"],["adults","asthma"])
        self.assertEqual(data["pico"]["comparison"],["placebo"])
        self.assertEqual([doc['pmid'] for doc in data['results']],["1"])
        self.assertIn("P: adults、asthma",retrieve.call_args.args[0])
        self.assertNotIn('p:',main._search_text(retrieve.call_args.args[0]).lower())

    async def test_structured_pico_rejects_oversized_fields_and_label_injection(self):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app),base_url="http://test") as client:
            with patch.object(main,"_retrieve",new_callable=AsyncMock) as retrieve:
                for value in ('x'*201,'adults\nC: placebo','adults; C: placebo'):
                    response=await client.post('/api/search',json={"query":"metformin","pico":{"population":value}})
                    self.assertEqual(response.status_code,422)
                retrieve.assert_not_awaited()
