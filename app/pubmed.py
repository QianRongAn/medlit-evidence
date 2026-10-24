"""PubMed E-utilities 客户端：esearch + efetch，解析为结构化文献。

内置进程内 TTL 缓存，重复提问避免重复请求 PubMed（E-utilities 有频率限制）。
"""
import base64
import hashlib
import asyncio
import json
import time
import xml.etree.ElementTree as ET

import httpx

from .config import PUBMED_BASE, PUBMED_PROXY, PUBMED_TIMEOUT, RETMAX
from .integrity import document_integrity, integrity_details

_CACHE = {}  # key -> (expire_at, value)
_CACHE_TTL = 300  # 秒
_RATE_LOOP = None
_RATE_LOCK = None
_NEXT_REQUEST = 0.0


async def _respect_rate_limit():
    global _RATE_LOOP, _RATE_LOCK, _NEXT_REQUEST
    loop = asyncio.get_running_loop()
    if _RATE_LOOP is not loop:
        _RATE_LOOP, _RATE_LOCK, _NEXT_REQUEST = loop, asyncio.Lock(), 0.0
    async with _RATE_LOCK:
        delay = _NEXT_REQUEST - loop.time()
        if delay > 0:
            await asyncio.sleep(delay)
        _NEXT_REQUEST = loop.time() + 0.35


def _cache_get(key):
    item = _CACHE.get(key)
    if item and item[0] > time.time():
        return item[1]
    return None


def _cache_set(key, value):
    _CACHE[key] = (time.time() + _CACHE_TTL, value)


def _client():
    # Configure PubMed through PUBMED_PROXY; unrelated inherited proxies can expire.
    kwargs = {"timeout": PUBMED_TIMEOUT, "trust_env": False}
    if PUBMED_PROXY:
        kwargs["proxy"] = PUBMED_PROXY
    return httpx.AsyncClient(**kwargs)


async def esearch(term, retmax=RETMAX, retstart=0):
    """返回 (pmids, total_count)。"""
    key = f"esearch:{term}:{retmax}:{retstart}"
    cached = _cache_get(key)
    if cached is not None:
        return cached

    url = f"{PUBMED_BASE}/esearch.fcgi"
    params = {
        "db": "pubmed",
        "term": term,
        "retmax": str(retmax),
        "retstart": str(retstart),
        "retmode": "json",
        "sort": "relevance",
    }
    await _respect_rate_limit()
    async with _client() as c:
        r = await c.get(url, params=params)
        r.raise_for_status()
        data = r.json()
        res = data.get("esearchresult", {})
        result = (res.get("idlist", []), int(res.get("count", "0") or 0))
        _cache_set(key, result)
        return result


class InvalidCursor(ValueError):
    pass


def _page_token(term, parts, total):
    if not parts:
        return None
    payload = {"q": hashlib.sha256(term.encode()).hexdigest()[:20], "parts": parts, "total": total}
    return base64.urlsafe_b64encode(json.dumps(payload,separators=(",",":")).encode()).decode().rstrip("=")


def _read_page_token(term, token):
    try:
        payload=json.loads(base64.urlsafe_b64decode(token + "=" * (-len(token)%4)))
        parts=payload["parts"]
        if payload["q"] != hashlib.sha256(term.encode()).hexdigest()[:20]:
            raise ValueError("cursor does not match this query")
        if not isinstance(parts,list) or not 1 <= len(parts) <= 64:
            raise ValueError("invalid cursor partitions")
        previous=0
        for part in parts:
            if not isinstance(part,list) or len(part)!=3 or any(type(n) is not int for n in part):
                raise ValueError("invalid cursor range")
            low,high,offset=part
            if not 0 <= low <= high <= 2147483647 or not 0 <= offset < 10000 or low < previous:
                raise ValueError("invalid cursor bounds")
            previous=high
        if type(payload["total"]) is not int or payload["total"] < 0:
            raise ValueError("invalid cursor count")
        return parts,payload["total"]
    except (KeyError,TypeError,UnicodeError,json.JSONDecodeError,ValueError) as error:
        raise InvalidCursor("无效或不属于本次问题的分页游标，请重新检索。") from error


async def esearch_page(term, retmax, cursor=None, first_result=None):
    """Continue all results, partitioning UID ranges beyond PubMed's 10,000-ID window."""
    if cursor:
        parts,total=_read_page_token(term,cursor)
    else:
        ids,total=first_result if first_result is not None else await esearch(term,retmax)
        if total <= 9999:
            offset=len(ids)
            return ids,total,_page_token(term,[[0,0,offset]],total) if ids and offset < total else None
        parts=[[1,2147483647,0]]
    while parts:
        low,high,offset=parts[0]
        bounded=term if low==high==0 else f"({term}) AND {low}:{high}[UID]"
        ids,count=await esearch(bounded,retmax,retstart=offset)
        if count > 9999:
            if low==high==0:
                parts=[[1,2147483647,0]]
                continue
            if low>=high:
                raise RuntimeError("PubMed UID partition could not be subdivided")
            middle=(low+high)//2
            parts[:1]=[[low,middle,0],[middle+1,high,0]]
            continue
        if not ids:
            if offset < count:
                raise RuntimeError("PubMed returned an empty page before the result set ended")
            parts.pop(0)
            continue
        next_offset=offset+len(ids)
        if next_offset>=count:
            parts.pop(0)
        else:
            parts[0]=[low,high,next_offset]
        return ids,total,_page_token(term,parts,total)
    return [],total,None


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
    await _respect_rate_limit()
    async with _client() as c:
        r = await c.get(url, params=params)
        r.raise_for_status()
        docs = parse_efetch_xml(r.content)  # 用字节流解析，尊重 XML 声明的编码
        _cache_set(key, docs)
        return docs


def _find_text(el, path):
    node = el.find(path)
    if node is None:
        return ""
    return "".join(node.itertext()).strip()


def _detect_integrity(pubtypes, reftypes):
    """兼容旧调用：返回主状态；完整标记与通知身份见 integrity_details。"""
    return integrity_details(pubtypes, reftypes)["integrity"]


def parse_efetch_xml(xml_text):
    root = ET.fromstring(xml_text)
    docs = []
    for art in root.findall(".//PubmedArticle"):
        pmid = _find_text(art, "./MedlineCitation/PMID")

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

        affiliations = set()
        for aff in art.findall(".//AffiliationInfo/Affiliation"):
            t = "".join(aff.itertext()).strip()
            if t:
                affiliations.add(t.lower())

        pubtypes = [_find_text(pt, ".") for pt in art.findall(
            "./MedlineCitation/Article/PublicationTypeList/PublicationType")]
        relations = [{
            "ref_type": cc.get("RefType", "").strip(),
            "pmid": _find_text(cc, "./PMID") or None,
            "citation": _find_text(cc, "./RefSource"),
        } for cc in art.findall("./MedlineCitation/CommentsCorrectionsList/CommentsCorrections")]
        details = integrity_details(pubtypes, [r["ref_type"] for r in relations])

        docs.append({
            "pmid": pmid,
            "title": _find_text(art, ".//ArticleTitle"),
            "abstract": "\n".join(abstract_parts),
            "journal": _find_text(art, ".//Journal/Title"),
            "year": year,
            "pubtypes": pubtypes,
            "authors": authors[:6],
            "n_authors": len(authors),
            "n_affiliations": len(affiliations),
            "n_grants": len(art.findall(".//GrantList/Grant")),
            "n_references": len(art.findall(".//ReferenceList/Reference")),
            "language": _find_text(art, ".//Language"),
            "source": "pubmed",
            **details,
            "integrity_relations": relations,
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
        d.update(document_integrity(d))
        d.setdefault("integrity_relations", [])
        d.setdefault("n_authors", len(d.get("authors", [])))
        d.setdefault("n_affiliations", 0)
        d.setdefault("n_grants", 0)
        d.setdefault("n_references", 0)
        d.setdefault("language", "eng")
    return data
