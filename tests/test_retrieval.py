"""检索与分词单元测试。"""
import unittest

from app.retrieval import rank
from app.tokenizer import tokenize


class TestTokenizer(unittest.TestCase):
    def test_stopwords_removed(self):
        t = tokenize("the effect of metformin on patients with diabetes")
        self.assertIn("metformin", t)
        self.assertNotIn("the", t)
        self.assertNotIn("patients", t)

    def test_alias(self):
        t = tokenize("PD-1 inhibitor in NSCLC")
        self.assertIn("pd1", t)
        self.assertIn("nsclc", t)

    def test_chinese_bigram(self):
        t = tokenize("二甲双胍对糖尿病")
        self.assertIn("二甲", t)
        self.assertIn("双胍", t)


class TestRank(unittest.TestCase):
    def test_relevant_doc_ranked_first(self):
        docs = [
            tokenize("metformin reduces cardiovascular risk in type 2 diabetes"),
            tokenize("a study of unrelated pediatric asthma treatment"),
        ]
        q = tokenize("metformin diabetes cardiovascular")
        ranked = rank(docs, q)
        self.assertTrue(ranked)
        self.assertEqual(ranked[0][0], 0)

    def test_empty_query(self):
        self.assertEqual(rank([["a"]], []), [])


if __name__ == "__main__":
    unittest.main()
