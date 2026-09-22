"""撤稿/更正/存疑检测的单测（纯逻辑，不依赖网络）。"""
import unittest

from app.pubmed import _detect_integrity, parse_efetch_xml


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
            _detect_integrity(["Expression of Concern"], []),
            "concern",
        )

    def test_corrected(self):
        self.assertEqual(
            _detect_integrity(["Published Erratum"], []),
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
        <PublicationType>Journal Article</PublicationType>
        <PublicationType>Retracted Publication</PublicationType>
      </Article>
    </MedlineCitation>
  </PubmedArticle>
</PubmedArticleSet>"""
        docs = parse_efetch_xml(xml)
        self.assertEqual(len(docs), 1)
        self.assertEqual(docs[0]["integrity"], "retracted")
        self.assertEqual(docs[0]["pmid"], "9500320")


if __name__ == "__main__":
    unittest.main()
