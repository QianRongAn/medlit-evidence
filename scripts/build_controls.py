"""为撤稿/存疑正样本做 matched control 对照采样。

背景：原数据集对照组的 76 篇"正常"论文里混有大量 Editorial / News / Erratum，
这些不是研究论文、本来就不会因数据造假被撤稿，直接当负样本会造成对照偏倚，
模型只会学到"社论 ≠ 研究论文"，而不是"哪种研究描述容易翻车"。

做法（文献计量学撤稿研究的黄金标准 matched control）：
给每篇正样本配一篇「同期 + 同刊」的正常研究论文作对照，排除一切标签性
PublicationType（Retracted / Concern / Erratum / Editorial / News / Letter / Comment）。
同刊同年无候选时逐级放宽：同刊不限年 -> 同设计类型跨期刊。

只做检索式采样，不写入任何标签信息，保证对照的"正常"状态独立于撤稿结果。
"""
import json
import os
import sys
import time

import httpx

BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
PROXY = os.environ.get("PUBMED_PROXY", "http://127.0.0.1:7890")
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

SRC = os.path.join(ROOT, "data", "retraction_dataset.jsonl")
OUT = os.path.join(ROOT, "data", "matched_controls.json")

# 正样本设计类型：从 PublicationType 里抽取"研究设计"词（白名单，非标签）
DESIGN_ORDER = [
    "Meta-Analysis", "Systematic Review", "Randomized Controlled Trial",
    "Clinical Trial", "Review", "Case Reports", "Comparative Study",
    "Observational Study", "Multicenter Study",
]

# 排除的标签性 / 非研究论文类型
EXCLUDE_PTS = (
    "retracted publication", "expression of concern",
    "corrected and republished article", "published erratum",
    "retraction of publication", "editorial", "news", "letter",
    "comment", "biography", "interview", "case reports", "portrait",
)


def extract_design(pts):
    """从 PublicationType 列表里挑出研究设计词（忽略撤稿/更正等标签）。"""
    lower = {p.lower() for p in pts}
    for d in DESIGN_ORDER:
        if d.lower() in lower:
            return d
    return None


def build_term(journal, year, design=None):
    """构造排除标签类型的检索式。"""
    nots = " OR ".join(f'"{p}"[pt]' for p in EXCLUDE_PTS)
    if journal and year:
        return f'"{journal}"[Journal] AND "{year}"[dp] NOT ({nots})'
    if journal:
        return f'"{journal}"[Journal] NOT ({nots})'
    if design and year:
        return f'"{design}"[pt] AND "{year}"[dp] NOT ({nots})'
    return None


def esearch(term, retmax=30):
    params = {
        "db": "pubmed", "term": term, "retmax": str(retmax),
        "retmode": "json", "sort": "date",
    }
    last = None
    for attempt in range(3):
        try:
            with httpx.Client(timeout=30, proxy=PROXY) as c:
                r = c.get(f"{BASE}/esearch.fcgi", params=params)
                r.raise_for_status()
                return r.json().get("esearchresult", {}).get("idlist", [])
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(1.5 * (attempt + 1))
    print(f"  ! esearch 失败: {last}", file=sys.stderr)
    return []


def main():
    rows = [json.loads(l) for l in open(SRC, encoding="utf-8")]
    pos = [r for r in rows if r["label"] in ("retracted", "concern")]
    pos_pmids = {r["pmid"] for r in rows}

    mapping = {}
    if os.path.exists(OUT):
        mapping = json.load(open(OUT, encoding="utf-8"))

    used_controls = set(mapping.values())
    done = 0
    fallback_stats = {"same_journal_year": 0, "same_journal": 0, "same_design_year": 0, "failed": 0}

    for i, r in enumerate(pos, 1):
        pmid = r["pmid"]
        if pmid in mapping and mapping[pmid]:
            done += 1
            continue
        journal = r.get("journal", "")
        year = r.get("year", "")
        design = extract_design(r.get("study_type_pt", []))
        time.sleep(0.4)

        chosen = None
        # 1) 同刊同年
        cands = [p for p in esearch(build_term(journal, year, design))
                 if p not in pos_pmids and p not in used_controls]
        if cands:
            chosen = cands[0]
            fallback_stats["same_journal_year"] += 1
        else:
            # 2) 同刊不限年
            cands = [p for p in esearch(build_term(journal, None, design))
                     if p not in pos_pmids and p not in used_controls]
            if cands:
                chosen = cands[0]
                fallback_stats["same_journal"] += 1
            elif design:
                # 3) 同设计类型跨期刊
                cands = [p for p in esearch(build_term(None, year, design))
                         if p not in pos_pmids and p not in used_controls]
                if cands:
                    chosen = cands[0]
                    fallback_stats["same_design_year"] += 1

        if chosen:
            mapping[pmid] = chosen
            used_controls.add(chosen)
            done += 1
        else:
            fallback_stats["failed"] += 1
            print(f"  [{i}/{len(pos)}] 未匹配: {pmid} {journal} {year}")

        if i % 20 == 0:
            json.dump(mapping, open(OUT, "w", encoding="utf-8"), indent=1)
            print(f"  进度 {i}/{len(pos)}，已匹配 {done}（断点已保存）")

    json.dump(mapping, open(OUT, "w", encoding="utf-8"), indent=1)
    print(f"\n完成：正样本 {len(pos)}，成功匹配 {done}，映射已写入 {OUT}")
    print("匹配层级统计:", fallback_stats)


if __name__ == "__main__":
    main()
