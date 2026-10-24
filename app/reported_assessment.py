"""Traceable outcome-specific findings reported by abstracts, not a clinical verdict.

No vote-count pooling, causal inference or calibrated probability is performed.
"""
import re

from .integrity import is_usable_evidence
from .pico import OUTCOME, normalize_text, term_mentions
from .synthesizer import _answer_sentences, _sections, WEAK_LABELS

_LABELS = {"increase": "报告增加", "decrease": "报告减少", "uncertain": "未见明确方向", "mixed": "原文方向不一致"}
_CHANGE = re.compile(r"\b(increas(?:e[ds]?|ing)|higher|rais(?:e[ds]?|ing)|elevat(?:e[ds]?|ing)|reduc(?:e[ds]?|ing)|decreas(?:e[ds]?|ing)|lower(?:ed)?|declin(?:e[ds]?|ing))\b")
_UNCERTAIN = re.compile(r"\b(?:may|might|could|possibly|uncertain|unclear|inconclusive|not statistically significant|no significant|no clear|no evidence|did not|does not|not associated|no difference|not unlikely|unlikely)\b")
_GRADE = re.compile(r"\b(very[ -]low|low|moderate|high)[ -](?:certainty|quality)(?:[ -]of)?[ -]evidence\b|\b(very[ -]low|low|moderate|high)[ -]certainty\b.{0,35}\b(?:evidence|grade)\b")
_LEVELS = {"high":"高", "moderate":"中等", "low":"低", "very low":"极低"}


def _interval_crosses_null(text):
    ratio=re.search(r"\b(?:or|rr|hr|ahr|aor|odds ratio|risk ratio|hazard ratio|rate ratio)\b",text)
    difference=re.search(r"\b(?:mean|risk|absolute) difference\b",text)
    if not ratio and not difference:
        return False
    null=1.0 if ratio else 0.0
    intervals=re.findall(r"\b(?:ci|confidence interval)\b[\s,\[\]():=]*(-?\d*\.?\d+)\s*(?:-|to|,)\s*(-?\d*\.?\d+)",text)
    return any(float(low)<=null<=float(high) for low,high in intervals)


def _aligned_context(doc, plan, quote):
    # Background mentions cannot establish a trial's actual P/I/C.
    context = quote + " " + " ".join(chunk for label,chunk in _sections(doc.get("abstract") or "")
                                      if label in {"methods","method","participants","interventions","design"})
    text = normalize_text(context)
    quote_text=normalize_text(quote)
    opposites={"adults":"children","children":"adults","type 1 diabetes":"type 2 diabetes","type 2 diabetes":"type 1 diabetes"}
    for concept in plan["pico"]["population"]:
        if concept in opposites and term_mentions(quote_text,opposites[concept]):
            return False
    for field in ("population","comparison"):
        if any(not term_mentions(text,concept) for concept in plan["pico"][field]):
            return False
    return True


def _direction(clause, outcome, intervention, comparison):
    text=normalize_text(clause)
    targets=term_mentions(text,outcome)
    if not targets or re.search(r"\b(?:which|unlike|in contrast to)\b",text):
        return None
    # Two different named outcomes in one clause cannot share one effect label.
    target_ranges=targets
    for other,_ in OUTCOME:
        if other==outcome:
            continue
        if any(not any(a < y and b > x for x,y in target_ranges) for a,b in term_mentions(text,other)):
            return None
    anchors=[span for concept in intervention for span in term_mentions(text,concept)]
    if not anchors:
        return None
    uncertain = bool(_UNCERTAIN.search(text)) or _interval_crosses_null(text)
    changes=[]
    for effect in _CHANGE.finditer(text):
        # The intervention must precede the effect; comparator-only mentions do not suffice.
        if not any(end<=effect.start() and effect.start()-end<100 for _,end in anchors):
            continue
        last_anchor=max((end for _,end in anchors if end<=effect.start()),default=-1)
        if any(last_anchor < start < effect.start() for concept in comparison for start,_ in term_mentions(text,concept)):
            continue
        if not any(0 <= start-effect.end() < 90 for start,_ in targets):
            continue
        if uncertain or re.search(r"\b(?:not|never|no)\b",text[max(0,effect.start()-18):effect.start()]):
            changes.append("uncertain")
        else:
            changes.append("increase" if re.match(r"increas|higher|rais|elevat",effect.group()) else "decrease")
    if not changes:
        if uncertain and any(0 <= start-end < 150 for _,end in anchors for start,_ in targets):
            return "uncertain"
        return None
    if len(set(changes))>1:
        return "mixed"
    return changes[0]


def assess_reported_findings(doc, plan):
    """Return original quotes and conservative abstention reasons for each asked outcome."""
    reports=[]
    if not is_usable_evidence(doc) or doc.get("source")!="pubmed":
        return reports
    for outcome in plan["pico"]["outcome"]:
        findings=[]
        certainty=[]
        for section,quote in _answer_sentences(doc.get("abstract") or ""):
            if not term_mentions(normalize_text(quote),outcome) or not _aligned_context(doc,plan,quote):
                continue
            # Do not transfer certainty or effect labels across contrasted outcomes.
            for clause in re.split(r";(?!\s*(?:\d{2}\s*%|ci\b|confidence\b))|\bbut\b|\bwhereas\b|\bwhile\b",quote,flags=re.I):
                text=normalize_text(clause)
                if not term_mentions(text,outcome):
                    continue
                others=[other for other,_ in OUTCOME if other!=outcome
                    and any(not any(a<y and b>x for x,y in term_mentions(text,outcome)) for a,b in term_mentions(text,other))]
                matches=list(_GRADE.finditer(text)) if not others else []
                if len(matches)==1:
                    match=matches[0]
                    negated=re.search(r"\b(?:no|not|without|lack(?:ing|s)?)\b",text[max(0,match.start()-30):match.start()])
                    if not negated:
                        level=(match.group(1) or match.group(2)).replace("-"," ")
                        certainty.append({"level":level,"label":_LEVELS[level],"quote":quote,"pmid":doc.get("pmid")})
                direction=_direction(clause,outcome,plan["pico"]["intervention"],plan["pico"]["comparison"])
                if direction:
                    findings.append({"direction":direction,"label":_LABELS[direction],"quote":quote,
                                     "section":section,"pmid":doc.get("pmid")})
        distinct={item["direction"] for item in findings}
        direction=next(iter(distinct)) if len(distinct)==1 else "mixed" if distinct else None
        requested=question_direction(plan.get("query", ""),outcome)
        alignment=("same_direction" if direction==requested else "opposite_direction") if requested and direction in ("increase","decrease") else None
        reports.append({"outcome":outcome,"direction":direction,"direction_label":_LABELS.get(direction,"缺少可核对的结局方向"),
                        "question_direction":requested,"alignment":alignment,
                        "findings":findings,"source_certainty":certainty,
                        "reason":None if findings else "摘要未提供同时覆盖已指定 PICO 的明确方向句；需核对全文。"})
    return reports


def question_direction(query,outcome):
    text=normalize_text(query)
    targets=term_mentions(text,outcome)
    verbs=list(re.finditer(r"\b(?:increas\w*|rais\w*|reduc\w*|decreas\w*|lower\w*)\b|增加|升高|降低|减少",text))
    for start,_ in targets:
        before=[verb for verb in verbs if 0<=start-verb.end()<100]
        if before:
            verb=before[-1]
            if re.search(r"\bnot\b|不|没有",text[max(0,verb.start()-12):verb.start()]):
                return None
            return "increase" if re.match(r"increas|rais|增加|升高",verb.group()) else "decrease"
    return None


def reported_summary(docs,plan):
    items=[]
    for doc in docs:
        reports=assess_reported_findings(doc,plan)
        doc["reported_assessment"]=reports
        items.extend(reports)
    return {"scope":"reported_abstract_findings","items":items,
            "note":"方向是具体结局在原文中的报告，不代表因果证明；原文 GRADE 评级注明来源，不按篇数或研究类型计算可信概率。"}


GRADE_DOMAINS=("risk_of_bias","inconsistency","indirectness","imprecision","publication_bias")


def grade_review(initial,domains,references):
    """A user-authored GRADE downgrade worksheet; missing domains remain explicitly incomplete."""
    missing=[key for key in GRADE_DOMAINS if domains.get(key,{}).get("severity") not in ("not_serious","serious","very_serious")
             or not domains[key].get("rationale","").strip()]
    if not references:
        missing.append("references")
    if initial not in ("randomized","observational"):
        missing.append("initial_evidence")
    if missing:
        return {"status":"incomplete","level":None,"label":"评估资料待补齐","missing":missing,"source":"user_review"}
    downgrades=sum({"not_serious":0,"serious":1,"very_serious":2}[domains[key]["severity"]] for key in GRADE_DOMAINS)
    score=max(1,(4 if initial=="randomized" else 2)-downgrades)
    level={4:"high",3:"moderate",2:"low",1:"very low"}[score]
    return {"status":"completed","level":level,"label":_LEVELS[level],"downgrade_levels":downgrades,
            "source":"user_review","references":references,
            "note":"人工填写的 GRADE 降级评估草案，未独立审核；未包含观察性证据升级因素，不是系统自动校准的概率。"}
