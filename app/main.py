"""MedLit Evidence 后端入口：FastAPI 服务。

用法：
    python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
"""
import asyncio
import os

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .config import CORPUS_FILE, LLM_API_KEY, RETMAX, STATIC_DIR
from .evidence import analyze_evidence
from .pico import extract_pico
from .pubmed import efetch, esearch, load_corpus
from .retrieval import rank
from .risk import predict_risk
from .study_type import classify
from .synthesizer import extractive_answer, llm_answer
from .tokenizer import tokenize
from .translate import translate_query

app = FastAPI(title="MedLit Evidence", version="0.1.0")


class Query(BaseModel):
    query: str
    retmax: int = RETMAX


def _search_text(query):
    """中文提问先翻译成英文检索词，英文提问原样返回。"""
    translated = translate_query(query)
    return translated or query


def _query_tokens(query):
    """检索用的 token：原文 + 翻译后的英文，保证中英文都能命中。"""
    return tokenize(query) + tokenize(_search_text(query))


def _annotate_docs(docs, query_tokens):
    """分类 + BM25 打分 + 归一化，按相关性降序返回。"""
    doc_tokens = [tokenize((d.get("title") or "") + " " + (d.get("abstract") or "")) for d in docs]
    ranked = rank(doc_tokens, query_tokens)

    max_score = max((s for _, s in ranked), default=0.0) or 1.0
    for d in docs:
        d["study_type"], d["grade"] = classify(
            (d.get("abstract") or "") + " " + (d.get("title") or ""), d.get("pubtypes")
        )
        d["relevance"] = 0.0

    for i, s in ranked:
        docs[i]["relevance"] = round(s / max_score * 100, 1)

    docs.sort(key=lambda d: -d["relevance"])
    return docs


async def _retrieve(query, retmax):
    """在线 PubMed 优先，失败或空则回退离线语料。返回 (docs, online, count)。"""
    search_text = _search_text(query)
    try:
        pmids, count = await esearch(search_text, retmax)
        docs = await efetch(pmids) if pmids else []
        if docs:
            return docs, True, count
    except Exception:
        docs = []

    corpus = load_corpus(CORPUS_FILE)
    tokens = _query_tokens(query)
    ranked = rank([tokenize((d.get("title") or "") + " " + (d.get("abstract") or "")) for d in corpus], tokens)
    picked = [corpus[i] for i, _ in ranked[:retmax]]
    return picked, False, len(picked)


@app.get("/health")
async def health():
    online = False
    try:
        _, count = await esearch("metformin", retmax=1)
        online = count > 0
    except Exception:
        online = False
    return {"status": "ok", "pubmed_online": online}


@app.post("/api/search")
async def search(q: Query):
    query = q.query.strip()
    if not query:
        raise HTTPException(status_code=400, detail="query 不能为空")
    query_tokens = _query_tokens(query)

    docs, online, count = await _retrieve(query, q.retmax)
    docs = _annotate_docs(docs, query_tokens)

    return {
        "query": query,
        "online": online,
        "total": count,
        "count": len(docs),
        "results": [
            {
                "pmid": d.get("pmid"),
                "title": d.get("title"),
                "abstract": d.get("abstract"),
                "journal": d.get("journal"),
                "year": d.get("year"),
                "authors": d.get("authors"),
                "study_type": d.get("study_type"),
                "grade": d.get("grade"),
                "relevance": d.get("relevance"),
                "source": d.get("source"),
                "integrity": d.get("integrity", "ok"),
                "risk": predict_risk(d),
            }
            for d in docs
        ],
    }


@app.post("/api/answer")
async def answer(q: Query):
    query = q.query.strip()
    if not query:
        raise HTTPException(status_code=400, detail="query 不能为空")
    query_tokens = _query_tokens(query)

    docs, online, count = await _retrieve(query, q.retmax)
    docs = _annotate_docs(docs, query_tokens)

    top = [d for d in docs if d.get("relevance", 0) > 0][:8]

    mode = "extractive"
    answer_text = None
    if LLM_API_KEY and top:
        try:
            answer_text = await llm_answer(query, top)
            mode = "llm"
        except Exception:
            answer_text = None

    sentences = None
    if answer_text is None:
        sentences = extractive_answer(top or docs, query_tokens)
        parts = []
        for s in sentences:
            parts.append(f"{s['sentence']} [PMID {s['pmid']}]")
        answer_text = "\n\n".join(parts)
        mode = "extractive"

    evidence = analyze_evidence(top or docs)

    # 证据等级分布
    from collections import Counter
    dist = Counter(d.get("grade", "N/A") for d in docs)

    return {
        "query": query,
        "online": online,
        "total": count,
        "mode": mode,
        "answer": answer_text,
        "sentences": sentences,
        "pico": extract_pico(query),
        "evidence": evidence,
        "evidence_distribution": {k: dist.get(k, 0) for k in ["High", "Moderate", "Low", "Very low", "N/A"]},
        "results": [
            {
                "pmid": d.get("pmid"),
                "title": d.get("title"),
                "abstract": d.get("abstract"),
                "journal": d.get("journal"),
                "year": d.get("year"),
                "authors": d.get("authors"),
                "study_type": d.get("study_type"),
                "grade": d.get("grade"),
                "relevance": d.get("relevance"),
                "source": d.get("source"),
                "integrity": d.get("integrity", "ok"),
                "risk": predict_risk(d),
            }
            for d in docs
        ],
    }


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/")
async def index():
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))
