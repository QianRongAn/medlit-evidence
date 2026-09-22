"""抓取正样本 + 对照的全量元数据，作为撤稿风险预测模型的特征地基。

输入：data/retraction_dataset.jsonl（180 正样本）+ data/matched_controls.json（180 对照）
输出：data/corpus_raw.jsonl，每篇含摘要、全部作者数、机构数、资助数、参考文献数、语言。

关键：这里只抓"发表时点可得"的题录信息，不抓撤稿公告/被引次数等"事后"信息，
避免后续建模时发生标签泄漏。
"""
import json
import os
import re
import sys
import time
import xml.etree.ElementTree as ET

import httpx

BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
PROXY = os.environ.get("PUBMED_PROXY", "http://127.0.0.1:7890")
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

SRC = os.path.join(ROOT, "data", "retraction_dataset.jsonl")
CTRL = os.path.join(ROOT, "data", "matched_controls.json")
OUT = os.path.join(ROOT, "data", "corpus_raw.jsonl")


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

    authors = art.findall(".//AuthorList/Author")
    n_authors = len(authors)

    affiliations = set()
    for aff in art.findall(".//AffiliationInfo/Affiliation"):
        t = "".join(aff.itertext()).strip()
        if t:
            affiliations.add(t.lower())
    for aff in art.findall(".//Author/Affiliation"):
        t = "".join(aff.itertext()).strip()
        if t:
            affiliations.add(t.lower())

    n_grants = len(art.findall(".//GrantList/Grant"))
    n_references = len(art.findall(".//ReferenceList/Reference"))
    language = _find_text(art, ".//Language")

    pubtypes = [ _find_text(pt, ".") for pt in art.findall(".//PublicationType") ]

    return {
        "pmid": pmid,
        "title": _find_text(art, ".//ArticleTitle"),
        "abstract": "\n".join(abstract_parts),
        "journal": _find_text(art, ".//Journal/Title"),
        "year": year,
        "n_authors": n_authors,
        "n_affiliations": len(affiliations),
        "n_grants": n_grants,
        "n_references": n_references,
        "language": language,
        "pubtypes": pubtypes,
    }


def efetch(pmids):
    url = f"{BASE}/efetch.fcgi"
    params = {"db": "pubmed", "id": ",".join(pmids), "retmode": "xml"}
    last = None
    for attempt in range(4):
        try:
            with httpx.Client(timeout=60, proxy=PROXY) as c:
                r = c.get(url, params=params)
                r.raise_for_status()
                root = ET.fromstring(r.content)
                return [parse_article(a) for a in root.findall(".//PubmedArticle")]
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(2 * (attempt + 1))
    print(f"  ! efetch 失败 {len(pmids)} 篇: {last}", file=sys.stderr)
    return []


def main():
    rows = [json.loads(l) for l in open(SRC, encoding="utf-8")]
    controls = json.load(open(CTRL, encoding="utf-8"))

    pos = {r["pmid"]: r["label"] for r in rows if r["label"] in ("retracted", "concern")}
    ctrl_pmids = list(controls.values())

    targets = []  # (pmid, label)
    for pmid, lab in pos.items():
        targets.append((pmid, lab))
    for pmid in ctrl_pmids:
        targets.append((pmid, "control"))

    label_of = {pmid: lab for pmid, lab in targets}
    all_pmids = list(label_of.keys())

    # 断点续传：已有结果不再重复抓
    got = {}
    if os.path.exists(OUT):
        for l in open(OUT, encoding="utf-8"):
            d = json.loads(l)
            got[d["pmid"]] = d
    todo = [p for p in all_pmids if p not in got]
    print(f"待抓取 {len(all_pmids)} 篇（正样本 {len(pos)} + 对照 {len(ctrl_pmids)}），已完成 {len(got)}，剩余 {len(todo)}")

    for i in range(0, len(todo), 100):
        batch = todo[i:i + 100]
        docs = efetch(batch)
        for d in docs:
            got[d["pmid"]] = d
        print(f"  剩余批次 {min(i + 100, len(todo))}/{len(todo)}，累计命中 {len(got)}")
        time.sleep(0.5)

    missing = [p for p in all_pmids if p not in got]
    print(f"命中 {len(got)}/{len(all_pmids)}，缺失 {len(missing)}")

    with open(OUT, "w", encoding="utf-8") as f:
        n = 0
        for pmid, lab in targets:
            d = got.get(pmid)
            if not d:
                continue
            d["label"] = 1 if lab in ("retracted", "concern") else 0
            d["label_name"] = lab
            f.write(json.dumps(d, ensure_ascii=False) + "\n")
            n += 1
    print(f"已写入 {n} 篇到 {OUT}")


if __name__ == "__main__":
    main()
