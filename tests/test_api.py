"""接口回归：替换外部服务，验证证据从检索到回答的完整链路。"""
import unittest
from copy import deepcopy
from unittest.mock import AsyncMock, patch

import httpx

from app import main
from app.evidence import analyze_evidence
from app.synthesizer import _build_context, extractive_answer


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
        context = _build_context(records)
        self.assertNotIn("[PMID 999]", context)
        self.assertIn("[PMID 123]", context)

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
                    llm.return_value = "Metformin reduced mortality. [PMID 123]"
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
