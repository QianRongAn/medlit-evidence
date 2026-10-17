# MedLit Evidence

医学文献检索与摘要整理原型：输入问题，从 PubMed 召回文献，展示研究类型、候选摘要句及完整性标记，供人工核查。

**当前版本不自动判定支持/反对、证据冲突或结论置信度。** 原有关键词规则无法确认问题与文献的人群、干预、对照、结局一致性，已停用。研究类型参考分级也不代表结论正确率。

## 当前能力

- 中英文查询；中文医学词典映射为英文检索词。
- 在线 PubMed 检索、BM25 排序及进程内 TTL 缓存。
- 请求失败时回退 11 篇演示语料；在线零结果保持为空。
- 规则 PICO 词项提取；尚未用于结构化检索或文献与问题的语义对齐。
- 根据标题、摘要和 PubMed 发表类型识别研究类型，展示参考分级。
- 默认抽取与查询词有重叠的摘要句，保留 PMID 供查证；相关性和句子适用性仍需人工核查。
- 已识别的撤稿文献保留在来源列表，但不进入回答或 LLM 上下文。存疑和更正同时显示告警。
- 可选 LLM 摘要整理；逐条校验实际上下文中的 PMID 和对应原句，自动生成引用。未通过时回退摘要摘录。生成摘要的语义是否受原文支持仍需人工核对。
- 可选 LightGBM 研究模型，显示 0–100 的研究分数；未校准，不代表未来撤稿概率。缺少模型或相关依赖时隐藏徽章，演示改写摘要不评分。

离线摘要是演示用改写，**不是 PMID 对应的 PubMed 原文**。界面会标识演示来源。

## 快速开始

```bash
# 仅运行检索与摘要整理
python -m pip install fastapi 'uvicorn[standard]' httpx
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

打开 `http://127.0.0.1:8000/`。网络需要代理时配置 `PUBMED_PROXY` 环境变量。

完整训练和模型依赖见 `requirements.txt`：

```bash
python -m pip install -r requirements.txt
```

### 可选 LLM

配置 `LLM_API_KEY`、`LLM_BASE_URL`（OpenAI 兼容地址）和 `LLM_MODEL` 后启用。请求失败时回退抽取式整理。

LLM 必须返回含 `pmid`、`text`、`quote` 的 JSON 条目。服务端只允许引用实际发送的摘要记录，并检查 `quote` 是该摘要片段中的连续原文。摘要正文不得夹带其他引用或链接，引用统一由服务端附加。任何条目无效则整份输出回退，避免部分无效内容被展示。

页面逐条展示摘要整理、可点击 PMID 与对应原句。校验范围是来源成员关系和原句一致性，**不等于摘要语义正确或临床适用性已验证**。不支持约定输出格式的兼容模型会回退摘录。

## API 与迁移

| 方法 | 路径 | 返回内容 |
| --- | --- | --- |
| GET | `/health` | PubMed 连通性、模型可用性、演示语料数量 |
| POST | `/api/search` | 文献、相关性、研究类型和完整性状态 |
| POST | `/api/answer` | 摘要整理、候选句、PICO 词项、来源及评估状态 |

```json
{"query": "他汀类药物会增加新发糖尿病风险吗", "retmax": 20}
```

`query` 去除首尾空白后不能为空，原始长度不超过 2000 字符；`retmax` 为 1–100。

`0.2.0` 的 `evidence` 契约：

- `assessment_version: "2"`。
- `assessment_status: "unassessed"` 表示有候选文献但未完成语义评估；`"no_usable_evidence"` 表示无可用相关文献。
- `confidence: null`、`conflict: null` 表示未评估，不能转换成 0 分或“无冲突”。
- `support_count`、`against_count`、`neutral_count` 暂为 0；未评估数量见 `unassessed_count`，不能把未评估当作中立或无效。
- 摘要句的 `polarity` 为 `"unassessed"`。前端不再展示旧版方向和分数，历史提问保留但旧判定标为停用。

`0.3.0` 新增或变更：

- 保留结果字段名 `risk`；可用时为 `{"kind":"research_model_score","score":73.0,"scale":[0,100],"calibrated":false,"description":"..."}`。`score` 从旧版 0–1 改为 0–100，删除风险 `level`；不能按概率解释。前端拒绝显示旧版概率载荷。不可用或演示语料为 null。
- LLM 模式也返回结构化 `sentences`，每项含 `sentence`、`pmid`、`title`、`quote`、`polarity`，引用编号由程序生成。
- `citation_validation`：LLM 成功时 `status="passed"`、`scope="context_membership_and_quote"`、`content_entailment="unassessed"`；摘录时为 `not_applicable` / `source_excerpts`。
- `llm_fallback_reason`：引用或格式校验失败为 `citation_validation_failed`，服务或响应异常为 `llm_unavailable`，无回退为 null。页面显示回退说明。

## 研究资产与边界

仓库含试点与全量特征表、模型文件、SHAP 图、消融及引文信号实验脚本：

- [全量模型历史报告](data/model_report_large.md)
- [引文信号历史报告](data/citation_signal_report.md)
- [多信号研究方案](docs/credibility_cross_validation.md)

以上是探索性结果。当前数据采样、发表年份删失、预测时点、PR 曲线面积和概率校准仍有待验证，不能据此认定某篇文献会在未来撤稿。`data/integrity_signals.jsonl` 为被忽略的本地产物，当前仓库不足以独立复现引文信号报告。

## 测试与后续工作

```bash
python -m unittest discover -s tests -v
node --test tests/test_ui.cjs
```

Python 测试替换外部网络服务，不需要密钥或模型依赖。GitHub Actions 在 Python 3.10 / 3.12 下验证后端，并运行前端状态回归测试。

[项目状态](docs/project_status.md) · [项目审查与优先级](docs/project_review.md)

本工具仅供研究与信息整理，不构成医疗建议。

## License

MIT
