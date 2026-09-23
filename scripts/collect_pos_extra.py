"""增量补存疑(expression of concern)正样本到 3000，正样本总目标 1.5 万。

现状：large_pos_pmids.json 已有 12978（12000 撤稿 + 978 存疑）。
本脚本：
1. esearch "expression of concern[pt]" 拉满 3000 个存疑 PMID
2. 与现有正样本去重，算出还缺多少
3. 追加到 large_pos_pmids.json（保留原 12000 撤稿）
4. 补抓这些新 PMID 的年份，合并进 large_pos_years.json

输出：data/large_pos_pmids.json 更新为 15000，large_pos_years.json 同步。
"""
import json
import os
import time
import xml.etree.ElementTree as ET

import httpx

BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
PROXY = os.environ.get("PUBMED_PROXY", "") or None
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
CKPT_POS = os.path.join(ROOT, "data", "large_pos_pmids.json")
CKPT_YEARS = os.path.join(ROOT, "data", "large_pos_years.json")

POS_RETRACTED = 12000
POS_CONCERN = 3000
TARGET_POS = POS_RETRACTED + POS_CONCERN  # 15000


def esearch_all(term, want):
    got = []
    params = {"db": "pubmed", "term": term, "retmax": str(min(want, 9999)),
              "retstart": "0", "retmode": "json"}
    for attempt in range(4):
        try:
            with httpx.Client(timeout=30, proxy=PROXY, trust_env=False) as c:
                r = c.get(f"{BASE}/esearch.fcgi", params=params)
                r.raise_for_status()
                got = r.json().get("esearchresult", {}).get("idlist", [])
                break
        except Exception as e:
            print(f"  ! esearch 尝试 {attempt + 1} 失败: {e}")
            time.sleep(2 * (attempt + 1))
    return got[:want]


def _load(path, default):
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return default


def _save(path, obj):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False)
    os.replace(tmp, path)


def efetch_years(pmids, existing):
    out = dict(existing)
    todo = [p for p in pmids if p not in out]
    print(f"  补年份：已有 {len(out)}，待抓 {len(todo)}")
    for i in range(0, len(todo), 100):
        batch = todo[i:i + 100]
        for attempt in range(4):
            try:
                with httpx.Client(timeout=60, proxy=PROXY) as c:
                    r = c.get(f"{BASE}/efetch.fcgi",
                              params={"db": "pubmed", "id": ",".join(batch), "retmode": "xml"})
                    r.raise_for_status()
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
            _save(CKPT_YEARS, out)
            print(f"  年份进度 {min(i + 100, len(todo))}/{len(todo)}（累计 {len(out)}）")
        time.sleep(0.3)
    _save(CKPT_YEARS, out)
    return out


def main():
    existing_pos = _load(CKPT_POS, [])
    print(f"现有正样本 PMID：{len(existing_pos)}")

    # 拉满 3000 存疑
    concern_all = esearch_all("expression of concern[pt]", POS_CONCERN)
    print(f"存疑 esearch 得 {len(concern_all)}")

    existing_set = set(existing_pos)
    new_concern = [p for p in concern_all if p not in existing_set]
    print(f"新增存疑 {len(new_concern)}")

    merged = existing_pos + new_concern
    # 去重保序
    merged = list(dict.fromkeys(merged))
    _save(CKPT_POS, merged)
    print(f"合并后正样本 PMID：{len(merged)}（目标 {TARGET_POS}）")

    # 补年份
    existing_years = _load(CKPT_YEARS, {})
    years = efetch_years(merged, existing_years)
    print(f"年份字典：{len(years)}")

    # 校验
    missing_year = [p for p in merged if p not in years]
    print(f"仍缺年份的 PMID：{len(missing_year)}")


if __name__ == "__main__":
    main()
