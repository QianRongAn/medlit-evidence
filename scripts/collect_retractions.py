"""撤稿文献数据采集器：抓取 PubMed 撤稿/存疑/更正文献，产出带标签数据集。

思路（可复现，零密钥）：
1. esearch 按 PublicationType 检索三类「问题文献」：撤稿、存疑、更正重发。
2. efetch 抓取题录：年份、期刊、研究类型、撤稿通知 PMID。
3. 用 elink 反向拿「撤稿通知」指向，记录撤稿耗时（发表年份 -> 撤稿通知年份）。
4. 同时按比例采「正常文献」作对照（负样本），构成可训练的二分类数据集。

产物：
- data/retraction_dataset.jsonl   逐篇标注（label: retracted/concern/corrected/ok + 元数据）
- data/retraction_profile.md      风险画像分析报告（年份/期刊/研究类型/耗时分布）

注意：遵守 E-utilities 频率限制（不并发，每次请求间有间隔）。
"""
import argparse
import json
import time
import urllib.parse
import urllib.request
from collections import Counter

PUBMED = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
PROXY = "http://127.0.0.1:7890"

opener = urllib.request.build_opener(
    urllib.request.ProxyHandler({"http": PROXY, "https": PROXY})
)


def _get(path, params, retries=3):
    url = f"{PUBMED}/{path}?{urllib.parse.urlencode(params)}"
    for i in range(retries):
        try:
            with opener.open(url, timeout=30) as r:
                return r.read()
        except Exception as e:
            if i == retries - 1:
                raise
            time.sleep(1.5 * (i + 1))


def esearch(term, retmax=50):
    data = _get("esearch.fcgi", {
        "db": "pubmed", "term": term, "retmax": retmax,
        "retmode": "json", "sort": "relevance",
    })
    res = json.loads(data)["esearchresult"]
    return res.get("idlist", []), int(res.get("count", "0") or 0)


def esearch_by_year(term, year_range, retmax=20):
    """按年份段分层采样，避免 relevance 排序只返回近期撤稿造成的耗时偏倚。"""
    return esearch(f"{term} AND {year_range}[dp]", retmax=retmax)


def efetch(pmids):
    import xml.etree.ElementTree as ET
    data = _get("efetch.fcgi", {"db": "pubmed", "id": ",".join(pmids), "retmode": "xml"})
    root = ET.fromstring(data)
    out = []
    for art in root.findall(".//PubmedArticle"):
        pmid = art.findtext(".//PMID")
        year = None
        pd = art.find(".//JournalIssue/PubDate")
        if pd is not None:
            y = pd.findtext("Year")
            if y:
                year = y
            else:
                md = pd.find("MedlineDate")
                if md is not None:
                    year = (md.text or "")[:4] or None
        pubtypes = [pt.text or "" for pt in art.findall(".//PublicationType") if pt.text]
        # 撤稿/存疑/更正的通知 PMID
        notice_pmid = None
        notice_year = None
        reftype = None
        for cc in art.findall(".//CommentsCorrectionsList/CommentsCorrections"):
            rt = cc.get("RefType", "")
            if rt in ("RetractionIn", "ExpressionOfConcernIn"):
                reftype = rt
                notice_pmid = cc.findtext("./PMID")
        out.append({
            "pmid": pmid,
            "title": (art.findtext(".//ArticleTitle") or "").strip(),
            "journal": (art.findtext(".//Journal/Title") or "").strip(),
            "year": year,
            "pubtypes": pubtypes,
            "notice_pmid": notice_pmid,
            "reftype": reftype,
        })
    return out


def notice_year(pmids):
    """批量拿撤稿通知的发表年份，用于算撤稿耗时。"""
    import xml.etree.ElementTree as ET
    pmids = [p for p in pmids if p]
    if not pmids:
        return {}
    data = _get("efetch.fcgi", {"db": "pubmed", "id": ",".join(pmids), "retmode": "xml"})
    root = ET.fromstring(data)
    out = {}
    for art in root.findall(".//PubmedArticle"):
        pmid = art.findtext(".//PMID")
        y = None
        pd = art.find(".//JournalIssue/PubDate")
        if pd is not None:
            y = pd.findtext("Year") or None
        out[pmid] = y
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--retracted", type=int, default=60, help="撤稿样本数")
    ap.add_argument("--concern", type=int, default=30, help="存疑样本数")
    ap.add_argument("--corrected", type=int, default=20, help="更正样本数")
    ap.add_argument("--control", type=int, default=60, help="正常对照样本数")
    ap.add_argument("--out", default="data/retraction_dataset.jsonl")
    args = ap.parse_args()

    rows = []

    def collect(term, label, n, year_ranges=None):
        """year_ranges 提供时按年份段分层采样，否则 relevance 采样。"""
        if year_ranges:
            per = max(1, n // len(year_ranges))
            for yr in year_ranges:
                pmids, _ = esearch_by_year(term, yr, retmax=per)
                _collect_pmids(pmids, label)
                time.sleep(1)
        else:
            pmids, _ = esearch(term, retmax=n)
            _collect_pmids(pmids, label)
            time.sleep(1)

    def _collect_pmids(pmids, label):
        docs = efetch(pmids)
        notices = [d["notice_pmid"] for d in docs]
        ny = notice_year(notices)
        for d in docs:
            rec = {
                "pmid": d["pmid"],
                "title": d["title"],
                "journal": d["journal"],
                "year": d["year"],
                "study_type_pt": d["pubtypes"],
                "label": label,
                "notice_pmid": d["notice_pmid"],
                "notice_year": ny.get(d["notice_pmid"]),
            }
            if d["year"] and rec["notice_year"]:
                rec["years_to_retraction"] = int(rec["notice_year"]) - int(d["year"])
            rows.append(rec)
        print(f"[{label}] 采集 {len(docs)} 篇")

    # 撤稿样本按年份段分层，覆盖早中近期，避免耗时偏倚
    collect("Retracted Publication[pt]", "retracted", args.retracted,
            year_ranges=["2000:2009", "2010:2014", "2015:2019", "2020:2026"])
    collect("Expression of Concern[pt]", "concern", args.concern)
    collect("Corrected and Republished Article[pt]", "corrected", args.corrected)

    # 对照组：随机正常文献
    control_ids, _ = esearch("hasabstract[text]", retmax=args.control)
    ctrl = efetch(control_ids)
    for d in ctrl:
        rows.append({
            "pmid": d["pmid"], "title": d["title"], "journal": d["journal"],
            "year": d["year"], "study_type_pt": d["pubtypes"],
            "label": "ok", "notice_pmid": None, "notice_year": None,
        })
    print(f"[control] 采集 {len(ctrl)} 篇")

    # 写出 JSONL
    import os
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"\n共 {len(rows)} 篇写入 {args.out}")

    # 简单画像
    labels = Counter(r["label"] for r in rows)
    print("\n标签分布:", dict(labels))
    ret = [r for r in rows if r["label"] == "retracted" and r.get("years_to_retraction") is not None]
    if ret:
        yrs = [r["years_to_retraction"] for r in ret]
        print(f"撤稿耗时（发表->撤稿）: 中位数 {sorted(yrs)[len(yrs)//2]} 年, 平均 {sum(yrs)/len(yrs):.1f} 年, 范围 {min(yrs)}~{max(yrs)}")


if __name__ == "__main__":
    main()
