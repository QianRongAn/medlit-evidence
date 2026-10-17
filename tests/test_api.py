"""接口回归：替换外部服务，验证证据从检索到回答的完整链路。"""
import unittest
import json
from copy import deepcopy
from pathlib import Path
import xml.etree.ElementTree as ET
from unittest.mock import AsyncMock, patch

import httpx

from app import main
from app.evidence import analyze_evidence
from app.synthesizer import _build_context, extractive_answer
from app.pubmed import parse_efetch_xml


def doc(pmid="1", integrity="ok", abstract=None):
    return {
        "pmid": pmid, "title": "Metformin trial", "year": "2024",
        "abstract": abstract or "CONCLUSIONS: Metformin reduced mortality.",
        "pubtypes": ["Randomized Controlled Trial"], "integrity": integrity,
        "source": "pubmed",
    }


class TestEvidenceSafety(unittest.TestCase):
    def test_no_usable_evidence_has_no_confidence(self):
        for docs in ([], [doc(integrity="retracted")]):
            with self.subTest(docs=docs):
                ev = analyze_evidence(docs)
                self.assertIsNone(ev["confidence"])
                self.assertEqual(ev["support_count"], 0)
                self.assertEqual(ev["assessment_status"], "no_usable_evidence")

    def test_synthesizers_exclude_retractions(self):
        records = [doc("999", "retracted"), doc("123")]
        sentences = extractive_answer(records, ["metformin"])
        self.assertEqual({s["pmid"] for s in sentences}, {"123"})
        context, sources = _build_context(records)
        self.assertNotIn('"pmid": "999"', context)
        self.assertIn('"pmid": "123"', context)
        self.assertEqual(set(sources), {"123"})

    def test_annotation_does_not_mutate_cached_records(self):
        records = [doc()]
        before = deepcopy(records)
        result = main._annotate_docs(records, ["metformin"])
        self.assertEqual(records, before)
        self.assertGreater(result[0]["relevance"], 0)


class TestAPI(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=main.app), base_url="http://test"
        )
        self.risk_patch = patch.object(main, "predict_risk", return_value=None)
        self.risk_patch.start()
        self.addCleanup(self.risk_patch.stop)

    async def asyncTearDown(self):
        await self.client.aclose()

    async def test_invalid_input_rejected_before_retrieval(self):
        with patch.object(main, "_retrieve", new_callable=AsyncMock) as retrieve:
            for route in ("search", "answer"):
                for payload, status in (
                    ({"query": "  "}, 400),
                    ({"query": "metformin", "retmax": 0}, 422),
                    ({"query": "metformin", "retmax": -1}, 422),
                    ({"query": "metformin", "retmax": 101}, 422),
                    ({"query": "x" * 2001}, 422),
                ):
                    with self.subTest(route=route, payload=payload):
                        response = await self.client.post("/api/" + route, json=payload)
                        self.assertEqual(response.status_code, status)
            retrieve.assert_not_awaited()

    async def test_empty_online_result_does_not_use_demo(self):
        with patch.object(main, "esearch", new_callable=AsyncMock, return_value=([], 0)), \
             patch.object(main, "load_corpus") as corpus:
            for route in ("search", "answer"):
                response = await self.client.post("/api/" + route, json={"query": "metformin"})
                data = response.json()
                self.assertEqual(response.status_code, 200)
                self.assertTrue(data["online"])
                self.assertEqual(data["results"], [])
                if route == "answer":
                    self.assertIsNone(data["evidence"]["confidence"])
                    self.assertIn("未找到", data["answer"])
            corpus.assert_not_called()

    async def test_network_failure_uses_matching_demo_only(self):
        with patch.object(main, "esearch", new_callable=AsyncMock, side_effect=RuntimeError("offline")), \
             patch.object(main, "load_corpus", return_value=[doc()]), \
             patch.object(main, "LLM_API_KEY", ""):
            found = (await self.client.post("/api/answer", json={"query": "metformin"})).json()
            self.assertFalse(found["online"])
            self.assertEqual(len(found["results"]), 1)
            missing = (await self.client.post("/api/answer", json={"query": "zzzzzz"})).json()
            self.assertEqual(missing["results"], [])
            self.assertIsNone(missing["evidence"]["confidence"])

    async def test_all_retracted_never_calls_llm(self):
        with patch.object(main, "_retrieve", new_callable=AsyncMock, return_value=([doc(integrity="retracted")], True, 1)), \
             patch.object(main, "LLM_API_KEY", "test"), \
             patch.object(main, "llm_answer", new_callable=AsyncMock) as llm:
            data = (await self.client.post("/api/answer", json={"query": "metformin"})).json()
            llm.assert_not_awaited()
            self.assertEqual(data["sentences"], [])
            self.assertIsNone(data["evidence"]["confidence"])
            self.assertEqual(data["evidence"]["retracted_count"], 1)
            self.assertEqual(len(data["results"]), 1)  # 保留文献供核查
            self.assertNotIn("reduced mortality", data["answer"])

    async def test_mixed_evidence_extractive_excludes_retracted(self):
        records = [doc("999", "retracted"), doc("123")]
        with patch.object(main, "_retrieve", new_callable=AsyncMock, return_value=(records, True, 2)), \
             patch.object(main, "LLM_API_KEY", ""):
            data = (await self.client.post("/api/answer", json={"query": "metformin"})).json()
            self.assertEqual({s["pmid"] for s in data["sentences"]}, {"123"})
            self.assertEqual(data["evidence"]["support_count"], 0)
            self.assertEqual(data["evidence"]["unassessed_count"], 1)
            self.assertEqual(data["evidence"]["retracted_count"], 1)

    async def test_llm_receives_only_usable_evidence_and_failure_falls_back(self):
        records = [doc("999", "retracted"), doc("123")]
        for fails in (False, True):
            with self.subTest(fails=fails), \
                 patch.object(main, "_retrieve", new_callable=AsyncMock, return_value=(records, True, 2)), \
                 patch.object(main, "LLM_API_KEY", "test"), \
                 patch.object(main, "llm_answer", new_callable=AsyncMock) as llm:
                if fails:
                    llm.side_effect = RuntimeError("unavailable")
                else:
                    llm.return_value = [{"sentence": "Metformin reduced mortality.", "pmid": "123",
                                         "polarity": "unassessed", "quote": "Metformin reduced mortality."}]
                data = (await self.client.post("/api/answer", json={"query": "metformin"})).json()
                self.assertEqual([d["pmid"] for d in llm.call_args.args[1]], ["123"])
                self.assertEqual(data["mode"], "extractive" if fails else "llm")
                self.assertNotIn("PMID 999", data["answer"])

    async def test_irrelevant_online_docs_do_not_form_verdict(self):
        with patch.object(main, "_retrieve", new_callable=AsyncMock, return_value=([doc()], True, 1)), \
             patch.object(main, "LLM_API_KEY", "test"), \
             patch.object(main, "llm_answer", new_callable=AsyncMock) as llm:
            data = (await self.client.post("/api/answer", json={"query": "zzzzzz"})).json()
            self.assertIsNone(data["evidence"]["confidence"])
            self.assertEqual(data["sentences"], [])
            llm.assert_not_awaited()

    async def test_question_direction_cannot_trigger_unvalidated_clinical_verdict(self):
        records = [
            {**doc("1"), "title": "Statin diabetes study",
             "abstract": "Statin therapy increased risk of incident diabetes."},
            {**doc("2"), "title": "Statin cardiovascular study",
             "abstract": "Statin therapy reduced cardiovascular risk."},
        ]
        questions = [
            "他汀会增加新发糖尿病风险吗",
            "他汀会降低心血管风险吗",
            "Do statins increase incident diabetes risk?",
        ]
        with patch.object(main, "_retrieve", new_callable=AsyncMock, return_value=(records, True, 2)), \
             patch.object(main, "LLM_API_KEY", ""):
            for query in questions:
                with self.subTest(query=query):
                    response = await self.client.post("/api/answer", json={"query": query})
                    self.assertEqual(response.status_code, 200)
                    data = response.json()
                    ev = data["evidence"]
                    self.assertEqual(ev["assessment_version"], "2")
                    self.assertEqual(ev["assessment_status"], "unassessed")
                    self.assertIsNone(ev["confidence"])
                    self.assertIsNone(ev["conflict"])
                    self.assertGreater(ev["unassessed_count"], 0)
                    self.assertIn("结局", ev["assessment_note"])
                    self.assertTrue(data["sentences"])
                    self.assertTrue(all(s["polarity"] == "unassessed" for s in data["sentences"]))

    async def test_real_llm_validator_controls_api_success_and_fallback(self):
        original_client = httpx.AsyncClient
        quote = "Metformin reduced mortality."
        base_item = {"pmid": "1", "text": "GENERATED_RESULT_ONLY", "quote": quote}
        cases = [
            (base_item, True),
            ({**base_item, "pmid": "999"}, False),  # 已撤稿、未发送
            ({**base_item, "pmid": "7"}, False),  # 检索到了，但超出上下文六篇上限
            ({**base_item, "quote": "Invented source quote with sufficient length."}, False),
            ({**base_item, "text": "GENERATED_RESULT_ONLY [PMID 999]"}, False),
            ({"pmid": "1", "text": "Missing quote"}, False),
            (None, False),
        ]
        records = [doc(str(i)) for i in range(1, 9)] + [doc("999", "retracted")]
        for item, valid in cases:
            def handler(request):
                output = json.dumps({"items": [item]}) if item else "uncited free text"
                return httpx.Response(200, json={"choices": [{"message": {"content": output}}]})

            def client(**kwargs):
                return original_client(transport=httpx.MockTransport(handler))

            with self.subTest(item=item), \
                 patch.object(main, "_retrieve", new_callable=AsyncMock, return_value=(records, True, len(records))), \
                 patch.object(main, "LLM_API_KEY", "test"), \
                 patch("app.synthesizer.httpx.AsyncClient", side_effect=client):
                response = await self.client.post("/api/answer", json={"query": "metformin"})
                self.assertEqual(response.status_code, 200)
                data = response.json()
                if valid:
                    self.assertEqual(data["mode"], "llm")
                    self.assertEqual(data["citation_validation"]["status"], "passed")
                    self.assertEqual(data["citation_validation"]["content_entailment"], "unassessed")
                    self.assertIsNone(data["llm_fallback_reason"])
                    self.assertEqual(data["answer"], "GENERATED_RESULT_ONLY [PMID 1]")
                    self.assertEqual(data["sentences"][0]["quote"], quote)
                else:
                    self.assertEqual(data["mode"], "extractive")
                    self.assertEqual(data["llm_fallback_reason"], "citation_validation_failed")
                    self.assertNotIn("GENERATED_RESULT_ONLY", data["answer"])
                    self.assertNotIn("PMID 999", data["answer"])
                    self.assertTrue(data["sentences"])

    async def test_pubmed_xml_to_api_preserves_types_roles_and_multiple_warnings(self):
        root = ET.fromstring((Path(__file__).parent / "fixtures/pubmed_integrity.xml").read_bytes())
        wanted = {"101", "102", "103", "201", "202", "203"}
        for article in list(root):
            if article.findtext("./MedlineCitation/PMID") not in wanted:
                root.remove(article)
        xml = ET.tostring(root)

        def client():
            return httpx.AsyncClient(transport=httpx.MockTransport(
                lambda request: httpx.Response(200, content=xml)))

        with patch.object(main, "esearch", new_callable=AsyncMock, return_value=(sorted(wanted), len(wanted))), \
             patch("app.pubmed._client", side_effect=client), patch("app.pubmed._CACHE", {}), \
             patch.object(main, "LLM_API_KEY", ""):
            for route in ("search", "answer"):
                response = await self.client.post("/api/" + route, json={"query": "metformin"})
                self.assertEqual(response.status_code, 200)
                data = response.json()
                docs = {d["pmid"]: d for d in data["results"]}
                self.assertEqual(set(docs), wanted)
                self.assertEqual((docs["101"]["study_type"], docs["101"]["grade"]), ("case_report", "Very low"))
                self.assertEqual((docs["102"]["study_type"], docs["102"]["grade"]), ("cohort", "Low"))
                self.assertEqual(docs["103"]["study_type"], "randomized_controlled_trial")
                self.assertEqual(docs["102"]["integrity_flags"], ["concern", "corrected"])
                self.assertEqual(docs["101"]["integrity_relations"][0]["pmid"], "201")
                for pmid in ("201", "202", "203"):
                    self.assertTrue(docs[pmid]["is_notice"])
                    self.assertEqual(docs[pmid]["study_type"], "notice")
                    self.assertEqual(docs[pmid]["grade"], "N/A")
                if route == "answer":
                    ev = data["evidence"]
                    self.assertEqual(ev["notice_count"], 3)
                    self.assertEqual(ev["retracted_count"], 1)
                    self.assertEqual(ev["concern_count"], 1)
                    self.assertEqual(ev["corrected_count"], 2)
                    self.assertEqual(ev["unassessed_count"], 2)
                    self.assertTrue(data["sentences"])
                    self.assertTrue({s["pmid"] for s in data["sentences"]} <= {"102", "103"})
                    for word in ("撤稿", "存疑", "更正", "通知"):
                        self.assertIn(word, ev["integrity_warning"])
                # 分类和请求不能修改缓存中的原始元数据。
                from app.pubmed import _CACHE
                cached_docs = next(iter(_CACHE.values()))[1]
                self.assertTrue(all("study_type" not in d for d in cached_docs))

    async def test_only_notices_never_call_llm_and_do_not_become_research_evidence(self):
        records = parse_efetch_xml((Path(__file__).parent / "fixtures/pubmed_integrity.xml").read_bytes())
        notices = [d for d in records if d["is_notice"]]
        with patch.object(main, "_retrieve", new_callable=AsyncMock, return_value=(notices, True, len(notices))), \
             patch.object(main, "LLM_API_KEY", "test"), \
             patch.object(main, "llm_answer", new_callable=AsyncMock) as llm:
            data = (await self.client.post("/api/answer", json={"query": "metformin"})).json()
            llm.assert_not_awaited()
            self.assertEqual(data["sentences"], [])
            self.assertEqual(data["evidence"]["notice_count"], 3)
            self.assertEqual(data["evidence"]["unassessed_count"], 0)
            self.assertEqual(data["evidence"]["assessment_status"], "no_usable_evidence")
            self.assertEqual(data["evidence"]["retracted_count"], 0)
            self.assertEqual(data["evidence"]["concern_count"], 0)
            self.assertEqual(data["evidence"]["corrected_count"], 0)
            self.assertEqual(len(data["results"]), 3)

    async def test_republished_new_version_does_not_inherit_old_retraction(self):
        records = parse_efetch_xml((Path(__file__).parent / "fixtures/pubmed_integrity.xml").read_bytes())
        versions = [d for d in records if d["pmid"] in {"104", "105"}]
        with patch.object(main, "_retrieve", new_callable=AsyncMock, return_value=(versions, True, 2)), \
             patch.object(main, "LLM_API_KEY", ""):
            data = (await self.client.post("/api/answer", json={"query": "metformin"})).json()
            self.assertEqual({s["pmid"] for s in data["sentences"]}, {"105"})
            self.assertEqual(data["evidence"]["retracted_count"], 1)
            self.assertEqual(data["evidence"]["corrected_count"], 1)
