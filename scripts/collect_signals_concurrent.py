#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""并发采集 OpenAlex 引文信号（直连 + 多线程提速）。

背景：沙箱直连 OpenAlex 单篇 4.6 秒（连接 1.2s + 响应 3.4s），
串行只有 0.18 篇/秒。用线程池并发把吞吐提到 2~4 篇/秒。

输出：data/integrity_signals.jsonl，每篇 {pmid, oa_found, cited_by_count,
      oa_is_retracted, oa_n_authors, oa_year, oa_journal}
断点续传：已有记录跳过。
"""
import argparse
import json
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import httpx

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DATA = os.path.join(ROOT, "data")

DEMO_PMIDS = os.path.join(DATA, "demo_pmids.json")
OUT = os.path.join(DATA, "integrity_signals.jsonl")

MAILTO = os.environ.get("OPENALEX_MAILTO", "").strip()


def fetch_one(pmid):
    """查单篇，返回 (pmid, dict)。失败返回 oa_found=False。"""
    try:
        r = httpx.get(
            "https://api.openalex.org/works",
            params={"filter": f"ids.pmid:{pmid}", "per-page": "1",
                    "mailto": MAILTO},
            timeout=25, proxy=None, trust_env=False,
        )
        if r.status_code != 200:
            return pmid, {"oa_found": False}
        d = r.json()
        if not d.get("results"):
            return pmid, {"oa_found": False}
        w = d["results"][0]
        return pmid, {
            "oa_found": True,
            "oa_id": w.get("id", "").split("/")[-1],
            "cited_by_count": w.get("cited_by_count", 0),
            "oa_is_retracted": 1 if w.get("is_retracted") else 0,
            "oa_n_authors": len(w.get("authorships", [])),
            "oa_year": w.get("publication_year"),
            "oa_journal": (w.get("primary_location") or {}).get("source") and
                          ((w.get("primary_location") or {}).get("source") or {}).get("display_name"),
        }
    except Exception:
        return pmid, {"oa_found": False}


def load_got():
    got = {}
    if os.path.exists(OUT):
        for l in open(OUT, encoding="utf-8"):
            d = json.loads(l)
            got[d["pmid"]] = d
    return got


def save(got, order):
    tmp = OUT + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        for p in order:
            if p in got:
                f.write(json.dumps(got[p], ensure_ascii=False) + "\n")
    os.replace(tmp, OUT)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=2000)
    ap.add_argument("--workers", type=int, default=12)
    a = ap.parse_args()

    pmids = json.load(open(DEMO_PMIDS, encoding="utf-8"))
    got = load_got()
    todo = [p for p in pmids if p not in got][:a.limit]
    print(f"已有 {len(got)}，本次采 {len(todo)}，并发 {a.workers}")

    t0 = time.time()
    done = 0
    with ThreadPoolExecutor(max_workers=a.workers) as ex:
        futs = {ex.submit(fetch_one, p): p for p in todo}
        for fut in as_completed(futs):
            pmid, sig = fut.result()
            sig["pmid"] = pmid
            got[pmid] = sig
            done += 1
            if done % 100 == 0:
                el = time.time() - t0
                print(f"  进度 {done}/{len(todo)}，速率 {done/el:.1f} 篇/秒，"
                      f"累计 {len(got)}", flush=True)
                save(got, pmids)

    save(got, pmids)
    el = time.time() - t0
    print(f"完成：本次 {done} 篇，速率 {done/el:.1f} 篇/秒，累计 {len(got)} -> {OUT}")


if __name__ == "__main__":
    main()
