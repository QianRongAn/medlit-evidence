"""中文医学术语 → 英文检索词映射，支持中文自然语言提问。

PubMed 以英文为主，中文提问需要先翻译成英文检索词才能召回。
这里用最长匹配做术语替换，其余中文语气词/虚词丢弃，英文单词原样保留。
"""

ZH2EN = [
    ("免疫检查点抑制剂", "immune checkpoint inhibitor"),
    ("无进展生存期", "progression-free survival"),
    ("总生存期", "overall survival"),
    ("心肌梗死", "myocardial infarction"),
    ("心力衰竭", "heart failure"),
    ("冠状动脉粥样硬化性心脏病", "coronary artery disease"),
    ("高血压", "hypertension"),
    ("高脂血症", "hyperlipidemia"),
    ("二甲双胍", "metformin"),
    ("阿司匹林", "aspirin"),
    ("黑色素瘤", "melanoma"),
    ("结直肠癌", "colorectal cancer"),
    ("乳腺癌", "breast cancer"),
    ("肺癌", "lung cancer"),
    ("心血管", "cardiovascular"),
    ("冠心病", "coronary artery disease"),
    ("脑卒中", "stroke"),
    ("心衰", "heart failure"),
    ("心梗", "myocardial infarction"),
    ("肿瘤", "tumor"),
    ("癌症", "cancer"),
    ("免疫治疗", "immunotherapy"),
    ("免疫疗法", "immunotherapy"),
    ("糖尿病", "diabetes"),
    ("他汀", "statin"),
    ("疫苗", "vaccine"),
    ("化疗", "chemotherapy"),
    ("放疗", "radiotherapy"),
    ("降压", "blood pressure lowering"),
    ("血糖", "blood glucose"),
    ("胆固醇", "cholesterol"),
    ("生存期", "survival"),
    ("预防", "prevention"),
    ("治疗", "treatment"),
    ("患者", "patients"),
    ("风险", "risk"),
    ("降低", "reduce"),
    ("增加", "increase"),
    ("改善", "improve"),
    ("卒中", "stroke"),
    ("获益", "benefit"),
    ("疗效", "efficacy"),
    ("安全性", "safety"),
    ("副作用", "adverse events"),
    ("pd-1", "pd1"),
    ("pd-l1", "pdl1"),
    ("sglt2", "sglt2"),
    ("是否", "whether"),
    ("哪些", ""),
    ("什么", ""),
    ("怎么", "how"),
    ("怎么样", ""),
    ("为什么", "why"),
    ("还是", "or"),
    ("与", "and"),
    ("和", "and"),
    ("比", "versus"),
    ("相比", "versus"),
    ("的", ""),
    ("了", ""),
    ("吗", ""),
    ("呢", ""),
    ("能", ""),
    ("可以", ""),
    ("会", ""),
    ("对", ""),
    ("在", ""),
    ("有", ""),
    ("是", ""),
]


def translate_query(text):
    """把中文提问转成英文检索串。最长匹配优先。"""
    if not text:
        return text
    # 保留原文本里的英文/数字，中文按词典替换
    out = []
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        # 英文/数字直接保留（跳过空格分隔的英文单词块）
        if ch.isascii() and (ch.isalnum() or ch == "-"):
            j = i
            while j < n and (text[j].isalnum() or text[j] == "-"):
                j += 1
            out.append(text[i:j])
            i = j
            continue
        if "\u4e00" <= ch <= "\u9fff":
            matched = False
            for zh, en in ZH2EN:
                if text.startswith(zh, i):
                    if en:
                        out.append(en)
                    i += len(zh)
                    matched = True
                    break
            if matched:
                continue
            # 未匹配的单个汉字丢弃
            i += 1
            continue
        i += 1
    return " ".join(x for x in out if x).strip()
