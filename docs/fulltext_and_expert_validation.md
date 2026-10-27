# 开放全文自动评估与专家验证

## 默认运行方式

检索结果先返回，页面随后自动调用 `POST /api/assessment/fulltext`，每次最多传 10 个 PMID、最多同时发送两个批次，继续处理所有已加载来源。这是网络批次规模，不是总评估或展示数量上限。新问题会取消旧任务；网络失败保留已显示结果并可重试。人工表单不是前置条件。

服务端重新获取 PubMed 原记录，执行相同 PICO 筛选和完整性检查，再查询 Europe PMC 开放全文。用户不能传入任意抓取 URL、伪造原文或跳过撤稿检查。全文必须同时通过元数据的开放访问标志和 JATS 的 PMID/PMCID 身份校验。抓取失败、无可用开放全文和已取得全文分别记录；未取得时保留明确标注的摘要依据。

全文解析包括正文、正文附表、可读取的文字附录；不读参考文献列表。每个段落和表格行保存稳定块编号、章节、规范文本、获取时间、XML 与正文 SHA256、来源 URL 和原许可。单篇 XML 过大或包含实体声明时不自动解析。图像、外部补充文件以及复杂合并表头的列映射尚未解析，不标为已经审阅。源文献版权及许可保留原作者声明，不适用项目代码许可。

## 自动判断

- 效应方向仅使用当前研究的方法语境、结果和结论，不让引言、参考文献或 GRADE 评论段落代替实际效应。全文未找到可靠效应句但摘要已有时，保留并明确标为摘要依据。
- 五维评估使用全文中的明确报告，每条引文必须能定位回规范文本块。GRADE 表只有表头/列对应清楚、结局和已指定 PICO 对齐时才读取，不把另一结局或另一比较的等级借过来。
- 作者在全文明确报告的 GRADE 与系统自行形成的判断区分。可显示全文中的低、中等、高等级，保留原句、表格行及来源；这不等于系统独立重做了作者的综述。
- 未有完整信息的维度保持缺口；取得全文不自动变成高质量。原始研究的研究级偏倚与结局证据体的 GRADE 不是同一个概念。本工具不宣称已覆盖完整 RoB 2 / ROBINS-I、全部补充材料、网络 Meta 的 CINeMA 或患者重要差异阈值评估。

接口只返回全文元数据、判断及所需引文，不把整篇全文随检索结果传给浏览器。全文取得进度、直接作者评级和原文位置在证据概况中展示。本文的自动评估是可追溯的规则实现，不是专家验证通过的临床决策系统。

来源：[Europe PMC 开放全文 API](https://europepmc.org/RestfulWebService)、[Cochrane 关于逐结局 GRADE 与双人独立评估](https://www.cochrane.org/authors/handbooks-and-manuals/handbook/current/chapter-14)。

## 专家盲审试点

问题池见 `evaluation/fulltext_pilot_cases.json`；冻结包见 `evaluation/expert_fulltext_v1/`。六个案例各选一个公开来源，属于有意选择的功能试点，不是覆盖完整证据体的系统综述，也不是人群代表性临床准确率样本。PMID 与训练特征表、旧 `clinical_v1` 基准不重叠；这不能消除相关综述之间的试验家族重叠，更不能据此宣称总体临床泛化性能。

`blind/` 只含问题与冻结原文，不含系统预测；`reviews/` 提供两份独立空表；`system/` 保存系统预测和运行指纹。组织者只向专家分发 blind 目录和其本人的空表，不要发送 system 目录或另一人的初始标签。原文作者评级属于允许查看的源资料，不是系统标签。

评审者需填写真实身份、临床/循证角色、专长、独立审阅声明、时间，逐项判断方向、可信度及五个维度；实质性判断必须提供原文块和连续引文。资质声明不能由工具验证，组织者应另行核实。模型生成标签不能冒充专家；当前没有实际专家参与，因此 `validation_status.json` 的专家准确率和一致性均为 `null`。

```bash
# 已有冻结包不能覆盖。新采样或新代码应选择新目录。
python scripts/expert_validation.py prepare --cases evaluation/fulltext_pilot_cases.json --output evaluation/new_expert_package

# 等两位专家独立完成后再执行；现在的空表会被拒绝。
python scripts/expert_validation.py score --package evaluation/expert_fulltext_v1 --review-a reviewer_A.completed.json --review-b reviewer_B.completed.json --output evaluation/review_report.json

# 有分歧时上一步只生成一致性统计和第三人裁决空表，不发布专家准确率。
python scripts/expert_validation.py score --package evaluation/expert_fulltext_v1 --review-a reviewer_A.completed.json --review-b reviewer_B.completed.json --adjudication adjudication.completed.json --output evaluation/adjudicated_report.json
```

最终报告包含原始一致率、Cohen kappa（类别恒定时不可计算）、所有案例准确率、系统回答覆盖率及回答条件下准确率。弃答不能从总案例分母中消失。原文/预测/标注错配、重复、缺项、错误引文、同一人充当两位评审或未裁决的分歧都不能生成最终专家准确率。评审材料与系统预测均冻结 SHA256，历史结果不覆写。

后续需要真实双人标注、第三人裁决，以及足量未用于修正规则的保留集。当前交付的是全文评估和可执行的专家验证流程，不能把回归测试通过写成专家验证完成。
