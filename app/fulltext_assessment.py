"""Outcome-scoped full-body appraisal with paragraph/table provenance."""
from copy import deepcopy
import re

from .automatic_assessment import appraise_report
from .pico import normalize_text, term_mentions
from .reported_assessment import assess_reported_findings, _aligned_context

LEVELS = {"very low":"极低", "low":"低", "moderate":"中等", "high":"高"}


def _view(doc, blocks, sections):
    view = {**doc}
    view["abstract"] = "\n".join(f"{block['section'].upper()}: {block['text']}" for block in blocks
                                 if block["section"] in sections and block["kind"] != "table_note")
    return view


def assess_fulltext(doc, plan):
    fulltext = doc.get("fulltext") or {}
    if fulltext.get("status") != "available":
        return
    blocks = fulltext["blocks"]
    # Introduction and discussion can describe another study. They do not supply effects.
    effect_blocks = [block for block in blocks if not re.search(r"\bgrade\b|quality of evidence|certainty of evidence|risk of bias", block["heading"], re.I)]
    effect_view = _view(doc, effect_blocks, {"methods", "results", "conclusion"})
    appraisal_view = _view(doc, blocks, {"methods", "results", "conclusion", "limitations"})
    abstract_reports = {report["outcome"]: report for report in doc.get("reported_assessment", [])}

    def locate(item):
        quote = item.get("quote")
        block = next((b for b in blocks if quote and quote in b["text"]), None)
        if block:
            item.update(scope="full_text", block_id=block["id"], heading=block["heading"],
                        url=fulltext["url"], text_sha256=fulltext["text_sha256"])
        return item

    reports = assess_reported_findings(effect_view, plan)
    grade_reports = {report["outcome"]: report for report in assess_reported_findings(appraisal_view, plan)}
    for report in reports:
        outcome = report["outcome"]
        report["source_certainty"] = grade_reports.get(outcome, {}).get("source_certainty", [])
        for block in blocks:
            if block["kind"] != "table" or block.get("table_layout") != "simple" or not term_mentions(normalize_text(block["text"]), outcome):
                continue
            context = normalize_text(doc.get("title", "") + " " + block["heading"] + " " + block["text"])
            # A grade table for a different drug/comparison cannot rate the current one.
            if (any(not term_mentions(context, concept) for field in ("population", "intervention", "comparison") for concept in plan["pico"][field])
                    or not _aligned_context(effect_view, plan, block["text"])):
                continue
            for header, cell in zip(block.get("headers", []), block.get("cells", [])):
                if not re.search(r"(?:certainty|quality).*evidence|\bgrade\b", header, re.I):
                    continue
                match = re.fullmatch(r"[⊕⊖◯○+\-\s]*(very[ -]low|low|moderate|high)(?:[ -]certainty)?(?:\s+[a-z0-9,]+)?", normalize_text(cell))
                if not match:
                    continue
                level = match.group(1).replace("-", " ")
                report["source_certainty"].append({"level":level, "label":LEVELS[level], "quote":block["text"],
                                                    "pmid":doc["pmid"], "kind":"outcome_grade_table"})
        for item in report["findings"] + report["source_certainty"]:
            locate(item)
        prior = abstract_reports.get(outcome, {})
        if not report["findings"] and prior.get("findings"):
            for key in ("findings", "direction", "direction_label", "alignment", "reason"):
                report[key] = deepcopy(prior.get(key))
            report["effect_scope"] = "abstract"
        else:
            report["effect_scope"] = "full_text"
        if not report["source_certainty"]:
            report["source_certainty"] = deepcopy(prior.get("source_certainty", []))
        report["automatic"] = appraise_report(appraisal_view, report, plan)
        auto = report["automatic"]
        auto["scope"] = "full_text"
        auto["source"] = {key:fulltext[key] for key in ("pmcid", "url", "xml_sha256", "text_sha256", "retrieved_at", "limitations")}
        for domain in auto["domains"].values():
            domain["reason"] = domain["reason"].replace("摘要信息不足", "当前全文信息不足")
            for item in domain["evidence"]:
                locate(item)
        certainty = auto["certainty"]
        if certainty["status"] == "limited":
            certainty["label"] = "全文资料仍有缺口"
            certainty["reason"] += " 已分析可获取的全文正文与 XML 表格；不等于已完成全文系统综述。"
        elif certainty["status"] == "preliminary":
            certainty["reason"] = "五项均有明确全文报告，按规则形成全文自动评估；尚无专家独立验证。"
        elif certainty["status"] == "source_reported":
            certainty["reason"] = "采用该结局原文明确报告的评级，见全文位置；系统未独立重做作者的 GRADE。"
    doc["reported_assessment"] = reports
