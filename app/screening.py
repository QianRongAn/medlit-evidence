"""可解释的词项/PICO 筛选；通过只表示文本覆盖，不证明临床适用性。"""
import re

from .pico import PICO_LABEL_PATTERN, TERM_LISTS, POPULATION, normalize_text, pico_mentions, term_mentions, term_variants
from .tokenizer import tokenize
from .translate import ZH2EN, translate_query

_FILLER = (
    "能不能", "会不会", "有没有", "能否", "有无", "对于", "是否", "如何", "什么", "哪些",
    "有何", "何种", "怎样", "怎么样", "怎么", "使用", "服用", "接受", "相较", "针对",
    "以及", "或者", "相比", "比较", "对比", "有效", "效果", "影响", "作用", "能够", "不能", "吗", "呢",
)
_GENERIC = {"whether", "inhibitor", "inhibitors", "receptor", "agonist", "benefit", "benefits",
            "effective", "efficacy", "safety", "prevent", "prevention", "reduces", "increases", "improves",
            "impact", "affect", "affects", "help", "helps", "preventing", "reducing", "increasing"}
_NEGATED = re.compile(
    r"(?:\b(?:without|excluding|excluded|free of|no history of|no diagnosis of)\s+(?:[a-z0-9-]+\s+){0,3}|"
    r"\b(?:not compared (?:with|to)|no comparison with|no)\s+|"
    r"\bnon[- ]|(?:不患|未患|无|没有|排除))$", re.I)
_CONDITION_OUTCOMES = {c for c, _ in POPULATION}
_OUTCOME_BEFORE = re.compile(
    r"\b(?:(?:risk|incidence|onset|occurrence|development|prevention|rates?)(?:\s+(?:of|for))?"
    r"(?:\s+(?:new-onset|incident|first|developing|new))?|"
    r"(?:prevent(?:ed|s|ing)?|develop(?:ed|s|ing)?|reduced?|increased?|lowered?)"
    r"(?:\s+the)?(?:\s+(?:first|incident|new-onset))?|"
    r"(?:outcomes?|endpoints?)(?:\s+(?:was|were|included|including|of)){0,2})\s*$|"
    r"(?:新发|发生|发病|预防|罹患|风险|减少|增加|降低)$", re.I)
_OUTCOME_AFTER = re.compile(r"^\s*(?:risk\b|incidence\b|onset\b|events?\b|rates?\b|风险|发病|发生)")


def _unmapped_chinese(text):
    for word in sorted({zh for zh, _ in ZH2EN} | set(_FILLER), key=len, reverse=True):
        text = text.replace(word, " ")
    return re.findall(r"[\u4e00-\u9fff]+", text)


def _lexical_tokens(text):
    return list(dict.fromkeys(t for t in tokenize(text) if re.fullmatch(r"[a-z][a-z0-9-]+", t)
                             and t not in _GENERIC))


def build_query_plan(query):
    text = normalize_text(query)
    mentions = pico_mentions(query)
    pico = {field: list(dict.fromkeys(c for _, _, c in found)) for field, found in mentions.items()}
    remaining = list(text)
    for found in mentions.values():
        for start, end, _ in found:
            remaining[start:end] = " " * (end - start)
    remaining = "".join(remaining)
    unknown = _unmapped_chinese(remaining)
    for values in pico.values():
        unknown.extend(value for value in values if re.search(r"[\u4e00-\u9fff]", value))
    unknown = list(dict.fromkeys(unknown))
    tokens = _lexical_tokens(translate_query(remaining))
    ranking = list(tokens)
    for required in pico.values():
        for concept in required:
            for variant in term_variants(concept):
                ranking.extend(tokenize(variant))
    ranking = list(dict.fromkeys(t for t in ranking if re.fullmatch(r"[a-z][a-z0-9-]+", t)))
    issues = []
    if unknown:
        issues.append("unmapped_chinese_terms")
    if re.search(r"\bor\b|或者|还是", text):
        issues.append("ambiguous_alternatives")
    if re.search(r"(?<![a-z0-9])\d+(?:\.\d+)?(?![a-z0-9])", remaining):
        issues.append("unsupported_numeric_constraint")
    if any(_NEGATED.search(text[max(0, start - 55):start])
           for start, _, _ in mentions["population"]):
        issues.append("negated_population_query")
    elif (re.search(r"\b(?:without|excluding)\b", text)
          or any(_NEGATED.search(text[max(0, start - 55):start])
                 for start, _, _ in mentions["comparison"])):
        issues.append("unparsed_exclusion")
    for match in re.finditer(PICO_LABEL_PATTERN, text):
        value = match.group(2)
        if re.search(r"\b(?:without|excluding|excluded|no|not|non)\b|不患|未患|排除|没有|无", value):
            issues.append("unparsed_exclusion")
        residual = list(value)
        for values in TERM_LISTS.values():
            for concept, _ in values:
                for start, end in term_mentions(value, concept):
                    residual[start:end] = " " * (end-start)
        if re.search(r"\d", "".join(residual)):
            issues.append("unsupported_numeric_constraint")
    issues = list(dict.fromkeys(issues))
    if not any(pico.values()) and not tokens:
        issues.append("no_content_terms")
    return {"version": "2", "query": query, "pico": pico, "lexical_terms": tokens,
            "ranking_tokens": ranking, "unmapped_terms": unknown, "issues": issues,
            "note": "按已识别词项和 PICO 条件保守筛选；未识别字段不作约束，通过不代表临床适用性已验证。"}


def _positive_mentions(text, concept, reject_negation=False):
    spans = term_mentions(text, concept)
    return any(not reject_negation or not _NEGATED.search(text[max(0, start - 55):start])
               for start, _ in spans)


def _outcome_present(text, concept):
    if concept not in _CONDITION_OUTCOMES:
        return _positive_mentions(text, concept)
    # 疾病作结局时，不能用“患该病的人群”字样冒充发病/风险结局。
    return any(_OUTCOME_BEFORE.search(text[max(0, start - 65):start])
               or _OUTCOME_AFTER.search(text[end:end + 25])
               for start, end in term_mentions(text, concept))


def screen_document(doc, plan):
    abstract = normalize_text(doc.get("abstract") or "")
    text = normalize_text((doc.get("title") or "") + "\n" + (doc.get("abstract") or ""))
    fields, reasons = {}, []
    for field, required in plan["pico"].items():
        # 明确结局须在摘要中出现，不能只凭标题引入一个没有对应摘要结果的回答。
        target = abstract if field == "outcome" else text
        matched = [c for c in required if (_outcome_present(target, c) if field == "outcome"
                   else _positive_mentions(target, c, field in {"population", "comparison"}))]
        missing = [c for c in required if c not in matched]
        fields[field] = {"required": required, "matched": matched, "missing": missing}
        if missing:
            reasons.append("missing_" + field)
    words = set(_lexical_tokens(text))
    lexical = plan["lexical_terms"]
    matched_words = [t for t in lexical if t in words]
    # 词典外词项的角色未知，不能假设缺失的恰好是不重要的药物/结局。
    if len(matched_words) < len(lexical):
        reasons.append("insufficient_lexical_coverage")
    if not abstract.strip():
        reasons.append("missing_abstract")
    if plan["issues"]:
        reasons.append("unsupported_query")
    total = sum(len(v) for v in plan["pico"].values()) + len(lexical)
    hits = sum(len(f["matched"]) for f in fields.values()) + len(matched_words)
    return {"eligible": not reasons, "reasons": reasons, "pico": fields,
            "matched_terms": matched_words, "missing_terms": [t for t in lexical if t not in words],
            "coverage": round(hits / total * 100, 1) if total else 0.0}


def sentence_relevant(text, plan):
    """抽取/引文不能仅因药名命中而选入另一结局的句子。"""
    text = normalize_text(text)
    if plan["issues"]:
        return False
    free = plan["lexical_terms"]
    if not set(free) <= set(_lexical_tokens(text)):
        return False
    outcomes = plan["pico"]["outcome"]
    if outcomes:
        return any(_outcome_present(text, c) for c in outcomes)
    if free:
        return True
    anchors = plan["pico"]["intervention"] or plan["pico"]["population"] or plan["pico"]["comparison"]
    return any(_positive_mentions(text, c) for c in anchors)


def screening_summary(plan, candidates, included, excluded):
    return {"status": "unsupported_query" if plan["issues"] else "matched" if included else "no_match",
            "candidate_count": candidates, "included_count": len(included), "excluded_count": len(excluded),
            "pico_constraints": plan["pico"], "lexical_terms": plan["lexical_terms"],
            "unmapped_terms": plan["unmapped_terms"], "issues": plan["issues"], "note": plan["note"]}
