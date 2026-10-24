# 研究类型与完整性规则（0.4.0）

## 研究类型

`classify(abstract, pubtypes, title=...)` 不再拼接所有字段扫描关键词。

1. 识别通知与研究计划，避免当作已完成研究。
2. 明确的发表类型采用精确词项匹配，优先于标题与摘要。例如 Case Reports 不会被背景中的 meta-analysis 覆盖。
3. 已知层级取具体类型：Meta-Analysis 优先于 Systematic Review/Review；Randomized Controlled Trial 优先于 Clinical Trial。不兼容的明确设计标注返回 other/N/A。
4. 仅 Journal Article 等泛化标注不足以确定设计。缺少明确类型时，标题须以设计自述开头或在冒号后自述设计；摘要只使用方法/设计段或明确自述本研究的句子。既往研究、背景、讨论、未来计划不作为判据。
5. 移除 prospective、follow-up、phase i 等宽泛子串的单独判断；保留词边界和非随机识别。无法确定时返回未分级，接受召回降低。

这些是保守规则，不保证穷尽复杂文献设计，也未进行临床有效性验证。研究设计参考分级与模型特征是独立路径；本轮没有修改已训练模型的特征或重训模型。

## 完整性

关系指向与通知身份依据 [NLM 链接政策](https://www.nlm.nih.gov/bsd/policy/errata.html)、[存疑关系说明](https://www.nlm.nih.gov/pubs/techbull/nd16/nd16_medline_data_changes_2017.html) 和 [RefType 定义](https://dtd.nlm.nih.gov/ncbi/pubmed/doc/out/250101/att-RefType-c.html)。

| RefType | 当前记录的处理 |
| --- | --- |
| RetractionIn | 撤稿原文 |
| RetractionOf | 撤稿通知 |
| ExpressionOfConcernIn | 存疑原文 |
| ExpressionOfConcernFor | 存疑通知 |
| ErratumIn | 有更正的原文 |
| ErratumFor | 更正通知 |
| CorrectedandRepublishedIn / From | 原版 / 修正后的重发版，均提示更正 |
| RetractedandRepublishedIn | 已撤稿旧版 |
| RetractedandRepublishedFrom | 修正后重发的新版，不自动继承旧版撤稿状态 |

支持 Retracted Publication、Corrected and Republished Article，以及通知类型 Retraction Notice、历史 Retraction of Publication、Expression of Concern 和 Published Erratum。未知关系和普通评论、更新、重印不直接判为问题文献。

`app/integrity.py` 统一处理解析结果、离线旧数据和回答过滤。撤稿原文和通知仅供核查，不进入回答、LLM 上下文或研究模型评分。存疑和更正原文仍可摘录，但保留全部已知告警。

主状态只用于兼容；多项问题保存于 integrity_flags，通知身份独立保存于 is_notice。通知本身若又被撤稿，可以同时具备两种信息。原文和相关记录的 PMID 使用各自的 XML 路径，缺失原文 PMID 时不以关联 PMID 冒充。

## 回归范围

- `tests/test_study_type.py`：元数据优先、背景污染、具体层级、冲突、非随机、计划、词边界与标题非自述情形。
- `tests/fixtures/pubmed_integrity.xml`：10 条明确标注为合成数据的固定样本，覆盖原文/通知、同时存疑与更正、两种重发方向。
- `tests/test_integrity.py`：各关系正反方向、缺关联 PMID、主 PMID 隔离、旧数据兼容与未知关系。
- ASGI 接口测试通过 XML 解析、缓存、类型标注和摘要摘录的真实链路；另测仅通知不调用 LLM，新版本不继承旧版撤稿。
- 前端测试覆盖多标记同时显示、正反向链接文字和不合法关联 PMID 的处理。
