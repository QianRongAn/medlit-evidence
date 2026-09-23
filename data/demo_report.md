# 撤稿风险预标注 demo 库 · 实测报告

样本：50000 篇近 5 年（2020-2025）肿瘤（neoplasms[mesh]）文献。

## 实测指标

| 指标 | 实测值 |
| --- | --- |
| 抓取速率 | **20~36 篇/秒**（eutils 直连、无 API key；跑久了会掉到 20） |
| 元数据存储（corpus.jsonl） | 92.3 MB（约 1846 B/篇） |
| 特征表（features.csv） | 82.8 MB |
| SQLite 风险库 | 110.3 MB（约 2205 B/篇） |

## 全量成本反推（PubMed 全量约 3700 万条）

| 项目 | 反推值 |
| --- | --- |
| 抓取耗时（eutils 单线程，25 篇/秒） | **约 411 小时 ≈ 17 天** |
| 抓取耗时（官方 FTP baseline 快照） | **数小时**（推荐，且不触发限流） |
| 元数据存储 | 3700 万 × 1846 B ≈ **68 GB** |
| SQLite 风险库 | 3700 万 × 2205 B ≈ **82 GB** |
| 风险分计算（LightGBM，纯 CPU） | 3700 万 × 微秒级 ≈ **几分钟** |

> 关键结论：**算分不是瓶颈（纯 CPU 几分钟），抓数据才是墙（eutils 要 17 天，FTP 快照数小时）**。全量库存储约 70~80 GB，普通云盘即可承载。

## 风险分分布（5 万篇肿瘤文献）

| 统计量 | 值 |
| --- | --- |
| 均值 | 0.345 |
| 中位数 | 0.307 |
| P90 | 0.688 |
| P99 | 0.848 |
| 高风险（>0.7） | 4479 篇 |
| 低风险（<0.3） | 24482 篇 |

## 高风险 Top 10

| 排名 | PMID | 风险分 | 标题 |
| --- | --- | --- | --- |
| 1 | 34950442 | 0.969 | Effect of Different Anesthesia Methods on Emergence Agitation... |
| 2 | 36550238 | 0.949 | The curative effect of some natural active compounds for liver... |
| 3 | 34933889 | 0.948 | The VISION Forward: Recognition and Implication of PSMA-/18F... |
| 4 | 36619796 | 0.941 | Performance of Restricted Mean Survival Time Based Methods... |
| 5 | 34912887 | 0.939 | Analysis of Effect on Infection Factors and Nursing Care of... |
| 6 | 36605938 | 0.938 | Prediction of the invasiveness of PTMC by a combination of... |
| 7 | 36700467 | 0.937 | Origin recognition complex subunit 1 (ORC1) augments malignant... |
| 8 | 36567858 | 0.935 | Artemisinin Alleviates Cerebral Ischemia/Reperfusion-Induced... |
| 9 | 34976330 | 0.934 | Big Data Information under Proportional Hazard Mathematical... |
| 10 | 34922601 | 0.933 | Long noncoding RNA PVT1 promotes breast cancer proliferation... |

## 说明

- 风险分是「撤稿风险的排序辅助」，不代表该文献真的会撤稿。
- 模型基于摘要写作特征（LightGBM 22 特征），非全文图像/数据核查，仅用于辅助人工审查。
- demo 库可用 SQLite 查询，支持按风险分、年份检索（`data/demo_risk.db`）。
