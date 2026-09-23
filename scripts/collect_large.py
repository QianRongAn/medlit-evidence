"""采集 3 万训练样本：正样本 1.5 万（撤稿+存疑）+ 负样本 1.5 万（按年份分层匹配的正常论文）。

负样本匹配策略（3 万规模的务实做法）：
- 与 360 管线的"同刊同年"不同，这里改用"按年份分层"匹配，因为逐篇同刊
  esearch 1.5 万次成本过高；年份是撤稿研究里最强的混杂变量，按年份对齐即可
  控制时间偏倚，期刊与研究设计作为特征交给模型自己学。
- 负样本只排除纯非研究类型（社论/新闻/信件/评论/传记/访谈/肖像）与标签性
  PublicationType（撤稿/存疑/更正/勘误），保留病例报告、综述、RCT 等真实
  研究论文，避免"病例报告=翻车"这类假关联。
"""
import json
import os
import random
import time

import httpx

BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
# PubMed 直连稳定（走代理 efetch 会 SSL EOF）；设 PUBMED_PROXY=off 或空则直连
PROXY = os.environ.get("PUBMED_PROXY", "") or None
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OUT = os.path.join(ROOT, "data", "large_targets.json")

POS_RETRACTED = 12000
POS_CONCERN = 3000
NEG_TOTAL = 15000

EXCLUDE_NEG = (
    "retracted publication", "expression of concern",
    "corrected and republished article", "published erratum",
    "retraction of publication", "editorial", "news", "letter",
    "comment", "biography", "interview", "portrait",
)


def esearch_all(term, want):
    """分页 esearch，拉够 want 个 PMID。注意 PubMed retmax 上限 10000，
    实际一次最多返回约 9999 条，必须用 retstart 翻页。"""
    got = []
    retstart = 0
    while len(got) < want:
        params = {
            "db": "pubmed", "term": term, "retmax": "10000",
            "retstart": str(retstart), "retmode": "json",
        }
        for attempt in range(4):
            try:
                with httpx.Client(timeout=30, proxy=PROXY) as c:
                    r = c.get(f"{BASE}/esearch.fcgi", params=params)
                    r.raise_for_status()
                    ids = r.json().get("esearchresult", {}).get("idlist", [])
                    if not ids:
                        return got
                    got.extend(ids)
                    retstart += len(ids)
                    break
            except Exception:
                time.sleep(2 * (attempt + 1))
        else:
            print(f"  ! esearch 连续 4 次失败，term={term[:30]}，已得 {len(got)}")
            break
        time.sleep(0.4)
    return got[:want]


def esearch_year(year, want):
    nots = " OR ".join(f'"{p}"[pt]' for p in EXCLUDE_NEG)
    term = f'"{year}"[dp] NOT ({nots})'
    return esearch_all(term, want)


# 断点续传的中间产物路径
CKPT_POS = os.path.join(ROOT, "data", "large_pos_pmids.json")
CKPT_YEARS = os.path.join(ROOT, "data", "large_pos_years.json")
CKPT_NEG = os.path.join(ROOT, "data", "large_neg_pmids.json")


def _load_json(path, default):
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return default


def _save_json(path, obj):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False)
    os.replace(tmp, path)


def main():
    random.seed(42)

    # ① 正样本 PMID（断点：已有则跳过 esearch）
    pos_pmids = _load_json(CKPT_POS, None)
    if pos_pmids is None:
        pos_retracted = esearch_all("retracted publication[pt]", POS_RETRACTED)
        pos_concern = esearch_all("expression of concern[pt]", POS_CONCERN)
        pos_pmids = list(dict.fromkeys(pos_retracted + pos_concern))  # 去重
        _save_json(CKPT_POS, pos_pmids)
        print(f"正样本 PMID：撤稿 {len(pos_retracted)} + 存疑 {len(pos_concern)} = {len(pos_pmids)}（去重后）")
    else:
        print(f"断点续传：正样本 PMID 已有 {len(pos_pmids)} 个，跳过 esearch")

    # ② 正样本年份（断点：已有年份的 PMID 不再 efetch）
    def efetch_years(pmids):
        out = _load_json(CKPT_YEARS, {})
        todo = [p for p in pmids if p not in out]
        print(f"  正样本年份：已有 {len(out)}，待抓 {len(todo)}")
        for i in range(0, len(todo), 100):
            batch = todo[i:i + 100]
            for attempt in range(4):
                try:
                    with httpx.Client(timeout=60, proxy=PROXY) as c:
                        r = c.get(f"{BASE}/efetch.fcgi",
                                  params={"db": "pubmed", "id": ",".join(batch), "retmode": "xml"})
                        r.raise_for_status()
                        import xml.etree.ElementTree as ET
                        root = ET.fromstring(r.content)
                        for art in root.findall(".//PubmedArticle"):
                            pmid = "".join(art.find(".//PMID").itertext()).strip()
                            y = art.find(".//JournalIssue/PubDate/Year")
                            year = y.text[:4] if y is not None and y.text else None
                            if year:
                                out[pmid] = year
                        break
                except Exception:
                    time.sleep(2 * (attempt + 1))
            if i % 500 == 0:
                _save_json(CKPT_YEARS, out)  # 每 500 批落一次盘
                print(f"  正样本年份进度 {min(i + 100, len(todo))}/{len(todo)}（累计 {len(out)}）")
            time.sleep(0.3)
        _save_json(CKPT_YEARS, out)
        return out

    pos_years = efetch_years(pos_pmids)
    from collections import Counter
    dist = Counter(pos_years.values())
    print(f"正样本年份分布（前 10）:", sorted(dist.items(), key=lambda t: -t[1])[:10])

    # ③ 负样本按年份分层采样（断点：已有负样本的年份跳过）
    neg_pmids = _load_json(CKPT_NEG, [])
    used = set(pos_pmids) | set(neg_pmids)
    if neg_pmids:
        print(f"断点续传：负样本 PMID 已有 {len(neg_pmids)} 个，继续补足")
    for year, cnt in sorted(dist.items(), key=lambda t: -t[1]):
        if not year or not year.isdigit():
            continue
        if len(neg_pmids) >= NEG_TOTAL:
            break
        want = max(1, round(NEG_TOTAL * cnt / sum(dist.values())))
        cands = [p for p in esearch_year(year, want * 3) if p not in used and p not in neg_pmids]
        if cands:
            neg_pmids.extend(cands[:want])
            used.update(cands[:want])
            _save_json(CKPT_NEG, neg_pmids)
        else:
            print(f"  {year} 年无候选正常论文")
        time.sleep(0.3)
    neg_pmids = neg_pmids[:NEG_TOTAL]
    _save_json(CKPT_NEG, neg_pmids)
    print(f"负样本 PMID：{len(neg_pmids)}")

    targets = [{"pmid": p, "label": 1, "label_name": "flipped"} for p in pos_pmids]
    targets += [{"pmid": p, "label": 0, "label_name": "control"} for p in neg_pmids]

    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(targets, f, ensure_ascii=False)
    print(f"目标清单已写入 {OUT}：总 {len(targets)}（正 {len(pos_pmids)} + 负 {len(neg_pmids)}）")


if __name__ == "__main__":
    main()
