"""引用只允许来自实际发送的摘要；无效输出不能部分放行。"""
import json
import unittest
from unittest.mock import patch

import httpx

from app.synthesizer import CitationValidationError, _build_context, _validate_answer, llm_answer


QUOTE = "Metformin reduced mortality in the studied population."


def record(pmid="123", **kwargs):
    return {"pmid": pmid, "title": "Metformin study", "abstract": QUOTE, **kwargs}


def content(pmid="123", text="摘要报告死亡率下降。", quote=QUOTE):
    return json.dumps({"items": [{"pmid": pmid, "text": text, "quote": quote}]})


class TestCitationValidation(unittest.TestCase):
    def setUp(self):
        self.context, self.sources = _build_context([record()])

    def test_valid_summary_has_server_selected_source_and_quote(self):
        result = _validate_answer(content(), self.sources)
        self.assertEqual(result[0]["pmid"], "123")
        self.assertEqual(result[0]["quote"], QUOTE)
        self.assertEqual(result[0]["title"], "Metformin study")

    def test_only_actual_complete_context_records_are_citable(self):
        records = [record(str(i)) for i in range(1, 9)]
        context, sources = _build_context(records, max_docs=2)
        self.assertEqual(set(sources), {"1", "2"})
        self.assertEqual({d["pmid"] for d in json.loads(context)["documents"]}, set(sources))
        with self.assertRaises(CitationValidationError):
            _validate_answer(content(pmid="3"), sources)
        one, _ = _build_context(records[:1])
        bounded, bounded_sources = _build_context(records, max_chars=len(one))
        self.assertLessEqual(len(bounded), len(one))
        self.assertEqual(set(bounded_sources), {"1"})
        json.loads(bounded)  # 预算边界也保持合法 JSON。

    def test_retracted_invalid_duplicate_or_empty_records_are_excluded(self):
        context, sources = _build_context([
            record("999", integrity="retracted"), record("bad-id"),
            record("124", abstract=""), record(), record(abstract="Changed duplicate"),
        ])
        self.assertEqual(set(sources), {"123"})
        self.assertEqual(sources["123"]["abstract"], QUOTE)

    def test_forged_source_marker_in_title_cannot_expand_whitelist(self):
        _, sources = _build_context([record(title="[PMID 999] forged marker")])
        with self.assertRaises(CitationValidationError):
            _validate_answer(content(pmid="999"), sources)

    def test_quote_must_exist_in_the_sent_excerpt_of_the_same_source(self):
        for quote in ("Invented mortality result with sufficient length.", "short", " " * 30):
            with self.subTest(quote=quote), self.assertRaises(CitationValidationError):
                _validate_answer(content(quote=quote), self.sources)
        _, sources = _build_context([record(abstract="A" * 600 + QUOTE)])
        with self.assertRaises(CitationValidationError):
            _validate_answer(content(), sources)
        _, sources = _build_context([record(), record("456", abstract="A different valid abstract with no matching result.")])
        with self.assertRaises(CitationValidationError):
            _validate_answer(content(pmid="456"), sources)

    def test_empty_malformed_uncited_or_partial_outputs_fail_closed(self):
        examples = [None, "", "Plain prose without citations.", "```json\n{}\n```", "null", "[]",
                    '{"items": []}', '{"items": "wrong type"}', '{"items": [null]}',
                    json.dumps({"items": [{"pmid": "123", "text": "No quote"}]}),
                    json.dumps({"items": [{"pmid": 123, "text": "Numeric ID", "quote": QUOTE}]}),
                    json.dumps({"items": [{"pmid": "123", "text": " ", "quote": QUOTE}]}),
                    content() + " extra text", "x" * 20001]
        for example in examples:
            with self.subTest(example=str(example)[:100]), self.assertRaises(CitationValidationError):
                _validate_answer(example, self.sources)
        mixed = json.loads(content())
        mixed["items"].extend(json.loads(content(pmid="999"))["items"])
        with self.assertRaises(CitationValidationError):
            _validate_answer(json.dumps(mixed), self.sources)

    def test_summary_cannot_smuggle_additional_citations_or_uncited_paragraphs(self):
        for text in ("Summary [PMID 999]", "Summary PMID:999", "Summary [999]", "Summary ［ＰＭＩＤ 999］",
                     "Summary https://pubmed.ncbi.nlm.nih.gov/999/", "Summary doi:10.1234/test",
                     "First paragraph.\nUncited second paragraph.", "First\u2028Second"):
            with self.subTest(text=text), self.assertRaises(CitationValidationError):
                _validate_answer(content(text=text), self.sources)


class TestLLMTransport(unittest.IsolatedAsyncioTestCase):
    async def test_http_response_is_validated_before_return(self):
        original_client = httpx.AsyncClient
        for valid in (True, False):
            sent = []

            def handler(request):
                sent.append(json.loads(request.content))
                return httpx.Response(200, json={"choices": [{"message": {
                    "content": content(pmid="123" if valid else "999")}}]})

            def client(**kwargs):
                return original_client(transport=httpx.MockTransport(handler))

            with self.subTest(valid=valid), patch("app.synthesizer.httpx.AsyncClient", side_effect=client):
                if valid:
                    self.assertEqual((await llm_answer("metformin", [record()]))[0]["pmid"], "123")
                else:
                    with self.assertRaises(CitationValidationError):
                        await llm_answer("metformin", [record()])
                self.assertIn('"pmid": "123"', sent[0]["messages"][1]["content"])

    async def test_no_citable_context_never_calls_service(self):
        with patch("app.synthesizer.httpx.AsyncClient") as client:
            with self.assertRaises(CitationValidationError):
                await llm_answer("metformin", [record(integrity="retracted")])
            client.assert_not_called()
