"""轻量分词：英文按词切分并去停用词，中文按单字 + 双字 bigram 切分。

不依赖 jieba/nltk，保证零重型依赖即可运行。医学文本以英文为主，
中文问题也能通过单字 + bigram 完成召回。
"""
import re

STOPWORDS = {
    "the", "a", "an", "and", "or", "but", "of", "in", "on", "at", "to", "for",
    "with", "by", "as", "is", "are", "was", "were", "be", "been", "being",
    "this", "that", "these", "those", "it", "its", "we", "our", "you", "your",
    "they", "their", "he", "she", "from", "not", "no", "yes", "has", "have",
    "had", "do", "does", "did", "will", "would", "can", "could", "should",
    "may", "might", "which", "who", "whom", "what", "when", "where", "why",
    "how", "such", "than", "then", "also", "more", "most", "only", "very",
    "just", "about", "between", "during", "after", "before", "using", "used",
    "use", "associated", "association", "compared", "comparison", "study",
    "studies", "patients", "patient", "group", "groups", "results", "result",
    "conclusion", "conclusions", "background", "objective", "methods", "method",
    "aim", "however", "although", "whereas", "among", "within", "without",
    "including", "include", "includes", "effect", "effects", "outcome",
    "outcomes", "trial", "trials", "treatment", "treat", "treated", "therapy",
    "risk", "significantly", "significant", "vs", "versus", "et", "al", "new",
    "per", "via", "clinical", "follow", "following", "showed", "shown", "shows",
    "found", "finding", "findings", "reported", "report", "evidence", "data",
    "mean", "median", "total", "both", "each", "other", "well", "two", "three",
    "one", "first", "second", "large", "small", "high", "higher", "low",
    "lower", "greater", "less", "randomized", "randomised", "double", "blind",
    "placebo", "does", "reduce", "reduced", "reduction", "increase",
    "increased", "improve", "improved",
}

# 常见药物 / 疾病缩写归一化，提升召回
ALIASES = {
    "t2dm": "diabetes",
    "pd-1": "pd1",
    "pd-l1": "pdl1",
    "ctla-4": "ctla4",
    "checkpoint": "ici",
    "nsclc": "nsclc",
    "acei": "acei",
    "arb": "arb",
    "mi": "mi",
    "cad": "cad",
    "cvd": "cvd",
    "ckd": "ckd",
    "sglt2": "sglt2",
    "glp-1": "glp1",
}

CJK_RE = re.compile(r"[\u4e00-\u9fff]")
WORD_RE = re.compile(r"[a-z0-9][a-z0-9\-]*")


def tokenize(text):
    if not text:
        return []
    text = text.lower()

    cjk = CJK_RE.findall(text)
    bigrams = [cjk[i] + cjk[i + 1] for i in range(len(cjk) - 1)]

    tokens = []
    for w in WORD_RE.findall(text):
        if len(w) < 2:
            continue
        if w in STOPWORDS:
            continue
        w = ALIASES.get(w, w)
        tokens.append(w)

    tokens.extend(cjk)
    tokens.extend(bigrams)
    return tokens
