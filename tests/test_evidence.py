"""结论极性、冲突检测与置信度评分的单元测试。"""
import unittest

from app.evidence import analyze_evidence, classify_polarity, compute_confidence


class TestPolarity(unittest.TestCase):
    def test_support(self):
        self.assertEqual(classify_polarity("Metformin reduced cardiovascular risk."), "support")

    def test_against_no_difference(self):
        self.assertEqual(classify_polarity("There was no significant difference between groups."), "against")

    def test_against_increased_risk(self):
        self.assertEqual(classify_polarity("Statin therapy was associated with increased risk of diabetes."), "against")

    def test_neutral(self):
        self.assertEqual(classify_polarity("The underlying mechanism remains unclear."), "neutral")


class TestConflict(unittest.TestCase):
    def _doc(self, pmid, concl, grade="Moderate", year="2020"):
        return {"pmid": pmid, "title": "t", "abstract": "BACKGROUND: x. RESULTS: y. CONCLUSIONS: " + concl,
                "grade": grade, "year": year, "pubtypes": []}

    def test_conflict_detected(self):
        docs = [
            self._doc("1", "The drug reduced mortality."),
            self._doc("2", "The drug had no significant benefit."),
        ]
        ev = analyze_evidence(docs)
        self.assertTrue(ev["conflict"])
        self.assertEqual(ev["verdict"], "证据存在分歧")
        self.assertEqual(ev["support_count"], 1)
        self.assertEqual(ev["against_count"], 1)

    def test_consensus_support(self):
        docs = [self._doc("1", "The drug reduced mortality."), self._doc("2", "The drug improved survival.")]
        ev = analyze_evidence(docs)
        self.assertFalse(ev["conflict"])
        self.assertEqual(ev["verdict"], "证据倾向支持")

    def test_confidence_in_range(self):
        docs = [self._doc("1", "The drug reduced mortality.", grade="High", year="2022")]
        score = compute_confidence(docs, conflict=False)
        self.assertTrue(0 <= score <= 100)


if __name__ == "__main__":
    unittest.main()
