"""抓取 3 万篇全量元数据（复用 fetch_corpus 的解析），断点续传。

输入：data/large_targets.json（collect_large.py 产出）
输出：data/corpus_raw_large.jsonl
"""
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

from fetch_corpus import efetch  # noqa: E402

SRC = os.path.join(ROOT, "data", "large_targets.json")
OUT = os.path.join(ROOT, "data", "corpus_raw_large.jsonl")


def _flush(got, targets, out_path):
    """把已抓到的写盘（带 label），可反复调用做增量保存。"""
    tmp = out_path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        for t in targets:
            d = got.get(t["pmid"])
            if not d:
                continue
            d["label"] = t["label"]
            d["label_name"] = t["label_name"]
            f.write(json.dumps(d, ensure_ascii=False) + "\n")
    os.replace(tmp, out_path)


def main():
    targets = json.load(open(SRC, encoding="utf-8"))
    print(f"目标 {len(targets)} 篇")

    got = {}
    if os.path.exists(OUT):
        for l in open(OUT, encoding="utf-8"):
            d = json.loads(l)
            got[d["pmid"]] = d

    todo = [t["pmid"] for t in targets if t["pmid"] not in got]
    print(f"已完成 {len(got)}，剩余 {len(todo)}")

    label_of = {t["pmid"]: t for t in targets}

    for i in range(0, len(todo), 100):
        batch = todo[i:i + 100]
        docs = efetch(batch)
        for d in docs:
            got[d["pmid"]] = d
        time.sleep(0.4)
        # 每 500 篇增量落盘，防止中途被杀白跑
        if (i + 100) % 500 == 0 or i + 100 >= len(todo):
            _flush(got, targets, OUT)
            print(f"  进度 {min(i + 100, len(todo))}/{len(todo)}，累计 {len(got)}", flush=True)

    _flush(got, targets, OUT)
    print(f"已写入 {len(got)} 篇到 {OUT}")


if __name__ == "__main__":
    main()
