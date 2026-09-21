"""研究设计识别与证据分级的单元测试。"""
import unittest

from app.study_type import classify


class TestClassify(unittest.TestCase):
    def test_meta_analysis(self):
        label, grade = classify("We performed a meta-analysis of randomized trials.")
        self.assertEqual(label, "meta_analysis")
        self.assertEqual(grade, "High")

    def test_systematic_review(self):
        label, grade = classify("This systematic review included 20 studies.")
        self.assertEqual(label, "systematic_review")
        self.assertEqual(grade, "High")

    def test_rct(self):
        label, grade = classify("Patients were randomly assigned to receive the drug or placebo.")
        self.assertEqual(label, "randomized_controlled_trial")
        self.assertEqual(grade, "Moderate")

    def test_cohort(self):
        label, grade = classify("A prospective cohort study with long-term follow-up.")
        self.assertEqual(label, "cohort")
        self.assertEqual(grade, "Low")

    def test_case_report(self):
        label, grade = classify("We report a case series of three patients.")
        self.assertEqual(label, "case_report")
        self.assertEqual(grade, "Very low")

    def test_rct_before_review(self):
        # 随机对照试验里可能含 review 字样，RCT 应优先
        label, grade = classify("A randomized controlled trial, reviewed by an independent board.")
        self.assertEqual(label, "randomized_controlled_trial")


if __name__ == "__main__":
    unittest.main()
