"""撤稿/更正/存疑检测的单测（纯逻辑，不依赖网络）。"""
import unittest
from pathlib import Path

from app.pubmed import _detect_integrity, parse_efetch_xml
from app.integrity import document_integrity, integrity_details, is_usable_evidence


class TestIntegrity(unittest.TestCase):
    def test_retracted_via_pubtype(self):
        self.assertEqual(
            _detect_integrity(["Journal Article", "Retracted Publication"], []),
            "retracted",
        )

    def test_retracted_via_reftype(self):
        self.assertEqual(
            _detect_integrity(["Journal Article"], ["RetractionIn", "CommentIn"]),
            "retracted",
        )

    def test_concern(self):
        self.assertEqual(
            _detect_integrity(["Journal Article"], ["ExpressionOfConcernIn"]),
            "concern",
        )

    def test_corrected(self):
        self.assertEqual(
            _detect_integrity(["Journal Article"], ["ErratumIn"]),
            "corrected",
        )
        self.assertEqual(
            _detect_integrity(["Corrected and Republished Article"], []),
            "corrected",
        )

    def test_ok(self):
        self.assertEqual(_detect_integrity(["Randomized Controlled Trial"], []), "ok")

    def test_parse_efetch_marks_retracted(self):
        xml = """<?xml version="1.0"?>
<PubmedArticleSet>
  <PubmedArticle>
    <MedlineCitation>
      <PMID>9500320</PMID>
      <Article>
        <ArticleTitle>Fake retracted study</ArticleTitle>
        <Journal><Title>Lancet</Title></Journal>
        <PublicationTypeList><PublicationType>Journal Article</PublicationType>
        <PublicationType>Retracted Publication</PublicationType></PublicationTypeList>
      </Article>
    </MedlineCitation>
  </PubmedArticle>
</PubmedArticleSet>"""
        docs = parse_efetch_xml(xml)
        self.assertEqual(len(docs), 1)
        self.assertEqual(docs[0]["integrity"], "retracted")
        self.assertEqual(docs[0]["pmid"], "9500320")

    def test_notice_publication_types_are_not_affected_original_articles(self):
        for pt in ("Retraction of Publication", "Retraction Notice", "Expression of Concern", "Published Erratum"):
            with self.subTest(pt=pt):
                details = integrity_details([pt], [])
                self.assertEqual(details["integrity"], "notice")
                self.assertTrue(details["is_notice"])
                self.assertEqual(details["integrity_flags"], [])
                self.assertFalse(is_usable_evidence(details))

    def test_relation_directions_and_republication_versions(self):
        cases = {
            "RetractionIn": "retracted", "RetractionOf": "notice",
            "ExpressionOfConcernIn": "concern", "ExpressionOfConcernFor": "notice",
            "ErratumIn": "corrected", "ErratumFor": "notice",
            "CorrectedandRepublishedIn": "corrected", "CorrectedandRepublishedFrom": "corrected",
            "RetractedandRepublishedIn": "retracted", "RetractedandRepublishedFrom": "corrected",
        }
        for relation, expected in cases.items():
            with self.subTest(relation=relation):
                result = integrity_details(["Journal Article"], [relation])
                self.assertEqual(result["integrity"], expected)
                self.assertEqual(result["is_notice"], expected == "notice")

    def test_multiple_flags_survive_priority_and_normalization(self):
        details = integrity_details([" Journal Article "], [
            " ErratumIn ", "EXPRESSIONOFCONCERNIN", "retractionin", "ErratumIn"])
        self.assertEqual(details["integrity"], "retracted")
        self.assertEqual(details["integrity_flags"], ["retracted", "concern", "corrected"])
        # 通知本身若又被撤稿，既保留身份也保留其自身状态。
        notice = integrity_details(["Retraction Notice", "Retracted Publication"], ["RetractionOf"])
        self.assertTrue(notice["is_notice"])
        self.assertEqual(notice["integrity"], "retracted")
        self.assertFalse(is_usable_evidence(notice))

    def test_comments_updates_and_plain_reprints_do_not_imply_integrity_issues(self):
        for ref in ("CommentIn", "CommentOn", "UpdateIn", "UpdateOf", "RepublishedIn", "RepublishedFrom",
                    "ReprintIn", "ReprintOf", "UnknownFutureType"):
            with self.subTest(ref=ref):
                self.assertEqual(_detect_integrity(["Journal Article"], [ref]), "ok")

    def test_standard_xml_fixture_preserves_roles_links_and_all_flags(self):
        records = parse_efetch_xml((Path(__file__).parent / "fixtures/pubmed_integrity.xml").read_bytes())
        docs = {d["pmid"]: d for d in records}
        expected = {"101": "retracted", "102": "concern", "103": "corrected", "104": "retracted",
                    "105": "corrected", "106": "corrected", "107": "corrected",
                    "201": "notice", "202": "notice", "203": "notice"}
        self.assertEqual({p: d["integrity"] for p, d in docs.items()}, expected)
        self.assertEqual(docs["102"]["integrity_flags"], ["concern", "corrected"])
        self.assertEqual(docs["101"]["integrity_relations"][0]["pmid"], "201")
        self.assertEqual(docs["201"]["integrity_relations"][0]["pmid"], "101")
        self.assertFalse(docs["105"]["is_notice"])
        self.assertTrue(is_usable_evidence(docs["105"]))

    def test_related_pmid_and_nested_pubtype_cannot_replace_primary_fields(self):
        xml = '''<PubmedArticleSet><PubmedArticle><MedlineCitation><Article>
          <ArticleTitle>Missing primary PMID</ArticleTitle>
          <PublicationTypeList><PublicationType>Journal Article</PublicationType></PublicationTypeList>
          </Article><CommentsCorrectionsList><CommentsCorrections RefType="CommentOn">
          <PMID>999</PMID></CommentsCorrections></CommentsCorrectionsList></MedlineCitation>
          <PubmedData><ReferenceList><Reference><PublicationType>Retracted Publication</PublicationType>
          </Reference></ReferenceList></PubmedData></PubmedArticle></PubmedArticleSet>'''
        parsed = parse_efetch_xml(xml)[0]
        self.assertEqual(parsed["pmid"], "")
        self.assertEqual(parsed["integrity"], "ok")
        self.assertEqual(parsed["pubtypes"], ["Journal Article"])

    def test_relation_without_linked_pmid_still_marks_affected_article(self):
        xml = '''<PubmedArticleSet><PubmedArticle><MedlineCitation><PMID>123</PMID><Article>
          <ArticleTitle>Original study</ArticleTitle></Article><CommentsCorrectionsList>
          <CommentsCorrections RefType="ErratumIn"><RefSource>Journal. Correction citation.</RefSource>
          </CommentsCorrections></CommentsCorrectionsList></MedlineCitation></PubmedArticle></PubmedArticleSet>'''
        parsed = parse_efetch_xml(xml)[0]
        self.assertEqual(parsed["integrity"], "corrected")
        self.assertIsNone(parsed["integrity_relations"][0]["pmid"])
        self.assertEqual(parsed["integrity_relations"][0]["citation"], "Journal. Correction citation.")

    def test_legacy_ok_cannot_override_new_metadata_and_old_severe_state_survives(self):
        self.assertFalse(is_usable_evidence({"integrity": "ok", "pubtypes": ["Retraction Notice"]}))
        self.assertFalse(is_usable_evidence({"integrity": "ok", "integrity_relations": [{"ref_type": "RetractionIn"}]}))
        self.assertEqual(document_integrity({"integrity": "retracted"})["integrity_flags"], ["retracted"])
        self.assertFalse(document_integrity({"integrity": "corrected"})["is_notice"])

    def test_offline_loader_reconciles_legacy_integrity_fields(self):
        import json
        import tempfile
        from app.pubmed import load_corpus
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "corpus.json"
            path.write_text(json.dumps([{"pmid": "123", "integrity": "ok", "pubtypes": ["Published Erratum"]}]), encoding="utf-8")
            parsed = load_corpus(path)[0]
        self.assertTrue(parsed["is_notice"])
        self.assertEqual(parsed["integrity"], "notice")


if __name__ == "__main__":
    unittest.main()
