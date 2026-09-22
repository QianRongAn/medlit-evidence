"""PICO 结构化提取的单测。"""
import unittest

from app.pico import extract_pico


class TestPico(unittest.TestCase):
    def test_chinese_diabetes_metformin(self):
        p = extract_pico("二甲双胍能降低2型糖尿病患者的心血管风险吗")
        self.assertIn("metformin", p["intervention"])
        self.assertTrue(any("diabetes" in x for x in p["population"]))
        self.assertTrue(any("cardiovascular" in x for x in p["outcome"]))

    def test_english_statin_diabetes(self):
        p = extract_pico("statins risk of incident diabetes")
        self.assertIn("statin", p["intervention"])
        self.assertIn("incident diabetes", p["outcome"])

    def test_english_sglt2_heart_failure(self):
        p = extract_pico("SGLT2 inhibitor heart failure")
        self.assertIn("sglt2 inhibitor", p["intervention"])
        self.assertIn("heart failure", p["population"])

    def test_pd1_melanoma_survival(self):
        p = extract_pico("PD-1 inhibitor advanced melanoma overall survival")
        self.assertIn("pd-1 inhibitor", p["intervention"])
        self.assertIn("melanoma", p["population"])
        self.assertIn("overall survival", p["outcome"])

    def test_comparison_placebo(self):
        p = extract_pico("aspirin versus placebo for prevention of myocardial infarction")
        self.assertIn("aspirin", p["intervention"])
        self.assertIn("placebo", p["comparison"])
        self.assertIn("myocardial infarction", p["outcome"])

    def test_empty_when_no_match(self):
        p = extract_pico("你好吗")
        self.assertEqual(p["population"], [])
        self.assertEqual(p["intervention"], [])
        self.assertEqual(p["outcome"], [])


if __name__ == "__main__":
    unittest.main()
