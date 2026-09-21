"""答案合成：默认离线抽取式；配置 LLM 后升级为生成式（RAG）。"""
import re

import httpx

from .config import LLM_API_KEY, LLM_BASE_URL, LLM_MODEL
from .evidence import classify_polarity
from .study_type import GRADE_ORDER

SENT_SPLIT = re.compile(r"(?<=[.!?])\s+")

# 摘要里常见的小节标签；结果/结论类句子优先，背景/方法类降权
SECTION_LABELS = {
    "background", "objective", "objectives", "methods", "method", "results",
    "result", "conclusions", "conclusion", "findings", "introduction",
    "design", "interventions", "measurements", "participants", "outcomes",
    "limitations", "aim", "purpose", "settings", "setting", "context",
    "discussion", "registration", "main outcome", "main outcome measures",
}
CONCLUSION_LABELS = {"results", "result", "conclusions", "conclusion", "findings"}
WEAK_LABELS = {
    "background", "objective", "objectives", "methods", "method",
    "introduction", "design", "measurements", "participants", "aim", "purpose",
}


def _strip_label(s):
    m = re.match(r"^([A-Za-z][A-Za-z ]{1,24}):\s*(.{20,})$", s, re.S)
    if m:
        label_raw = m.group(1).strip().lower()
        body = m.group(2)
        # 多词标签（如 BACKGROUND AND AIMS）取首个已知词；全大写未知标签也剥掉
        if label_raw in SECTION_LABELS:
            return label_raw, body
        for w in label_raw.split():
            if w in SECTION_LABELS:
                return w, body
        if label_raw.upper() == m.group(1).strip() and 3 <= len(label_raw) <= 24:
            return "other", body
    return None, s


def _split_sentences(text):
    if not text:
        return []
    out = []
    for s in SENT_SPLIT.split(text):
        s = s.strip()
        if len(s) > 15:
            out.append(s)
    return out


def extractive_answer(docs, query_tokens, max_sentences=4):
    """按证据等级 + 关键词命中密度抽取关键句，附 PMID 引用。"""
    docs_sorted = sorted(docs, key=lambda d: GRADE_ORDER.get(d.get("grade", "N/A"), 4))

    scored = []
    for d in docs_sorted:
        text = d.get("abstract") or d.get("title") or ""
        for si, s in enumerate(_split_sentences(text)):
            label, body = _strip_label(s)
            sl = body.lower()
            hits = sum(1 for t in query_tokens if t in sl)
            if hits == 0:
                continue
            pos_bonus = 1.0 if si == 0 else 0.0
            grade_bonus = max(0.0, (4 - GRADE_ORDER.get(d.get("grade", "N/A"), 4)) * 0.4)
            section_bonus = 0.0
            if label in CONCLUSION_LABELS:
                section_bonus = 1.5
            elif label in WEAK_LABELS:
                section_bonus = -0.8
            score = hits * 2.0 + pos_bonus + grade_bonus + section_bonus
            scored.append((score, body, d))

    scored.sort(key=lambda x: -x[0])

    seen = set()
    picked = []
    for _, s, d in scored:
        key = s[:60].lower()
        if key in seen:
            continue
        seen.add(key)
        picked.append({
            "sentence": s,
            "pmid": d.get("pmid"),
            "title": d.get("title"),
            "polarity": classify_polarity(s),
        })
        if len(picked) >= max_sentences:
            break
    return picked


def _build_context(docs, max_docs=6, max_chars=4000):
    parts = []
    for d in docs[:max_docs]:
        ab = (d.get("abstract") or "").strip().replace("\n", " ")
        if len(ab) > 600:
            ab = ab[:600] + "..."
        parts.append(f"[PMID {d.get('pmid')}] {d.get('title')}\n{ab}")
    ctx = "\n\n".join(parts)
    return ctx[:max_chars]


async def llm_answer(query, docs):
    """调用 OpenAI 兼容接口做生成式回答。"""
    context = _build_context(docs)
    system = (
        "你是一名循证医学助手。基于提供的文献生成中文回答，"
        "必须引用来源（用 [PMID xxxxx] 标注），不得编造未在文献中出现的数据，"
        "证据不足时明确说明。"
    )
    user = f"问题：{query}\n\n文献：\n{context}\n\n请给出结论、关键证据、以及证据强度说明。"
    payload = {
        "model": LLM_MODEL,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": 0.3,
    }
    headers = {"Authorization": f"Bearer {LLM_API_KEY}"}
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.post(
            f"{LLM_BASE_URL.rstrip('/')}/chat/completions",
            json=payload,
            headers=headers,
        )
        r.raise_for_status()
        data = r.json()
        return data["choices"][0]["message"]["content"]
