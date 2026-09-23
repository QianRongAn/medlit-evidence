#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""并发采集 OpenAlex 引文信号（多线程 + curl 子进程）。

背景：单线程每批 curl 5-6s（网络 RTT 主导），78481 篇要 20h。
改用 ThreadPoolExecutor 并发发多批，把速率拉到 10+ 篇/秒，全量压到 2-3h。

用法：
    python collect_signals_curl.py <api_key> [并发数] [限制篇数]
    默认并发 16，限制 0=全部。
"""
import json
import os
import subprocess
import sys
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed

_HERE = os.path.dirname(os.path.abspath(__file__))
_BASE = os.path.dirname(_HERE)
PMID_FILE = os.path.join(_BASE, "data", "all_pmids_for_signals.txt")
OUT_FILE = os.path.join(_BASE, "data", "integrity_signals.jsonl")
MAILTO = os.environ.get("OPENALEX_MAILTO", "").strip()
BATCH = 50  # 每批 50 个 PMID

API_KEY = os.environ.get("OPENALEX_API_KEY", "").strip()
CONC = 16
LIMIT = 0
if len(sys.argv) > 1 and sys.argv[1] != "":
    API_KEY = sys.argv[1].strip()
if len(sys.argv) > 2:
    CONC = int(sys.argv[2])
if len(sys.argv) > 3:
    LIMIT = int(sys.argv[3])

SELECT = "id,ids,cited_by_count,is_retracted,authorships,publication_year,primary_location"


def curl_get(url, timeout=45):
    try:
        r = subprocess.run(
            ["curl", "-s", "--max-time", str(timeout), url],
            capture_output=True, timeout=timeout + 10,
        )
    except subprocess.TimeoutExpired:
        return None
    if r.returncode != 0 or not r.stdout:
        return None
    try:
        return json.loads(r.stdout.decode("utf-8", "replace"))
    except Exception:
        return None


def fetch_batch(pmids):
    if not pmids:
        return {}
    filt = "ids.pmid:" + "|".join(
        "https://pubmed.ncbi.nlm.nih.gov/%s" % p for p in pmids
    )
    params = urllib.parse.urlencode({
        "filter": filt,
        "per-page": str(len(pmids)),
        "select": SELECT,
        "mailto": MAILTO,
        "api_key": API_KEY,
    })
    d = curl_get("https://api.openalex.org/works?" + params)
    out = {}
    if not d or "results" not in d:
        return out
    for w in d.get("results", []):
        ids = w.get("ids") or {}
        pmid = (ids.get("pmid") or "").split("/")[-1]
        if not pmid:
            continue
        src = (w.get("primary_location") or {}).get("source") or {}
        out[pmid] = {
            "pmid": pmid,
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
        print(f"找不到 {PMID_FILE}")
        sys.exit(1)
    if not API_KEY:
        print("缺少 API key")
        sys.exit(1)

    order = [l.strip() for l in open(PMID_FILE, encoding="utf-8") if l.strip()]
    if LIMIT > 0:
        order = order[:LIMIT]
    print(f"PMID 总数: {len(order)}  并发: {CONC}")

    got = {}
    if os.path.exists(OUT_FILE):
        for l in open(OUT_FILE, encoding="utf-8"):
            d = json.loads(l)
            got[d["pmid"]] = d
    print(f"已有结果: {len(got)}")

    todo = [p for p in order if p not in got]
    print(f"待采: {len(todo)}")

    # 切成批
    batches = [todo[i:i + BATCH] for i in range(0, len(todo), BATCH)]
    print(f"共 {len(batches)} 批，开始并发采集...")

    t0 = time.time()
    done_batch = 0

    def run(b):
        return fetch_batch(b)

    with ThreadPoolExecutor(max_workers=CONC) as ex:
        futs = {ex.submit(run, b): b for b in batches}
        for fut in as_completed(futs):
            b = futs[fut]
            try:
                res = fut.result()
            except Exception:
                res = {}
            for p in b:
                got[p] = res.get(p, {"pmid": p, "oa_found": False})
            done_batch += 1
            if done_batch % 10 == 0 or done_batch == len(batches):
                save(got, order)
                el = time.time() - t0
                n_done = sum(1 for p in todo if p in got)
                rate = n_done / el if el > 0 else 0
                pct = n_done / len(todo) * 100
                print(f"\r  {n_done}/{len(todo)} ({pct:.1f}%)  {rate:.1f} 篇/秒  {el/60:.1f} 分", end="", flush=True)

    save(got, order)
    found = sum(1 for v in got.values() if v.get("oa_found"))
    print(f"\n\n完成！共 {len(got)} 篇，命中 {found} 篇 → {OUT_FILE}")


def save(got, order):
    tmp = OUT_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        for p in order:
            if p in got:
                f.write(json.dumps(got[p], ensure_ascii=False) + "\n")
    os.replace(tmp, OUT_FILE)


if __name__ == "__main__":
    main()
