"""Automatic, outcome-specific abstract assessment with explicit missing information.

This is a reproducible preliminary appraisal, not validated clinical GRADE.
Unknown domains widen the possible grade range; they are never treated as low risk.
"""
import re

from .pico import OUTCOME, normalize_text, term_mentions
from .integrity import document_integrity
from .synthesizer import _sections, _split_sentences

LEVELS = {1: "极低", 2: "低", 3: "中等", 4: "高"}
DOMAINS = {
    "risk_of_bias": ("偏倚风险", r"\b(?:high|serious) risk of bias\b|\b(?:residual|unmeasured) confounding\b", r"\blow risk of bias\b"),
    "inconsistency": ("不一致性", r"\b(?:substantial|considerable|high) heterogeneity\b", r"\b(?:no|low|little) (?:statistical )?heterogeneity\b"),
    "indirectness": ("间接性", r"\b(?:serious indirectness|indirect evidence|surrogate (?:endpoint|outcome))s?\b", r"\bno serious indirectness\b"),
    "imprecision": ("不精确性", r"\b(?:serious imprecision|wide confidence intervals?|imprecise estimates?)\b", r"\b(?:no serious imprecision|narrow confidence intervals?)\b"),
    "publication_bias": ("发表偏倚", r"\b(?:evidence of|suspected|likely) publication bias\b", r"\bno (?:evidence of )?publication bias\b"),
}


def appraise_report(doc, report, plan):
    """Use only the outcome's own sentences and this study's methods/limitations."""
    outcome = report["outcome"]
    synthesis = doc.get("study_type") in ("meta_analysis", "systematic_review")
    design = doc.get("study_type", "other")
    methods = " ".join(chunk for label, chunk in _sections(doc.get("abstract") or "")
                       if label in ("methods", "method", "design"))
    initial = 4 if design == "randomized_controlled_trial" else 2 if design in ("cohort", "case_control") else None
    if synthesis and re.search(r"\bonly randomi[sz]ed (?:controlled )?trials\b|\bincluded \d+ randomi[sz]ed (?:controlled )?trials\b", methods, re.I) and not re.search(r"observational|non.?randomi[sz]ed|cohort", methods, re.I):
        initial = 4
    priority = 0 if synthesis else 1 if design == "randomized_controlled_trial" else 2 if design in ("cohort", "case_control", "clinical_trial") else 3
    relevant = []
    for section, chunk in _sections(doc.get("abstract") or ""):
        if section in ("background", "introduction", "objective", "objectives", "aim", "purpose"):
            continue
        for quote in _split_sentences(chunk):
            text = normalize_text(quote)
            # Generic methods from a different PICO/endpoint cannot establish certainty.
            if not all(term_mentions(text, concept) for field in ("population", "comparison") for concept in plan["pico"][field]) and section not in ("methods", "method", "design", "limitations"):
                continue
            own_outcome = bool(term_mentions(text, outcome))
            if own_outcome or section in ("methods", "method", "design", "limitations"):
                # Outcome-specific signals take precedence over generic methods.
                target_ranges = term_mentions(text, outcome)
                if any(other != outcome and any(not any(a < y and b > x for x, y in target_ranges)
                       for a, b in term_mentions(text, other)) for other, _ in OUTCOME):
                    continue
                relevant.append((text, quote))
    domains = {}
    for key, (label, negative, positive) in DOMAINS.items():
        signals = []
        for text, quote in relevant:
            for status, pattern in (("not_serious", positive), ("serious", negative)):
                for match in re.finditer(pattern, text):
                    if status == "serious" and re.search(r"\b(?:no|not|without)\b[^.;]{0,25}$", text[max(0, match.start()-30):match.start()]):
                        continue
                    if status == "not_serious" and (re.search(r"\b(?:not|without|uncertain|unclear|unable|cannot)\b[^.;]{0,30}$", text[max(0,match.start()-40):match.start()])
                                                    or re.match(r"\s+(?:(?:was|were|is|could|can|has|had|have|be)\s+){0,3}not\b",text[match.end():])):
                        continue
                    signals.append({"status": status, "quote": quote, "pmid": doc["pmid"]})
        statuses = {signal["status"] for signal in signals}
        status = next(iter(statuses)) if len(statuses) == 1 else "unknown"
        domains[key] = {"label": label, "status": status, "evidence": signals,
                        "reason": "原文有可追溯的明确报告" if status != "unknown" else "摘要信息不足或报告冲突，未按无风险处理"}
    for finding in report.get("findings", []):
        if re.search(r"\b(?:ci|confidence interval)\b", finding["quote"], re.I):
            domain = domains["imprecision"]
            if not any(item["quote"] == finding["quote"] for item in domain["evidence"]):
                domain["evidence"].append({"status":"information", "quote":finding["quote"], "pmid":doc["pmid"]})
            if domain["status"] == "unknown":
                domain["reason"] = "已提取效应置信区间；缺少临床重要差异阈值或最优信息量，不能仅凭统计显著判定精确性"
    if "concern" in document_integrity(doc)["integrity_flags"]:
        domains["risk_of_bias"].update(status="serious", reason="出版记录存在存疑标记，降低可信度上界")
        domains["risk_of_bias"]["evidence"].append({"status":"serious", "pmid":doc["pmid"],
                                                   "quote":"", "metadata":"出版记录存在存疑标记"})
    # A null-crossing interval signals direction uncertainty, not automatic GRADE downgrade.
    serious = sum(domain["status"] == "serious" for domain in domains.values())
    unknown = sum(domain["status"] == "unknown" for domain in domains.values())
    upper = max(1, initial - serious) if initial else None
    lower = max(1, upper - 2*unknown) if upper else None
    certainty = {"status": "limited", "label": "可信度受限", "level": None,
                 "lower": LEVELS.get(lower), "upper": LEVELS.get(upper),
                 "reason": f"自动核查发现 {serious} 项明确局限、{unknown} 项资料缺口；未知项不视为通过。"}
    if not report.get("direction"):
        certainty.update(label="结论依据不足", reason="未能从当前摘要可靠提取对齐 PICO 的结局效应。")
    elif report.get("source_certainty"):
        levels = {item["level"] for item in report["source_certainty"]}
        certainty.update(status="source_reported", label=" / ".join(sorted({item["label"] for item in report["source_certainty"]})),
                         level=next(iter(levels)) if len(levels) == 1 else None,
                         reason="采用该结局原文明确报告的评级；系统未独立重做全文 GRADE。")
    elif initial and unknown == 0:
        certainty.update(status="preliminary", label=LEVELS[upper], level={1:"very low", 2:"low", 3:"moderate", 4:"high"}[upper],
                         reason="五项均有明确摘要报告，按证据起点和明确局限自动形成初评，尚未全文复核。")
    return {"version": "1", "priority": priority, "design": design,
            "initial": LEVELS.get(initial), "domains": domains, "certainty": certainty}


def summarize_automatic(docs, outcomes):
    """Describe the strongest available design tier without counting votes or pooling overlaps."""
    results = []
    for outcome in outcomes:
        items = [(doc, report) for doc in docs for report in doc.get("reported_assessment", [])
                 if report["outcome"] == outcome and report.get("direction") and report.get("automatic")]
        if not items:
            results.append({"outcome": outcome, "direction": None, "label": "当前结论依据不足", "references": []})
            continue
        priority = min(report["automatic"]["priority"] for _, report in items)
        selected = [(doc, report) for doc, report in items if report["automatic"]["priority"] == priority]
        directions = {report["direction"] for _, report in selected}
        clear = directions & {"increase", "decrease"}
        direction = "mixed" if len(clear) > 1 or "mixed" in directions else next(iter(clear)) if clear else "uncertain"
        labels = {"increase": "现有证据提示增加", "decrease": "现有证据提示减少", "uncertain": "现有证据尚不能确定方向", "mixed": "现有证据方向不一致"}
        results.append({"outcome": outcome, "direction": direction, "label": labels[direction],
                        "has_uncertain_reports": "uncertain" in directions,
                        "references": [doc["pmid"] for doc, _ in selected], "priority": priority,
                        "note": "按可用研究设计层级选择方向依据；未按篇数投票，未合并可能重叠的研究。"})
    return results
