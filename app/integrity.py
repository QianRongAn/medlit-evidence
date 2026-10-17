"""PubMed 完整性状态：区分原文章、通知及重发版本，保留多状态。

关系方向依据 NLM https://www.nlm.nih.gov/bsd/policy/errata.html 。
普通评论、更新和重印关系不等于存在完整性问题。
"""

ARTICLE_RELATIONS = {
    "retractionin": "retracted",
    "retractedandrepublishedin": "retracted",
    "expressionofconcernin": "concern",
    "erratumin": "corrected",
    "correctedandrepublishedin": "corrected",
    "correctedandrepublishedfrom": "corrected",
    "retractedandrepublishedfrom": "corrected",
}
NOTICE_RELATIONS = {
    "retractionof": "retraction",
    "expressionofconcernfor": "concern",
    "erratumfor": "correction",
}
NOTICE_PUBTYPES = {
    "retraction of publication": "retraction",  # 历史名称
    "retraction notice": "retraction",
    "expression of concern": "concern",
    "published erratum": "correction",
}
ARTICLE_PUBTYPES = {
    "retracted publication": "retracted",
    "corrected and republished article": "corrected",
}


def normalize_terms(values):
    if isinstance(values, str):
        values = [values]
    return {" ".join(v.lower().split()) for v in (values or []) if isinstance(v, str)}


def integrity_details(pubtypes=None, reftypes=None):
    pts, refs = normalize_terms(pubtypes), normalize_terms(reftypes)
    flags = {ARTICLE_PUBTYPES[p] for p in pts if p in ARTICLE_PUBTYPES}
    flags.update(ARTICLE_RELATIONS[r] for r in refs if r in ARTICLE_RELATIONS)
    notices = {NOTICE_PUBTYPES[p] for p in pts if p in NOTICE_PUBTYPES}
    notices.update(NOTICE_RELATIONS[r] for r in refs if r in NOTICE_RELATIONS)
    ordered = [s for s in ("retracted", "concern", "corrected") if s in flags]
    return {
        "integrity": ordered[0] if ordered else "notice" if notices else "ok",
        "integrity_flags": ordered,
        "is_notice": bool(notices),
        "notice_types": sorted(notices),
    }


def document_integrity(doc):
    """统一源元数据和旧字段；旧的 ok 状态不能覆盖新检出的撤稿或通知。"""
    details = integrity_details(doc.get("pubtypes"), [
        r.get("ref_type", "") for r in doc.get("integrity_relations", [])])
    flags = set(details["integrity_flags"]) | set(doc.get("integrity_flags") or [])
    flags.add(doc.get("integrity", "ok"))
    details["integrity_flags"] = [s for s in ("retracted", "concern", "corrected") if s in flags]
    details["is_notice"] |= bool(doc.get("is_notice") or doc.get("integrity") == "notice")
    details["integrity"] = (details["integrity_flags"][0] if details["integrity_flags"]
                            else "notice" if details["is_notice"] else "ok")
    details["notice_types"] = sorted(set(details["notice_types"]) | (
        set(doc.get("notice_types") or []) & {"retraction", "concern", "correction"}))
    return details


def is_usable_evidence(doc):
    """撤稿原文与通知不能作为研究证据；兼容仅有旧 integrity 字段的记录。"""
    details = document_integrity(doc)
    return details["integrity"] != "retracted" and not details["is_notice"]
