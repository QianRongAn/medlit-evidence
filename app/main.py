"""MedLit Evidence 后端入口：FastAPI 服务。

用法：
    python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
"""
import os
from copy import deepcopy

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .config import CORPUS_FILE, LLM_API_KEY, RETMAX, STATIC_DIR
from .evidence import analyze_evidence
from .integrity import document_integrity, is_usable_evidence
from .pubmed import efetch, esearch, load_corpus
from .retrieval import rank
from .screening import build_query_plan, screen_document, screening_summary
from .risk import model_available, predict_risk
from .study_type import classify
from .synthesizer import CitationValidationError, extractive_answer, llm_answer
from .tokenizer import tokenize
from .translate import translate_query

app = FastAPI(title="MedLit Evidence", version="0.6.0")


class Query(BaseModel):
    query: str = Field(..., max_length=2000)
    retmax: int = Field(default=RETMAX, ge=1, le=100)


def _search_text(query):
    """生成召回词；中文使用已识别概念及有效词，不丢失已识别的 PICO 条件。"""
    translated = translate_query(query)
    if any("\u4e00" <= c <= "\u9fff" for c in query):
        # 使用完整概念短语，避免翻译丢失“2 型/新发”等条件或重复拼接药名。
        plan = build_query_plan(query)
        terms = [c for values in plan["pico"].values() for c in values] + plan["lexical_terms"]
        translated = " ".join(dict.fromkeys(terms)) or translated
    return translated or query


def _query_tokens(query):
    """词项去重，加入已识别概念的词典变体供排序；不作为纳入门槛。"""
    return build_query_plan(query)["ranking_tokens"]


def _annotate_docs(docs, query_tokens):
    """分类及原始 BM25 排序，不再按候选最大值生成 100 分。"""
    docs = deepcopy(docs)  # PubMed 缓存由多次请求共享，标注不得污染缓存。
    doc_tokens = [tokenize((d.get("title") or "") + " " + (d.get("abstract") or "")) for d in docs]
    ranked = rank(doc_tokens, query_tokens)

    for d in docs:
        d.update(document_integrity(d))
        if d.get("is_notice") or d.get("integrity") == "notice":
            d["study_type"], d["grade"] = "notice", "N/A"
        else:
            d["study_type"], d["grade"] = classify(
                d.get("abstract") or "", d.get("pubtypes"), title=d.get("title") or "")
        d["relevance"] = 0.0
        d["bm25_score"] = 0.0

    for i, s in ranked:
        docs[i]["bm25_score"] = round(s, 4)
        docs[i]["relevance"] = round(len(set(query_tokens) & set(doc_tokens[i])) / max(len(set(query_tokens)), 1) * 100, 1)

    docs.sort(key=lambda d: -d["bm25_score"])
    return docs


async def _retrieve(query, retmax):
    """在线 PubMed 优先，仅请求失败时回退演示语料。返回 (docs, online, count)。"""
    search_text = _search_text(query)
    try:
        pmids, count = await esearch(search_text, retmax)
        docs = await efetch(pmids) if pmids else []
        return docs, True, count
    except Exception:
        docs = []

    corpus = load_corpus(CORPUS_FILE)
    tokens = _query_tokens(query)
    ranked = rank([tokenize((d.get("title") or "") + " " + (d.get("abstract") or "")) for d in corpus], tokens)
    picked = [corpus[i] for i, _ in ranked]  # 先筛选，再按返回上限截断，避免弱匹配挤掉合格演示记录。
    return picked, False, len(picked)


def _source(d, score_model=True):
    fields = ("pmid", "title", "abstract", "journal", "year", "authors", "study_type", "grade",
              "relevance", "bm25_score", "source", "integrity", "integrity_flags", "is_notice",
              "notice_types", "integrity_relations", "screening", "answer_eligible")
    return {**{key: d.get(key) for key in fields}, "risk": predict_risk(d) if score_model else None}


async def _screened_retrieval(query, retmax):
    plan = build_query_plan(query)
    candidates, online, total = await _retrieve(query, retmax)
    candidates = _annotate_docs(candidates, plan["ranking_tokens"])
    included, excluded = [], []
    for d in candidates:
        d["screening"] = screen_document(d, plan)
        d["relevance"] = d["screening"]["coverage"]
        d["answer_eligible"] = d["screening"]["eligible"] and is_usable_evidence(d)
        (included if d["screening"]["eligible"] else excluded).append(d)
    included.sort(key=lambda d: (-d["relevance"], -d["bm25_score"]))
    summary = screening_summary(plan, len(candidates), included[:retmax], excluded)
    summary["matched_count"] = len(included)
    return included[:retmax], excluded, online, total, plan, summary


@app.get("/health")
async def health():
    online = False
    try:
        _, count = await esearch("metformin", retmax=1)
        online = count > 0
    except Exception:
        online = False
    return {
        "status": "ok",
        "pubmed_online": online,
        "model_loaded": model_available(),
        "corpus_size": len(load_corpus(CORPUS_FILE)),
    }


@app.post("/api/search")
async def search(q: Query):
    query = q.query.strip()
    if not query:
        raise HTTPException(status_code=400, detail="query 不能为空")
    docs, excluded, online, count, plan, screening = await _screened_retrieval(query, q.retmax)

    return {
        "query": query,
        "online": online,
        "total": count,
        "count": len(docs),
        "pico": plan["pico"],
        "screening": screening,
        "results": [_source(d) for d in docs],
        "excluded_results": [_source(d, False) for d in excluded],
    }


@app.post("/api/answer")
async def answer(q: Query):
    query = q.query.strip()
    if not query:
        raise HTTPException(status_code=400, detail="query 不能为空")
    docs, excluded, online, count, plan, screening = await _screened_retrieval(query, q.retmax)
    query_tokens = plan["ranking_tokens"]
    usable = [d for d in docs if d["answer_eligible"]][:8]
    mode = "extractive"
    sentences = None
    fallback_reason = None
    if LLM_API_KEY and usable:
        try:
            sentences = await llm_answer(query, usable)
            mode = "llm"
        except CitationValidationError:
            fallback_reason = "citation_validation_failed"
        except Exception:
            fallback_reason = "llm_unavailable"

    if sentences is None:
        sentences = extractive_answer(usable, query_tokens, query_plan=plan)
        mode = "extractive"
    answer_text = "\n\n".join(f"{s['sentence']} [PMID {s['pmid']}]" for s in sentences)
    if not answer_text:
        answer_text = ("问题中有尚不能可靠解析的条件，请使用明确的医学术语并说明比较对象。"
                       if plan["issues"] else "未找到同时满足查询条件且可摘录的相关证据；未放宽条件生成回答。")

    evidence = analyze_evidence(docs)

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
        "citation_validation": {
            "status": "passed" if mode == "llm" else "not_applicable",
            "scope": "context_membership_and_quote" if mode == "llm" else "source_excerpts",
            "content_entailment": "unassessed",
        },
        "llm_fallback_reason": fallback_reason,
        "pico": plan["pico"],
        "screening": screening,
        "evidence": evidence,
        "evidence_distribution": {k: dist.get(k, 0) for k in ["High", "Moderate", "Low", "Very low", "N/A"]},
        "results": [_source(d) for d in docs],
        "excluded_results": [_source(d, False) for d in excluded],
    }


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/")
async def index():
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))
