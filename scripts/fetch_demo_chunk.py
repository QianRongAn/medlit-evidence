"""限量抓取 demo 库元数据（每跑一次抓 --limit 篇，抓完即退出）。

设计：一次只抓固定量，跑完立即退出，靠 demo_corpus.jsonl 断点续传。
这样每次都是短前台任务，不会被沙箱回收/超时白跑。反复调用直到抓满。
"""
import argparse
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
from build_demo_risk_db import efetch, DEMO_CORPUS, DEMO_PMIDS  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=5000)
    a = ap.parse_args()

    pmids = json.load(open(DEMO_PMIDS, encoding="utf-8"))
    got = {}
    if os.path.exists(DEMO_CORPUS):
        for l in open(DEMO_CORPUS, encoding="utf-8"):
            d = json.loads(l)
            got[d["pmid"]] = d

    todo = [p for p in pmids if p not in got]
    print(f"已有 {len(got)}，剩余 {len(todo)}，本次抓 {min(a.limit, len(todo))}")

    if not todo:
        print("已抓满，无需继续")
        return

    batch_target = todo[:a.limit]
    t0 = time.time()
    done_this_run = 0
    for i in range(0, len(batch_target), 100):
        batch = batch_target[i:i + 100]
        docs = efetch(batch)
        for d in docs:
            got[d["pmid"]] = d
        done_this_run += len(docs)
        # 每 500 篇落盘一次
        if (i + 100) % 500 == 0:
            tmp = DEMO_CORPUS + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                for p in pmids:
                    if p in got:
                        f.write(json.dumps(got[p], ensure_ascii=False) + "\n")
            os.replace(tmp, DEMO_CORPUS)
            print(f"  本段进度 {done_this_run}/{len(batch_target)}，累计 {len(got)}", flush=True)
        time.sleep(0.3)

    # 最终落盘
    tmp = DEMO_CORPUS + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        for p in pmids:
            if p in got:
                f.write(json.dumps(got[p], ensure_ascii=False) + "\n")
    os.replace(tmp, DEMO_CORPUS)
    el = time.time() - t0
    print(f"本段完成：新增 {done_this_run}，累计 {len(got)}，速率 {done_this_run/el:.1f} 篇/秒")


if __name__ == "__main__":
    main()
