"""BM25 检索。纯 Python 实现，文档量小（20 篇左右）时足够快且零依赖。"""
import math
from collections import Counter


class BM25:
    def __init__(self, docs, k1=1.5, b=0.75):
        self.k1 = k1
        self.b = b
        self.docs = docs  # list[list[str]]
        self.n = len(docs)
        self.doc_len = [len(d) for d in docs]
        self.avgdl = sum(self.doc_len) / max(1, self.n)

        self.df = Counter()
        for d in docs:
            for t in set(d):
                self.df[t] += 1

        self.idf = {}
        n = self.n
        for t, df in self.df.items():
            self.idf[t] = math.log(1 + (n - df + 0.5) / (df + 0.5))

    def score(self, query_tokens):
        qf = Counter(query_tokens)
        scores = [0.0] * self.n
        for t, qtf in qf.items():
            idf = self.idf.get(t, 0.0)
            if idf == 0.0:
                continue
            for i, d in enumerate(self.docs):
                tf = d.count(t)
                if tf == 0:
                    continue
                denom = tf + self.k1 * (1 - self.b + self.b * self.doc_len[i] / self.avgdl)
                scores[i] += idf * (tf * (self.k1 + 1)) / denom * qtf
        return scores


def rank(docs_tokens, query_tokens):
    """返回 [(doc_index, score), ...] 按分数降序，仅保留 score > 0。"""
    if not docs_tokens or not query_tokens:
        return []
    bm = BM25(docs_tokens)
    scores = bm.score(query_tokens)
    ranked = [(i, s) for i, s in enumerate(scores) if s > 0]
    ranked.sort(key=lambda x: -x[1])
    return ranked
