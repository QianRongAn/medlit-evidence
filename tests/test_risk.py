"""模型输出契约：分数不代表校准后的事件概率。"""
import unittest
from unittest.mock import Mock, patch

from app import risk


class TestResearchScore(unittest.TestCase):
    def test_score_contract_has_no_probability_or_risk_band(self):
        model = Mock()
        model.predict_proba.return_value = [[0.27, 0.73]]
        with patch.object(risk, "_load", return_value=True), \
             patch.object(risk, "_model", model), patch.object(risk, "_scaler", Mock()):
            result = risk.predict_risk({"title": "A trial", "source": "pubmed"})
        self.assertEqual(result["kind"], "research_model_score")
        self.assertEqual(result["score"], 73.0)
        self.assertEqual(result["scale"], [0, 100])
        self.assertFalse(result["calibrated"])
        self.assertNotIn("level", result)
        self.assertIn("不代表未来撤稿概率", result["description"])

    def test_demo_corpus_is_not_scored(self):
        with patch.object(risk, "_load") as load:
            self.assertIsNone(risk.predict_risk({"source": "offline"}))
            load.assert_not_called()

    def test_unavailable_model_returns_no_score(self):
        with patch.object(risk, "_load", return_value=False):
            self.assertIsNone(risk.predict_risk({}))

    def test_nonfinite_or_out_of_range_model_output_is_not_published(self):
        for value in (float("nan"), float("inf"), -0.01, 1.01):
            with self.subTest(value=value), patch.object(risk, "_load", return_value=True), \
                 patch.object(risk, "_model", Mock()) as model, patch.object(risk, "_scaler", Mock()):
                model.predict_proba.return_value = [[0, value]]
                self.assertIsNone(risk.predict_risk({}))

    def test_score_boundaries(self):
        for value, expected in ((0, 0), (1, 100)):
            with self.subTest(value=value), patch.object(risk, "_load", return_value=True), \
                 patch.object(risk, "_model", Mock()) as model, patch.object(risk, "_scaler", Mock()):
                model.predict_proba.return_value = [[1 - value, value]]
                self.assertEqual(risk.predict_risk({})["score"], expected)

    def test_partial_model_load_does_not_report_ready(self):
        joblib = Mock()
        joblib.load.side_effect = [Mock(), ValueError("broken scaler")]
        with patch.dict("sys.modules", {"joblib": joblib}), \
             patch.object(risk.os.path, "exists", return_value=True), \
             patch.object(risk, "_model", None), patch.object(risk, "_scaler", None), \
             patch.object(risk, "_load_failed", False):
            self.assertFalse(risk.model_available())
            self.assertFalse(risk.model_available())
            self.assertIsNone(risk._model)
            self.assertIsNone(risk.predict_risk({}))
