"""构建撤稿风险预标注 demo 库（5 万篇近 5 年肿瘤/免疫文献）。

流程：
1. esearch 拉 5 万篇 neoplasms[mesh] 近 5 年 PMID（按年份分层采样保证年份均匀）
2. efetch 抓元数据（标题/摘要/作者数/机构数/资助数/参考文献数/语言/年份）
3. 用训练好的 LightGBM 模型逐篇跑撤稿风险分
4. 入库 SQLite，可检索

输出：
- data/demo_pmids.json        选中的 5 万 PMID
- data/demo_corpus.jsonl      元数据
- data/demo_features.csv      特征
- data/demo_risk.db           SQLite 库（含 risk 分数）
- data/demo_report.md         实测抓取速率 + 存储 + 成本反推
"""
import json
import os
import sqlite3
import sys
import time
import xml.etree.ElementTree as ET

import httpx
import joblib
import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
from build_features import build as build_features  # noqa: E402

BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
PROXY = os.environ.get("PUBMED_PROXY", "") or None

N_TARGET = 50000
YEARS = list(range(2020, 2026))  # 2020-2025
TERM_TMPL = 'neoplasms[mesh] AND ("{y}/01/01"[pdat] : "{y}/12/31"[pdat])'

DATA = os.path.join(ROOT, "data")
DEMO_PMIDS = os.path.join(DATA, "demo_pmids.json")
DEMO_CORPUS = os.path.join(DATA, "demo_corpus.jsonl")
DEMO_FEATURES = os.path.join(DATA, "demo_features.csv")
DEMO_DB = os.path.join(DATA, "demo_risk.db")
DEMO_REPORT = os.path.join(DATA, "demo_report.md")

MODEL_DIR = os.path.join(ROOT, "models")


def esearch_pmids(term, want):
    """esearch 拉 PMID，retmax 上限 9999，按 want 截断。"""
    for a in range(4):
        try:
            r = httpx.get(f"{BASE}/esearch.fcgi",
                          params={"db": "pubmed", "term": term,
                                  "retmax": str(min(want, 9999)), "retmode": "json"},
                          timeout=60, proxy=None, trust_env=False)
            ids = r.json()["esearchresult"]["idlist"]
            return ids[:want]
        except Exception as e:
            print(f"  ! esearch 失败: {e}")
            time.sleep(2 * (a + 1))
    return []


def _find_text(el, path):
    node = el.find(path)
    return "".join(node.itertext()).strip() if node is not None else ""


def parse_article(art):
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

    affiliations = set()
    for aff in art.findall(".//AffiliationInfo/Affiliation"):
        t = "".join(aff.itertext()).strip()
        if t:
            affiliations.add(t.lower())
    for aff in art.findall(".//Author/Affiliation"):
        t = "".join(aff.itertext()).strip()
        if t:
            affiliations.add(t.lower())

    return {
        "pmid": pmid,
        "title": _find_text(art, ".//ArticleTitle"),
        "abstract": "\n".join(abstract_parts),
        "journal": _find_text(art, ".//Journal/Title"),
        "year": year,
        "n_authors": len(art.findall(".//AuthorList/Author")),
        "n_affiliations": len(affiliations),
        "n_grants": len(art.findall(".//GrantList/Grant")),
        "n_references": len(art.findall(".//ReferenceList/Reference")),
        "language": _find_text(art, ".//Language"),
        "pubtypes": [_find_text(pt, ".") for pt in art.findall(".//PublicationType")],
    }


def efetch(pmids):
    url = f"{BASE}/efetch.fcgi"
    params = {"db": "pubmed", "id": ",".join(pmids), "retmode": "xml"}
    for a in range(4):
        try:
            r = httpx.get(url, params=params, timeout=90, proxy=None, trust_env=False)
            r.raise_for_status()
            root = ET.fromstring(r.content)
            return [parse_article(x) for x in root.findall(".//PubmedArticle")]
        except Exception as e:
            time.sleep(2 * (a + 1))
    return []


def step_collect_pmids():
    if os.path.exists(DEMO_PMIDS):
        pmids = json.load(open(DEMO_PMIDS, encoding="utf-8"))
        print(f"断点续传：已有 {len(pmids)} PMID")
        return pmids
    per_year = N_TARGET // len(YEARS)
    got = []
    for y in YEARS:
        ids = esearch_pmids(TERM_TMPL.format(y=y), per_year + 100)
        got.extend(ids)
        print(f"  {y} 年：拉取 {len(ids)}")
        time.sleep(0.4)
    got = list(dict.fromkeys(got))[:N_TARGET]
    json.dump(got, open(DEMO_PMIDS, "w", encoding="utf-8"), ensure_ascii=False)
    print(f"共选中 {len(got)} PMID")
    return got


def step_fetch_corpus(pmids):
    got = {}
    if os.path.exists(DEMO_CORPUS):
        for l in open(DEMO_CORPUS, encoding="utf-8"):
            d = json.loads(l)
            got[d["pmid"]] = d
    todo = [p for p in pmids if p not in got]
    print(f"待抓元数据 {len(todo)} 篇")
    t0 = time.time()
    for i in range(0, len(todo), 100):
        batch = todo[i:i + 100]
        docs = efetch(batch)
        for d in docs:
            got[d["pmid"]] = d
        if (i + 100) % 500 == 0 or i + 100 >= len(todo):
            # 增量写盘（每 500 篇落一次，被杀最多白抓 500 篇）
            tmp = DEMO_CORPUS + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                for p in pmids:
                    if p in got:
                        f.write(json.dumps(got[p], ensure_ascii=False) + "\n")
            os.replace(tmp, DEMO_CORPUS)
            el = time.time() - t0
            rate = (i + 100) / el
            print(f"  进度 {min(i + 100, len(todo))}/{len(todo)}，"
                  f"速率 {rate:.1f} 篇/秒，累计 {len(got)}", flush=True)
        time.sleep(0.3)
    return got


def step_build_features(corpus):
    rows = []
    for d in corpus.values():
        rows.append({"pmid": d["pmid"], "title": d.get("title") or "",
                     "abstract": d.get("abstract") or "", "year": d.get("year"),
                     "n_authors": d.get("n_authors"), "n_affiliations": d.get("n_affiliations"),
                     "n_grants": d.get("n_grants"), "n_references": d.get("n_references"),
                     "language": d.get("language")})
    df = pd.DataFrame(rows)
    return df


def step_score_and_store(df):
    lgb = joblib.load(os.path.join(MODEL_DIR, "lgb.joblib"))
    scaler = joblib.load(os.path.join(MODEL_DIR, "scaler.joblib"))

    from build_features import (CERTAINTY, DESIGN_RULES, EXAGGERATION, HEDGE,
                                STAT_TERMS, design_flags, count_words)
    FEATURE_COLS = [
        "title_len", "abstract_len", "n_sentences", "avg_sentence_len",
        "n_authors", "n_affiliations", "n_grants", "n_references",
        "is_english", "year", "n_exaggeration", "n_certainty", "n_hedge",
        "n_stats", "digits_per_1000", "single_author",
        "design_meta", "design_rct", "design_case_report", "design_cohort",
        "design_basic", "design_review",
    ]
    import re
    recs = []
    for _, r in df.iterrows():
        title = r["title"] or ""
        abstract = r["abstract"] or ""
        text = f"{title}\n{abstract}"
        n_sent = len(re.findall(r"[.!?]", abstract))
        n_digits = sum(c.isdigit() for c in abstract)
        rec = {
            "pmid": r["pmid"], "title": title, "abstract": abstract,
            "year": int(r["year"]) if str(r["year"]).isdigit() else 0,
            "title_len": len(title), "abstract_len": len(abstract),
            "n_sentences": n_sent,
            "avg_sentence_len": round(len(abstract) / max(n_sent, 1), 1),
            "n_authors": r["n_authors"] or 0, "n_affiliations": r["n_affiliations"] or 0,
            "n_grants": r["n_grants"] or 0, "n_references": r["n_references"] or 0,
            "is_english": 1 if (r["language"] or "").lower() == "eng" else 0,
            "n_exaggeration": count_words(text, EXAGGERATION),
            "n_certainty": count_words(text, CERTAINTY),
            "n_hedge": count_words(text, HEDGE),
            "n_stats": count_words(text, STAT_TERMS),
            "digits_per_1000": round(n_digits * 1000 / max(len(abstract), 1), 1),
            "single_author": 1 if (r["n_authors"] or 0) == 1 else 0,
        }
        rec.update(design_flags(text))
        recs.append(rec)

    fdf = pd.DataFrame(recs)
    fdf.to_csv(DEMO_FEATURES, index=False)

    X = fdf[FEATURE_COLS].values.astype(float)
    Xs = scaler.transform(X)
    proba = lgb.predict_proba(Xs)[:, 1]

    fdf["risk_score"] = proba
    return fdf


def store_sqlite(fdf):
    if os.path.exists(DEMO_DB):
        os.remove(DEMO_DB)
    con = sqlite3.connect(DEMO_DB)
    fdf.to_sql("articles", con, if_exists="replace", index=False)
    con.execute("CREATE INDEX idx_risk ON articles(risk_score)")
    con.execute("CREATE INDEX idx_year ON articles(year)")
    con.execute("CREATE INDEX idx_pmid ON articles(pmid)")
    con.commit()
    n = con.execute("SELECT COUNT(*) FROM articles").fetchone()[0]
    con.close()
    print(f"SQLite 入库 {n} 篇 -> {DEMO_DB}")


def write_report(fdf, fetch_elapsed, fetch_n):
    n = len(fdf)
    db_size = os.path.getsize(DEMO_DB) / 1e6
    corpus_size = os.path.getsize(DEMO_CORPUS) / 1e6
    rate = fetch_n / max(fetch_elapsed, 1)
    lines = [
        "# 撤稿风险预标注 demo 库 · 实测报告\n",
        f"样本：{n} 篇近 5 年（2020-2025）肿瘤（neoplasms[mesh]）文献。\n",
        "## 实测指标\n",
        f"- 抓取速率：**{rate:.1f} 篇/秒**（eutils 直连，无 API key）",
        f"- 元数据存储：{corpus_size:.1f} MB",
        f"- 特征表：{os.path.getsize(DEMO_FEATURES)/1e6:.2f} MB",
        f"- SQLite 库：{db_size:.1f} MB",
        "",
        "## 全量成本反推（3700 万条）\n",
        f"- 抓取耗时：3700 万 ÷ {rate:.0f} 篇/秒 ≈ **{37000000/rate/3600:.0f} 小时**"
        f"（eutils 单线程；用官方 FTP 快照可压缩到数小时）",
        f"- 元数据存储：3700 万 × {corpus_size/n*1e6:.0f} B/篇 ≈ {corpus_size/n*37:.1f} GB",
        f"- SQLite 库：3700 万 × {db_size/n*1e6:.0f} B/篇 ≈ {db_size/n*37:.1f} GB",
        "",
        "## 风险分分布\n",
        f"- 均值 {fdf['risk_score'].mean():.3f}，中位数 {fdf['risk_score'].median():.3f}",
        f"- P90 {fdf['risk_score'].quantile(0.9):.3f}，P99 {fdf['risk_score'].quantile(0.99):.3f}",
        f"- 高风险（>0.7）{int((fdf['risk_score']>0.7).sum())} 篇，"
        f"低风险（<0.3）{int((fdf['risk_score']<0.3).sum())} 篇",
        "",
        "## 高风险 Top 10\n",
        "| 排名 | PMID | 风险分 | 标题 |",
        "| --- | --- | --- | --- |",
    ]
    top = fdf.sort_values("risk_score", ascending=False).head(10)
    for i, (_, r) in enumerate(top.iterrows(), 1):
        t = (r["title"] or "")[:60]
        lines.append(f"| {i} | {r['pmid']} | {r['risk_score']:.3f} | {t} |")
    lines.append("")
    lines.append("## 说明\n")
    lines.append("风险分是「撤稿风险的排序辅助」，不代表该文献真的会撤稿。")
    lines.append("模型基于摘要写作特征（LightGBM），非全文图像/数据核查，仅用于辅助人工审查。\n")
    with open(DEMO_REPORT, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"报告已写入 {DEMO_REPORT}")


def main():
    print("=== ① 采集 PMID ===")
    pmids = step_collect_pmids()

    print("=== ② 抓元数据 ===")
    t0 = time.time()
    corpus = step_fetch_corpus(pmids)
    fetch_elapsed = time.time() - t0
    fetch_n = len(corpus)

    print("=== ③ 构建特征 ===")
    df = step_build_features(corpus)

    print("=== ④ 跑风险分 ===")
    fdf = step_score_and_store(df)

    print("=== ⑤ 入库 SQLite ===")
    store_sqlite(fdf)

    print("=== ⑥ 写报告 ===")
    write_report(fdf, fetch_elapsed, fetch_n)


if __name__ == "__main__":
    main()
