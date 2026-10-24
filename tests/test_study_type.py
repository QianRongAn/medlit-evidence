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

    def test_publication_type_overrides_background_and_title_keywords(self):
        cases = [
            (["Case Reports"], ("case_report", "Very low")),
            (["Randomized Controlled Trial"], ("randomized_controlled_trial", "Moderate")),
            (["Clinical Trial, Phase II"], ("clinical_trial", "Moderate")),
            (["Controlled Clinical Trial"], ("clinical_trial", "Moderate")),
            (["Review"], ("review", "N/A")),
        ]
        for pts, expected in cases:
            with self.subTest(pts=pts):
                self.assertEqual(classify("A previous meta-analysis was discussed.", pts,
                                          title="Meta-analysis mentioned in discussion"), expected)

    def test_metadata_hierarchy_is_specific_and_order_independent(self):
        cases = [
            (["Clinical Trial", "Randomized Controlled Trial"], "randomized_controlled_trial"),
            (["Review", "Systematic Review", "Meta-Analysis"], "meta_analysis"),
            (["Review", "Systematic Review"], "systematic_review"),
            (["Clinical Trial", "Clinical Trial, Phase III"], "clinical_trial"),
        ]
        for pts, expected in cases:
            for order in (pts, pts[::-1]):
                with self.subTest(order=order):
                    self.assertEqual(classify("", order)[0], expected)

    def test_conflicting_specific_metadata_abstains(self):
        self.assertEqual(classify("", ["Case Reports", "Meta-Analysis"]), ("other", "N/A"))

    def test_metadata_matching_uses_exact_terms(self):
        self.assertEqual(classify("", ["  RANDOMIZED  CONTROLLED TRIAL  "])[0], "randomized_controlled_trial")
        self.assertEqual(classify("", ["Randomized Controlled Trials as Topic"]), ("other", "N/A"))

    def test_title_design_is_not_overridden_by_abstract_background(self):
        abstract = "BACKGROUND: A previous meta-analysis showed benefit. DISCUSSION: Randomized trials are needed."
        self.assertEqual(classify(abstract, ["Journal Article"], title="Metformin: a case report"),
                         ("case_report", "Very low"))
        self.assertEqual(classify(abstract, title="Metformin: a case-control study"), ("case_control", "Low"))

    def test_only_own_methods_are_used_as_abstract_fallback(self):
        abstract = ("BACKGROUND: A meta-analysis of randomized controlled trials showed benefit. "
                    "METHODS: We conducted a retrospective case-control study. "
                    "DISCUSSION: A systematic review is needed.")
        self.assertEqual(classify(abstract, title="Metformin outcomes"), ("case_control", "Low"))

    def test_background_or_referred_design_alone_cannot_assign_grade(self):
        texts = ["Previous meta-analysis reported benefit.",
                 "BACKGROUND: A systematic review suggested benefit. CONCLUSIONS: More trials are needed.",
                 "METHODS: We compared estimates from previous randomized controlled trials.",
                 "We performed an analysis of previous meta-analysis results."]
        for text in texts:
            with self.subTest(text=text):
                self.assertEqual(classify(text, ["Journal Article"], title="Metformin effects"), ("other", "N/A"))

    def test_word_boundaries_and_nonrandomization_prevent_false_trials(self):
        for title in ("A non-randomized controlled trial", "A non randomized controlled trial",
                      "A phase imaging method", "A prospective analysis with follow-up", "Preview of a treatment"):
            with self.subTest(title=title):
                self.assertEqual(classify("", title=title), ("other", "N/A"))

    def test_protocols_and_comments_do_not_become_completed_trials(self):
        for title in ("Study protocol for a randomized controlled trial", "Comment on a meta-analysis"):
            with self.subTest(title=title):
                self.assertEqual(classify("", title=title), ("other", "N/A"))
        for pt in ("Editorial", "Letter", "Comment", "News", "Clinical Trial Protocol"):
            with self.subTest(pt=pt):
                self.assertEqual(classify("We performed a meta-analysis.", [pt]), ("other", "N/A"))

    def test_notices_are_never_study_designs(self):
        for pt in ("Retraction Notice", "Retraction of Publication", "Expression of Concern", "Published Erratum"):
            with self.subTest(pt=pt):
                self.assertEqual(classify("We performed a meta-analysis.", [pt, "Meta-Analysis"]), ("notice", "N/A"))

    def test_observational_metadata_does_not_upgrade_to_interventional_trial(self):
        self.assertEqual(classify("", ["Observational Study"], title="A randomized controlled trial"), ("other", "N/A"))
        self.assertEqual(classify("", ["Observational Study"], title="A prospective cohort study"), ("cohort", "Low"))

    def test_uncertain_title_cannot_be_promoted_by_secondary_abstract_cue(self):
        self.assertEqual(classify("We performed a meta-analysis.", title="A case report and meta-analysis"),
                         ("other", "N/A"))

    def test_title_mentions_of_research_types_cannot_manufacture_high_grade(self):
        for title in ("Evaluation of meta-analysis software", "Impact of a systematic review on practice",
                      "Comment on a meta-analysis", "Lessons from a previous randomized controlled trial"):
            with self.subTest(title=title):
                self.assertEqual(classify("", ["Journal Article"], title=title), ("other", "N/A"))
        self.assertEqual(classify("", title="A review of meta-analysis tools"), ("review", "N/A"))


if __name__ == "__main__":
    unittest.main()
