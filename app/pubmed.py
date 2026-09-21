"""PubMed E-utilities 客户端：esearch + efetch，解析为结构化文献。

内置进程内 TTL 缓存，重复提问避免重复请求 PubMed（E-utilities 有频率限制）。
"""
import json
import time
import xml.etree.ElementTree as ET

import httpx

from .config import PUBMED_BASE, PUBMED_PROXY, PUBMED_TIMEOUT, RETMAX

_CACHE = {}  # key -> (expire_at, value)
_CACHE_TTL = 300  # 秒


def _cache_get(key):
    item = _CACHE.get(key)
    if item and item[0] > time.time():
        return item[1]
    return None


def _cache_set(key, value):
    _CACHE[key] = (time.time() + _CACHE_TTL, value)


def _client():
    kwargs = {"timeout": PUBMED_TIMEOUT}
    if PUBMED_PROXY:
        kwargs["proxy"] = PUBMED_PROXY
    return httpx.AsyncClient(**kwargs)


async def esearch(term, retmax=RETMAX):
    """返回 (pmids, total_count)。"""
    key = f"esearch:{term}:{retmax}"
    cached = _cache_get(key)
    if cached is not None:
        return cached

    url = f"{PUBMED_BASE}/esearch.fcgi"
    params = {
        "db": "pubmed",
        "term": term,
        "retmax": str(retmax),
        "retmode": "json",
        "sort": "relevance",
    }
    async with _client() as c:
        r = await c.get(url, params=params)
        r.raise_for_status()
        data = r.json()
        res = data.get("esearchresult", {})
        result = (res.get("idlist", []), int(res.get("count", "0") or 0))
        _cache_set(key, result)
        return result


async def efetch(pmids):
    """按 PMID 列表抓取题录 + 摘要。"""
    if not pmids:
        return []
    key = f"efetch:{','.join(sorted(pmids))}"
    cached = _cache_get(key)
    if cached is not None:
        return cached

    url = f"{PUBMED_BASE}/efetch.fcgi"
    params = {"db": "pubmed", "id": ",".join(pmids), "retmode": "xml"}
    async with _client() as c:
        r = await c.get(url, params=params)
        r.raise_for_status()
        docs = parse_efetch_xml(r.text)
        _cache_set(key, docs)
        return docs


def _find_text(el, path):
    node = el.find(path)
    if node is None:
        return ""
    return "".join(node.itertext()).strip()


def parse_efetch_xml(xml_text):
    root = ET.fromstring(xml_text)
    docs = []
    for art in root.findall(".//PubmedArticle"):
        pmid = _find_text(art, ".//PMID")

        abstract_parts = []
        for ab in art.findall(".//Abstract/AbstractText"):
            label = ab.get("Label")
            txt = "".join(ab.itertext()).strip()
            if label:
                txt = f"{label}: {txt}"
            abstract_parts.append(txt)

        year = None
        pubdate = art.find(".//JournalIssue/PubDate")
        if pubdate is not None:
            y = pubdate.findtext("Year")
            if y:
                year = y
            else:
                md = pubdate.find("MedlineDate")
                if md is not None:
                    year = (md.text or "")[:4] or None

        authors = []
        for a in art.findall(".//AuthorList/Author"):
            ln = _find_text(a, "LastName")
            fn = _find_text(a, "ForeName")
            if ln:
                authors.append(f"{fn} {ln}".strip())

        docs.append({
            "pmid": pmid,
            "title": _find_text(art, ".//ArticleTitle"),
            "abstract": "\n".join(abstract_parts),
            "journal": _find_text(art, ".//Journal/Title"),
            "year": year,
            "pubtypes": [_find_text(pt, ".") for pt in art.findall(".//PublicationType")],
            "authors": authors[:6],
            "source": "pubmed",
        })
    return docs


def load_corpus(path):
    """加载离线 fallback 语料。"""
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    for d in data:
        d.setdefault("source", "offline")
        d.setdefault("authors", [])
        d.setdefault("pubtypes", [])
    return data
