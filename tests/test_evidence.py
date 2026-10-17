"""回归：不得把措辞极性冒充对临床问题的判定。"""
import unittest

from app.evidence import analyze_evidence, extract_conclusion


def doc(pmid, text, integrity="ok", grade="High"):
    return {"pmid": pmid, "title": "Study", "abstract": text,
            "grade": grade, "year": "2026", "integrity": integrity}


class TestAssessmentAbstention(unittest.TestCase):
    def assert_unassessed(self, result, count):
        self.assertEqual(result["assessment_status"], "unassessed")
        self.assertIsNone(result["confidence"])
        self.assertIsNone(result["conflict"])
        self.assertEqual(result["unassessed_count"], count)
        self.assertEqual(result["support_count"], 0)
        self.assertEqual(result["against_count"], 0)
        self.assertEqual(result["neutral_count"], 0)
        self.assertTrue(all(it["polarity"] == "unassessed" for it in result["conclusions"]))

    def test_different_outcomes_do_not_create_false_conflict(self):
        result = analyze_evidence([
            doc("1", "Statin therapy increased risk of incident diabetes."),
            doc("2", "Statin therapy reduced cardiovascular risk."),
        ])
        self.assert_unassessed(result, 2)
        self.assertEqual(result["verdict"], "证据方向待核对")

    def test_benefit_words_do_not_produce_support_or_high_confidence(self):
        self.assert_unassessed(analyze_evidence([
            doc("1", "Metformin reduced mortality."),
            doc("2", "Metformin improved survival."),
        ]), 2)

    def test_negation_uncertainty_and_harm_are_not_opposition(self):
        examples = [
            "Statin therapy increased risk of new-onset diabetes.",
            "Metformin did not reduce mortality.",
            "Metformin did not increase mortality.",
            "There was no significant difference between groups.",
            "It is not unlikely that treatment may reduce mortality.",
            "Treatment reduced mortality but increased bleeding.",
            "The mechanism remains unclear.",
        ]
        for text in examples:
            with self.subTest(text=text):
                self.assert_unassessed(analyze_evidence([doc("1", text)]), 1)

    def test_grade_quantity_and_recency_cannot_manufacture_confidence(self):
        self.assert_unassessed(analyze_evidence([
            doc(str(i), "Treatment reduced mortality.") for i in range(8)
        ]), 8)

    def test_no_evidence_is_distinct_from_unassessed(self):
        for records in ([], [doc("1", "Treatment improved survival.", "retracted")]):
            with self.subTest(records=records):
                result = analyze_evidence(records)
                self.assertEqual(result["assessment_status"], "no_usable_evidence")
                self.assertEqual(result["unassessed_count"], 0)
                self.assertIsNone(result["confidence"])
                self.assertIsNone(result["conflict"])

    def test_conclusion_is_preserved_as_source_text(self):
        record = doc("1", "BACKGROUND: A clinical question. CONCLUSIONS: Treatment reduced mortality.")
        result = analyze_evidence([record])
        self.assertEqual(result["conclusions"][0]["conclusion"], extract_conclusion(record))
        self.assertEqual(result["conclusions"][0]["grade"], "High")
        self.assertIn("CONCLUSIONS:", result["conclusions"][0]["conclusion"])

    def test_integrity_warnings_are_all_preserved(self):
        records = [doc("1", "Treatment improved survival.", "retracted"),
                   doc("2", "Treatment improved survival.", "concern"),
                   doc("3", "Treatment improved survival.", "corrected")]
        result = analyze_evidence(records)
        self.assert_unassessed(result, 2)
        for name in ("retracted", "concern", "corrected"):
            self.assertEqual(result[name + "_count"], 1)
        for label in ("撤稿", "存疑", "更正"):
            self.assertIn(label, result["integrity_warning"])


if __name__ == "__main__":
    unittest.main()
