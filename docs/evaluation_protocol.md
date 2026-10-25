# 实验评估协议 v2

日期：2026-10-18。训练、消融和引文对照共用 `scripts/evaluation.py`，默认只写报告，不更新产品模型。

## 指标与常量对照

AP（Average Precision）作为主指标，另列 ROC AUC、测试阳性比例、Brier、PR 曲线梯形面积。后者只用于追溯旧结果，不能混称 AP。[scikit-learn 说明](https://scikit-learn.org/stable/modules/generated/sklearn.metrics.average_precision_score.html)明确区分 AP 与梯形插值。

每个模型、特征组、每折测试都配同一切分上的常量对照：恒定预测训练集阳性比例，不能偷用测试比例。常量 AP 等于该测试集阳性比例，ROC AUC 为 0.5；其 PR 梯形面积可达 `(1 + 测试阳性比例) / 2`。因此旧报告的年份 ROC AUC=0.5 / PR 梯形面积较高，不代表有效排序。

报告列模型减常量的 ΔAP、ΔBrier（后者越低越好）。CV 输出折均值和折标准差；标准差不是置信区间，不据此判断统计显著。特征组差异仅是探索性比较，不证明独立贡献或因果关系。病例/对照抽样比例不是总体撤稿率，Brier 的改善也不证明面向真实总体已校准。

## 回顾性发表年份分组

必须显式指定 `--cutoff-year`，不再根据全数据 70 分位挑选切点。训练年份 ≤ cutoff，测试年份 > cutoff + gap；间隔由 `--gap-years` 指定，报告排除数量。缺失/非整数年份、空集、任一侧缺类别、重复/无效 PMID 都报错。CV 按固定种子 42 分层，少数类不足折数报错。

此次沿用旧实验的 2024 切点，是已看过结果的探索性重算，不是预注册或独立未触碰留出集。只有发表年份和采集时状态，不能证明未来事件预测；当前引文次数、作者/参考文献/摘要也可能在事后更新。重复 PMID 阻断不等于排除同作者、同刊或相似文本带来的依赖。

```bash
python scripts/train_model.py --features data/features_large.csv --cutoff-year 2024 --report data/model_report_large_v2.md
python scripts/evaluate_ablation.py --cutoff-year 2024
python scripts/evaluate_citation_signal.py --cutoff-year 2024 --signals data/integrity_signals.jsonl
```

每折重新克隆模型；标准化器只拟合训练数据，符合 [scikit-learn 数据泄漏指南](https://scikit-learn.org/stable/common_pitfalls.html)。三个实验入口复用同一指标与切分实现。JSON 附件保留每折指标、训练/测试 PMID 有序哈希、数据哈希、种子、模型参数和依赖版本；引文实验额外记录信号文件哈希。引文实验只允许明确命中的记录，缺失计数不能冒充 0，重复信号 PMID 拒绝最后一条覆盖。

## 固定观察窗时间协议

`--protocol dated-horizon --cutoff-date YYYY-MM-DD --as-of YYYY-MM-DD --horizon-days N [--gap-days N]` 接收逐篇的以下列，日期必须精确到日：

| 列 | 要求 |
| --- | --- |
| pmid | 唯一、有效 |
| prediction_date | 该篇预测基准日 |
| features_observed_at | 该行所有特征真实可用的最晚日期，≤预测日 |
| event_date | 目标事件日期，无事件为空；事件须晚于预测日且不晚于随访终点 |
| followup_end | 确认事件状态的随访终点，≤数据 as-of 日期 |
| label_available_at | 固定观察窗标签可用日期；完整窗已结束且被观察到后才能填写；未成熟可空 |

目标定义是预测日后 N 天内的撤稿事件，标签由事件日期推导，忽略当前 `label`。如需将存疑作为另一结局须建立单独事件定义，不能混入撤稿时间。固定窗对正负样本均要求完整观察，避免正样本提前入组而负样本观察不足；观察不足的样本明确排除，不能标成阴性。

训练样本的观察窗终点与标签可用日都必须 ≤ 切点；测试预测日在切点 + gap 之后，且观察窗已完整随访。切点前但标签后来才可用的记录排除。严格协议只报告该时间切分，不附随机 CV。切分后任一侧缺类别即拒绝评估。

这是一套可执行的历史时间模拟检查，并不能自动证实日期字段真实。必须从冻结的预测时点来源重建**每项**特征，保留来源和事件证据供审计；给今日特征补一个过去日期不满足协议。当前仓库 CSV 缺少这些元数据，会明确拒绝严格时间评估。当前引文快照入口更直接禁止 dated-horizon；未来须新增按时点对齐的信号数据路径，不能把今日被引次数映射到过去。

## 此次实际重跑

23,287 条记录，2024 切点：训练 17,177，测试 6,110，测试阳性比例 0.1646。完整结果见 [模型 v2](../data/model_report_large_v2.md)、[消融 v2](../data/ablation_report_v2.md) 和同名 JSON。

| 回顾性年份分组 | ROC AUC | AP | 常量 AP | PR 梯形面积 |
| --- | --- | --- | --- | --- |
| 仅年份 LightGBM | 0.5000 | 0.1646 | 0.1646 | 0.5823 |
| 全特征 LightGBM | 0.7126 | 0.3196 | 0.1646 | 0.3186 |

全部模型报告和 11 组消融均在本地 CPU 重跑；未更新产品模型。原始引文信号文件未提交，无法重跑引文结果，旧报告加醒目历史标记，旧数字保留供追溯。未来预测能力仍为不可评估，需收集时点特征、事件日期与随访证据；这不是用年份切分就能补出的数据。

旧 `train_model.py` 自动覆盖 models 和生成 SHAP 的行为已取消。需要显式 `--models-dir` 才导出模型与 scaler；本轮未使用。SHAP 图保留为历史资产，不自动刷新。评估回归依赖 numpy/pandas/scikit-learn/lightgbm，CI 已安装并运行，无网络数据或 GPU 需求。
