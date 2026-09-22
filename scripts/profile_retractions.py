"""撤稿风险画像分析：读撤稿数据集，产出可复现的统计报告。

输出 data/retraction_profile.md：
- 标签分布、撤稿耗时分布（发表 -> 撤稿）
- 撤稿文献的期刊分布、研究类型分布
- 与对照组对比，提炼"高风险信号"
"""
import json
import os
from collections import Counter

DATASET = "data/retraction_dataset.jsonl"
OUT = "data/retraction_profile.md"


def load():
    if not os.path.exists(DATASET):
        return []
    rows = []
    with open(DATASET, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def _median(xs):
    xs = sorted(xs)
    if not xs:
        return 0
    return xs[len(xs) // 2]


def analyze(rows):
    labels = Counter(r["label"] for r in rows)
    ret = [r for r in rows if r["label"] == "retracted"]
    ok = [r for r in rows if r["label"] == "ok"]

    # 撤稿耗时（发表年份 -> 撤稿通知年份）
    delays = [r["years_to_retraction"] for r in ret if r.get("years_to_retraction") is not None]

    # 期刊分布（撤稿 vs 对照）
    ret_journals = Counter(r["journal"] for r in ret if r.get("journal"))
    ok_journals = Counter(r["journal"] for r in ok if r.get("journal"))

    # 研究类型（PublicationType 含 RCT / Review / Case 等关键词）
    def study_flags(doc):
        pts = " ".join(doc.get("study_type_pt", [])).lower()
        flags = []
        if "randomized controlled trial" in pts:
            flags.append("RCT")
        if "meta-analysis" in pts or "systematic review" in pts:
            flags.append("Meta/系统综述")
        if "case report" in pts:
            flags.append("病例报告")
        if "review" in pts:
            flags.append("综述")
        if "clinical trial" in pts:
            flags.append("临床试验")
        return flags

    ret_types = Counter()
    for r in ret:
        for f in study_flags(r):
            ret_types[f] += 1
    ok_types = Counter()
    for r in ok:
        for f in study_flags(r):
            ok_types[f] += 1

    return {
        "labels": labels,
        "n_retracted": len(ret),
        "n_ok": len(ok),
        "delays": delays,
        "ret_journals": ret_journals,
        "ok_journals": ok_journals,
        "ret_types": ret_types,
        "ok_types": ok_types,
    }


def render(rows):
    a = analyze(rows)
    if not rows:
        return "# 撤稿风险画像\n\n暂无数据，先运行 scripts/collect_retractions.py\n"

    n = len(rows)
    lines = []
    lines.append("# 撤稿风险画像（Retraction Risk Profile）\n")
    lines.append(f"> 样本量 {n} 篇，采集自 PubMed E-utilities，可复现：`python scripts/collect_retractions.py`\n")

    lines.append("## 标签分布\n")
    lines.append("| 标签 | 篇数 |")
    lines.append("| --- | --- |")
    for k in ["retracted", "concern", "corrected", "ok"]:
        lines.append(f"| {k} | {a['labels'].get(k, 0)} |")
    lines.append("")

    if a["delays"]:
        delays = a["delays"]
        lines.append("## 撤稿耗时（发表 -> 撤稿，年）\n")
        lines.append(f"- 中位数：{_median(delays)} 年")
        lines.append(f"- 平均：{sum(delays)/len(delays):.1f} 年")
        lines.append(f"- 范围：{min(delays)} ~ {max(delays)} 年")
        lines.append(f"- 5 年内被撤稿占比：{sum(1 for d in delays if d <= 5)/len(delays)*100:.0f}%\n")

    lines.append("## 撤稿文献的期刊分布（Top 10）\n")
    lines.append("| 期刊 | 撤稿篇数 |")
    lines.append("| --- | --- |")
    for j, c in a["ret_journals"].most_common(10):
        lines.append(f"| {j} | {c} |")
    lines.append("")

    lines.append("## 研究类型分布（撤稿 vs 对照）\n")
    lines.append("| 研究类型 | 撤稿 | 对照 |")
    lines.append("| --- | --- | --- |")
    all_types = set(a["ret_types"]) | set(a["ok_types"])
    for t in sorted(all_types, key=lambda x: -a["ret_types"].get(x, 0)):
        lines.append(f"| {t} | {a['ret_types'].get(t, 0)} | {a['ok_types'].get(t, 0)} |")
    lines.append("")

    lines.append("## 说明\n")
    lines.append("本报告为描述性统计，非因果推断。撤稿耗时受采样年份段影响；"
                 "细粒度撤稿原因（数据造假/图片重复等）需付费全文，此处未纳入。\n")
    return "\n".join(lines)


def main():
    rows = load()
    md = render(rows)
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(md)
    print(f"报告写入 {OUT}（{len(rows)} 篇样本）")


if __name__ == "__main__":
    main()
