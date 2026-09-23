#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""本机采集 OpenAlex 引文信号（零依赖，Python 标准库即可跑）。

为什么放本机跑：沙箱环境访问 api.openalex.org 又慢又不稳（直连 4.6s/篇、
代理被 RST、并发超时），而你本机能正常打开 openalex.org，直连快很多。

用法（本机任意目录，一条命令）：
    python collect_signals_local.py

它会：
1. 读同目录的 all_pmids_for_signals.txt（每行一个 PMID）
2. 用 OpenAlex 批量查询（每批 50 个 PMID），带 mailto 礼貌池 + 自动重试
3. 断点续传到 integrity_signals.jsonl（跑一半断了再跑会接着来）
4. 进度条实时显示

跑完把 integrity_signals.jsonl 发回即可。

依赖：仅 Python 标准库（urllib / json），无需 pip install。
"""
import json
import os
import sys
import time
import urllib.parse
import urllib.error
import urllib.request

PMID_FILE = "all_pmids_for_signals.txt"
OUT_FILE = "integrity_signals.jsonl"
MAILTO = os.environ.get("OPENALEX_MAILTO", "").strip()
# 从环境变量 OPENALEX_API_KEY 读 key（优先），也可用命令行第 1 个参数传。
# key 绝不写进代码/仓库，避免泄露。
API_KEY = os.environ.get("OPENALEX_API_KEY", "").strip()
if len(sys.argv) > 1:
    API_KEY = sys.argv[1].strip()
BATCH = 50  # OpenAlex filter 一次最多 50 个 OR 条件
# 2026-02 起 OpenAlex 要求所有请求带 key；免费 key 每天 $1 额度，
# list/filter 类请求 $0.0001/次，即每天可免费查约 1 万次。
# 批量 50 篇/次 → 7.8 万篇约 1560 次请求，远低于免费额度。


def api_get(url, retries=8):
    """带重试的 GET。优先直连；遇 429 自动退避重试。"""
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": "medlit-signals/1.0 (mailto:%s)" % MAILTO,
            })
            with urllib.request.urlopen(req, timeout=40) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code == 429:
                wait = min(60, 2 * (i + 1))
                time.sleep(wait)  # 限流退避，最多等 60s
                continue
            time.sleep(1 + i * 1.5)
        except Exception:
            time.sleep(1 + i * 1.5)
    return None


def fetch_batch(pmids):
    """批量查一批 PMID 的引文信号。返回 {pmid: signal_dict}。"""
    if not pmids:
        return {}
    filt = "ids.pmid:" + "|".join(pmids)
    params = urllib.parse.urlencode({
        "filter": filt,
        "per-page": str(len(pmids)),
        "select": "id,cited_by_count,is_retracted,authorships,publication_year,"
                  "primary_location",
        "mailto": MAILTO,
    })
    d = api_get("https://api.openalex.org/works?" + params)
    out = {}
    if not d or "results" not in d:
        return out
    # 结果里带 PMID，需要从 id 反查。OpenAlex 的 work id 不含 PMID，
    # 但可以用 ids 字段；select 里加 ids 更稳。这里退化为：按顺序回填。
    # 更稳：重新请求带 ids.pmid 的映射。为简单可靠，这里改用 per-result 的 ids。
    # 由于 select 没带 ids，我们换一种方式：直接解析结果，靠顺序匹配（不可靠）。
    # 因此这里改用「逐个回查」太慢，改为：请求时带 mailto + 完整返回。
    return out


def fetch_batch_full(pmids):
    """批量查，返回 {pmid: signal}。用 ids 字段做精确映射。"""
    if not pmids:
        return {}
    # 关键：ids.pmid 的值必须是完整 URL 形式，不是裸 PMID。
    filt = "ids.pmid:" + "|".join(
        "https://pubmed.ncbi.nlm.nih.gov/%s" % p for p in pmids
    )
    params = urllib.parse.urlencode({
        "filter": filt,
        "per-page": str(len(pmids)),
        "select": "id,ids,cited_by_count,is_retracted,authorships,publication_year,"
                  "primary_location",
        "mailto": MAILTO,
    })
    if API_KEY:
        params += "&api_key=" + urllib.parse.quote(API_KEY)
    d = api_get("https://api.openalex.org/works?" + params)
    out = {}
    if not d or "results" not in d:
        return out
    for w in d["results"]:
        ids = w.get("ids") or {}
        pmid = (ids.get("pmid") or "").split("/")[-1]
        if not pmid:
            continue
        src = (w.get("primary_location") or {}).get("source") or {}
        out[pmid] = {
            "oa_found": True,
            "oa_id": (w.get("id") or "").split("/")[-1],
            "cited_by_count": w.get("cited_by_count", 0),
            "oa_is_retracted": 1 if w.get("is_retracted") else 0,
            "oa_n_authors": len(w.get("authorships", [])),
            "oa_year": w.get("publication_year"),
            "oa_journal": src.get("display_name"),
        }
    return out


def main():
    if not os.path.exists(PMID_FILE):
        print(f"找不到 {PMID_FILE}，请把它和本脚本放同一目录。")
        sys.exit(1)

    pmids = [l.strip() for l in open(PMID_FILE, encoding="utf-8") if l.strip()]
    print(f"PMID 总数: {len(pmids)}")

    # 断点续传：读已有结果
    got = {}
    if os.path.exists(OUT_FILE):
        for l in open(OUT_FILE, encoding="utf-8"):
            d = json.loads(l)
            got[d["pmid"]] = d
    print(f"已有结果: {len(got)}")

    todo = [p for p in pmids if p not in got]
    print(f"待采: {len(todo)}")

    t0 = time.time()
    done = 0
    # 分批处理
    for i in range(0, len(todo), BATCH):
        batch = todo[i:i + BATCH]
        batch_res = fetch_batch_full(batch)
        for p in batch:
            if p in batch_res:
                got[p] = batch_res[p]
            else:
                got[p] = {"pmid": p, "oa_found": False}
        done += len(batch)
        # 每 5 批落一次盘
        if (i // BATCH) % 5 == 0 or i + BATCH >= len(todo):
            tmp = OUT_FILE + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                for p in pmids:
                    if p in got:
                        f.write(json.dumps(got[p], ensure_ascii=False) + "\n")
            os.replace(tmp, OUT_FILE)
        el = time.time() - t0
        rate = done / el if el > 0 else 0
        pct = done / len(todo) * 100
        sys.stdout.write(f"\r  进度 {done}/{len(todo)} ({pct:.1f}%)  "
                         f"速率 {rate:.1f} 篇/秒  已用时 {el/60:.1f} 分")
        sys.stdout.flush()
        time.sleep(0.15)

    # 最终落盘
    tmp = OUT_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        for p in pmids:
            if p in got:
                f.write(json.dumps(got[p], ensure_ascii=False) + "\n")
    os.replace(tmp, OUT_FILE)

    found = sum(1 for v in got.values() if v.get("oa_found"))
    print(f"\n\n完成！共 {len(got)} 篇，其中 OpenAlex 命中 {found} 篇")
    print(f"结果已写入 {OUT_FILE}，把这个文件发回即可。")


if __name__ == "__main__":
    main()
