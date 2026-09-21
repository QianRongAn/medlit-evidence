"""全局配置，全部可从环境变量覆盖。"""
import os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")
STATIC_DIR = os.path.join(BASE_DIR, "static")

# PubMed E-utilities
PUBMED_BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
PUBMED_PROXY = os.environ.get("PUBMED_PROXY", "").strip()
PUBMED_TIMEOUT = float(os.environ.get("PUBMED_TIMEOUT", "12"))
RETMAX = int(os.environ.get("RETMAX", "20"))

# 可选 LLM（OpenAI 兼容接口），不配置则走离线抽取式回答
LLM_API_KEY = os.environ.get("LLM_API_KEY", "").strip()
LLM_BASE_URL = os.environ.get("LLM_BASE_URL", "https://api.openai.com/v1").strip()
LLM_MODEL = os.environ.get("LLM_MODEL", "gpt-4o-mini").strip()

# 离线 fallback 语料
CORPUS_FILE = os.path.join(DATA_DIR, "sample_corpus.json")
