"""PICO 结构化：把自然语言临床问题拆成 人群 / 干预 / 对照 / 结局 四要素。

规则驱动（零依赖）：基于医学词典 + 中英文双向匹配。比氢离子的语义解析弱，
但可解释、可审计、离线可跑——这正符合本产品的定位（白盒、可复现）。

返回四要素各自的命中词列表；未命中的要素留空（前端显示"未明确"）。
"""

from .translate import translate_query

# 每类：英文规范词 -> 可命中的中英文变体（含大小写不敏感的子串）
POPULATION = [
    ("type 2 diabetes", ["type 2 diabetes", "t2dm", "2型糖尿病", "2 型糖尿病", "糖尿病"]),
    ("hypertension", ["hypertension", "high blood pressure", "高血压"]),
    ("heart failure", ["heart failure", "hfref", "hfpef", "心力衰竭", "心衰"]),
    ("myocardial infarction", ["myocardial infarction", "心肌梗死", "心梗"]),
    ("coronary artery disease", ["coronary artery disease", "冠心病", "冠状动脉"]),
    ("stroke", ["stroke", "脑卒中", "卒中"]),
    ("atrial fibrillation", ["atrial fibrillation", "房颤"]),
    ("melanoma", ["melanoma", "advanced melanoma", "黑色素瘤"]),
    ("colorectal cancer", ["colorectal cancer", "结直肠癌"]),
    ("breast cancer", ["breast cancer", "乳腺癌"]),
    ("lung cancer", ["lung cancer", "肺癌"]),
    ("chronic kidney disease", ["chronic kidney disease", "ckd", "慢性肾病"]),
    ("cancer", ["cancer", "癌症", "肿瘤"]),
    ("children", ["children", "pediatric", "儿童"]),
    ("adults", ["adults", "adult", "成人"]),
    ("elderly", ["elderly", "老年人"]),
]

INTERVENTION = [
    ("metformin", ["metformin", "二甲双胍"]),
    ("aspirin", ["aspirin", "阿司匹林"]),
    ("statin", ["statin", "他汀"]),
    ("sglt2 inhibitor", ["sglt2", "sglt-2", "sglt2抑制剂"]),
    ("glp-1 receptor agonist", ["glp-1", "glp1", "glp-1受体激动剂"]),
    ("pd-1 inhibitor", ["pd-1", "pd1", "pd-1抑制剂", "nivolumab", "pembrolizumab", "纳武利尤", "帕博利珠"]),
    ("immune checkpoint inhibitor", ["immune checkpoint inhibitor", "免疫检查点抑制剂"]),
    ("immunotherapy", ["immunotherapy", "免疫治疗", "免疫疗法"]),
    ("chemotherapy", ["chemotherapy", "化疗"]),
    ("radiotherapy", ["radiotherapy", "放疗"]),
    ("vaccine", ["vaccine", "疫苗"]),
    ("intensive blood pressure control", ["intensive blood pressure", "blood pressure control", "强化降压", "降压"]),
    ("anticoagulant", ["anticoagulant", "抗凝"]),
]

COMPARISON = [
    ("placebo", ["placebo", "安慰剂"]),
    ("standard care", ["standard care", "standard therapy", "usual care", "标准治疗", "常规治疗"]),
    ("versus", ["versus", " vs ", "vs.", "compared with", "compared to", "相比", "对比", "还是"]),
]

OUTCOME = [
    ("mortality", ["mortality", "death", "死亡率", "死亡"]),
    ("overall survival", ["overall survival", "总生存期", "总生存"]),
    ("progression-free survival", ["progression-free survival", "无进展生存期"]),
    ("cardiovascular risk", ["cardiovascular risk", "cardiovascular events", "major adverse cardiovascular", "心血管风险", "心血管事件"]),
    ("myocardial infarction", ["myocardial infarction", "心肌梗死", "心梗"]),
    ("stroke", ["stroke", "脑卒中", "卒中"]),
    ("incident diabetes", ["incident diabetes", "new-onset diabetes", "新发糖尿病"]),
    ("adverse events", ["adverse events", "adverse event", "副作用", "不良反应"]),
    ("efficacy", ["efficacy", "疗效", "有效性"]),
    ("safety", ["safety", "安全性"]),
    ("hospitalization", ["hospitalization", "住院"]),
]


def _pick(term_list, query_lower, en_lower):
    out = []
    for canonical, variants in term_list:
        for v in variants:
            if v in query_lower or v in en_lower:
                out.append(canonical)
                break
    return list(dict.fromkeys(out))


def extract_pico(query):
    """返回 {'population','intervention','comparison','outcome': [词...]}。"""
    q = (query or "").lower()
    en = translate_query(query or "").lower()
    return {
        "population": _pick(POPULATION, q, en),
        "intervention": _pick(INTERVENTION, q, en),
        "comparison": _pick(COMPARISON, q, en),
        "outcome": _pick(OUTCOME, q, en),
    }
