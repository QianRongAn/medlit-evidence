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

    def test_generic_diabetes_and_incident_diabetes_have_distinct_roles(self):
        self.assertEqual(extract_pico("糖尿病患者")["population"], ["diabetes"])
        self.assertEqual(extract_pico("新发糖尿病风险")["population"], [])
        self.assertEqual(extract_pico("新发糖尿病风险")["outcome"], ["incident diabetes"])
        self.assertEqual(extract_pico("二甲双胍会增加糖尿病风险吗")["outcome"], ["diabetes"])

    def test_boundaries_and_active_comparator_roles(self):
        self.assertEqual(extract_pico("nystatin")["intervention"], [])
        self.assertEqual(extract_pico("metformin versus aspirin")["comparison"], ["aspirin"])
        self.assertEqual(extract_pico("nivolumab versus pembrolizumab")["intervention"], ["nivolumab"])

    def test_typed_diabetes_and_specific_cancer_do_not_duplicate_generic_terms(self):
        self.assertEqual(extract_pico("type 2 diabetes patients")["population"], ["type 2 diabetes"])
        self.assertEqual(extract_pico("patients with lung cancer")["population"], ["lung cancer"])




class LabelledPicoTests(unittest.TestCase):
    def test_explicit_fields_recognize_unknown_english_terms_in_their_given_role(self):
        p=extract_pico("P: adults with bronchiectasis; I: budesonide; C: placebo; O: exacerbations")
        self.assertEqual(p['population'],['adults','bronchiectasis'])
        self.assertEqual(p['intervention'],['budesonide'])
        self.assertEqual(p['comparison'],['placebo'])
        self.assertEqual(p['outcome'],['exacerbations'])

    def test_chinese_labels_and_patients_suffix_do_not_create_spurious_terms(self):
        p=extract_pico("人群：心衰患者；干预：SGLT2 抑制剂；对照：常规治疗；结局：全因死亡率")
        self.assertEqual(p['population'],['heart failure'])
        self.assertEqual(p['intervention'],['sglt2 inhibitor'])
        self.assertEqual(p['comparison'],['standard care'])
        self.assertEqual(p['outcome'],['mortality'])

    def test_specific_statins_keep_comparator_identity(self):
        p=extract_pico("阿托伐他汀比瑞舒伐他汀能降低死亡率吗")
        self.assertEqual(p['intervention'],['atorvastatin'])
        self.assertEqual(p['comparison'],['rosuvastatin'])

    def test_common_aliases_do_not_invent_other_fields(self):
        p=extract_pico("older adults with asthma received sglt-2 inhibitors for hospitalizations")
        self.assertEqual(p['population'],['elderly','asthma'])
        self.assertEqual(p['intervention'],['sglt2 inhibitor'])
        self.assertEqual(p['outcome'],['hospitalization'])
        self.assertEqual(p['comparison'],[])


if __name__ == "__main__":
    unittest.main()
