"""PICO 结构化：把自然语言临床问题拆成 人群 / 干预 / 对照 / 结局 四要素。

规则驱动：基于医学词典、英文词边界及局部角色线索，不是完整的语义解析。

返回四要素各自的命中词列表；未命中的要素留空（前端显示"未明确"）。
"""

import re
import unicodedata

# 每类：英文规范词 -> 中英文变体；英文使用词边界，中文优先较长概念。
POPULATION = [
    ("type 2 diabetes", ["type 2 diabetes", "type ii diabetes", "t2dm", "2型糖尿病", "2 型糖尿病"]),
    ("type 1 diabetes", ["type 1 diabetes", "type i diabetes", "t1dm", "1型糖尿病", "1 型糖尿病"]),
    ("diabetes", ["diabetes", "diabetic", "糖尿病"]),
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
    ("children", ["children", "child", "pediatric", "paediatric", "儿童"]),
    ("adults", ["adults", "adult", "成人"]),
    ("elderly", ["elderly", "老年人"]),
]

INTERVENTION = [
    ("metformin", ["metformin", "二甲双胍"]),
    ("aspirin", ["aspirin", "阿司匹林"]),
    ("statin", ["statin", "statins", "他汀"]),
    ("sglt2 inhibitor", ["sglt2", "sglt-2", "sglt2抑制剂"]),
    ("glp-1 receptor agonist", ["glp-1", "glp1", "glp-1受体激动剂"]),
    ("pd-1 inhibitor", ["pd-1", "pd1", "pd-1抑制剂"]),
    ("nivolumab", ["nivolumab", "纳武利尤单抗", "纳武利尤"]),
    ("pembrolizumab", ["pembrolizumab", "帕博利珠单抗", "帕博利珠"]),
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
]

OUTCOME = [
    ("mortality", ["mortality", "death", "deaths", "死亡率", "死亡"]),
    ("overall survival", ["overall survival", "总生存期", "总生存"]),
    ("progression-free survival", ["progression-free survival", "progression free survival", "无进展生存期"]),
    ("cardiovascular risk", ["cardiovascular risk", "cardiovascular events", "major adverse cardiovascular", "心血管风险", "心血管事件"]),
    ("myocardial infarction", ["myocardial infarction", "心肌梗死", "心梗"]),
    ("myocarditis", ["myocarditis", "心肌炎"]),
    ("stroke", ["stroke", "脑卒中", "卒中"]),
    ("incident diabetes", ["incident diabetes", "new-onset diabetes", "new onset diabetes", "新发糖尿病"]),
    ("adverse events", ["adverse events", "adverse event", "副作用", "不良反应"]),
    ("efficacy", ["efficacy", "疗效", "有效性"]),
    ("safety", ["safety", "安全性"]),
    ("hospitalization", ["hospitalization", "hospitalisation", "住院"]),
]


TERM_LISTS = {"population": POPULATION, "intervention": INTERVENTION,
              "comparison": COMPARISON, "outcome": OUTCOME}


def normalize_text(text):
    text = unicodedata.normalize("NFKC", text or "").lower()
    return re.sub(r"[\u2010-\u2015]", "-", text)


def term_pattern(term):
    # 中文无需英文词边界；英文药名不能命中 nystatin/somatostatin 等子串。
    if re.search(r"[\u4e00-\u9fff]", term):
        return re.escape(term)
    return r"(?<![a-z0-9])" + re.escape(term).replace(r"\ ", r"\s+") + r"(?![a-z0-9])"


def term_variants(canonical):
    variants = [canonical]
    for terms in TERM_LISTS.values():
        for key, aliases in terms:
            if key == canonical:
                variants.extend(aliases)
    return sorted(set(variants))


def term_mentions(text, canonical):
    return [(m.start(), m.end()) for variant in term_variants(canonical)
            for m in re.finditer(term_pattern(normalize_text(variant)), text)]


def pico_mentions(query):
    """返回带原文位置的词典命中；同字段优先较长概念，防止泛词重复。"""
    text = normalize_text(query)
    found = {}
    for field, terms in TERM_LISTS.items():
        candidates = [(start, end, canonical) for canonical, _ in terms
                      for start, end in term_mentions(text, canonical)]
        picked = []
        for start, end, canonical in sorted(candidates, key=lambda x: (-(x[1] - x[0]), x[0])):
            if not any(start < b and end > a for a, b, _ in picked):
                picked.append((start, end, canonical))
        found[field] = sorted(picked)
    # 发病/风险结局不是已有该病的人群；明确的患者语境仍可保留为 P。
    populations = []
    for start, end, canonical in found["population"]:
        prefix, suffix = text[max(0, start - 45):start], text[end:end + 12]
        explicit_patient = bool(re.search(r"(?:patients?|people|adults?|children)\s+with\s*$", prefix)
                                or re.match(r"\s*患者", suffix))
        overlaps_outcome = any(start < b and end > a for a, b, _ in found["outcome"])
        is_risk = bool(re.search(r"(?:risk|incidence|prevention)\s+of\s*$|\bprevent(?:s|ing)?\s*$", prefix)
                       or re.search(r"(?:预防|新发|发生)\s*$", prefix)
                       or re.match(r"\s*(?:risk|incidence|风险|发病)", suffix))
        if not explicit_patient and (overlaps_outcome or is_risk):
            if not overlaps_outcome:
                found["outcome"].append((start, end, canonical))
        else:
            populations.append((start, end, canonical))
            if explicit_patient:
                found["outcome"] = [(a, b, c) for a, b, c in found["outcome"]
                                    if not (a == start and b == end and c == canonical)]
    found["population"] = populations
    marker = re.search(r"\b(?:versus|vs\.?|compared (?:with|to))\b|与(?=.{0,80}(?:相比|比较|对比))", text)
    if marker and any(end <= marker.start() for _, end, _ in found["intervention"]):
        comparators = [m for m in found["intervention"] if m[0] >= marker.end()]
        found["comparison"].extend(comparators)
        found["intervention"] = [m for m in found["intervention"] if m not in comparators]
    return found


def extract_pico(query):
    """返回 {'population','intervention','comparison','outcome': [词...]}。"""
    return {field: list(dict.fromkeys(c for _, _, c in mentions))
            for field, mentions in pico_mentions(query).items()}
