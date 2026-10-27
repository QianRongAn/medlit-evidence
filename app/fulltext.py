"""Identity-checked Europe PMC open-access JATS acquisition and section/table parsing."""
import asyncio
from collections import OrderedDict
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import re
import time
import xml.etree.ElementTree as ET

import httpx

from .config import PUBMED_PROXY
from .integrity import is_usable_evidence

BASE = "https://www.ebi.ac.uk/europepmc/webservices/rest"
MAX_BYTES = 8 * 1024 * 1024
_CACHE = OrderedDict()


def _text(node):
    return re.sub(r"\s+", " ", "".join(node.itertext())).strip() if node is not None else ""


def _section(title):
    text = title.lower()
    for label, pattern in (("methods", r"method|design|risk.of.bias|quality assessment|statistical|eligibility"),
                           ("results", r"result|finding|summary.of.findings|certainty.of.evidence|quality.of.evidence|\bgrade\b"),
                           ("limitations", r"limitation|strength.*weakness"),
                           ("conclusion", r"conclusion|interpretation"),
                           ("discussion", r"discussion"), ("background", r"introduction|background")):
        if re.search(pattern, text):
            return label
    return "other"


def parse_jats(xml, pmid, pmcid):
    raw = xml.encode() if isinstance(xml, str) else xml
    if len(raw) > MAX_BYTES or b"<!ENTITY" in raw.upper():
        raise ValueError("oversized_or_unsafe_xml")
    root = ET.fromstring(raw)
    for node in root.iter():
        node.tag = node.tag.rsplit("}", 1)[-1]
    if root.tag != "article":
        raise ValueError("not_article_xml")
    ids = {node.get("pub-id-type"): _text(node) for node in root.findall("./front/article-meta/article-id")}
    if ids.get("pmid") != str(pmid):
        raise ValueError("pmid_identity_mismatch")
    xml_pmc = ids.get("pmc") or ids.get("pmcid")
    if xml_pmc and "PMC" + xml_pmc.removeprefix("PMC") != pmcid:
        raise ValueError("pmcid_identity_mismatch")
    body = root.find("body")
    if body is None:
        raise ValueError("body_unavailable")
    blocks = []

    def add(text, section, heading, kind, **extra):
        if text:
            blocks.append({"id": f"b{len(blocks)+1:05}", "section": section, "heading": heading,
                           "kind": kind, "text": text, **extra})

    def table(node, section, heading):
        caption = _text(node.find("caption"))
        rows = node.findall(".//tr")
        header_rows = node.findall(".//thead/tr")
        complex_layout = any(cell.get("rowspan", "1") != "1" or cell.get("colspan", "1") != "1"
                             for cell in node.iter() if cell.tag in ("th", "td"))
        headers = []
        for row in rows:
            cells = [_text(cell) for cell in row if cell.tag in ("th", "td")]
            if not cells:
                continue
            if row in header_rows or row.findall("th"):
                headers = cells
                continue
            text = " | ".join(f"{headers[i] if i < len(headers) else 'Column '+str(i+1)}: {cell}" for i, cell in enumerate(cells))
            add(text, section, heading + " / " + caption, "table", headers=headers[:], cells=cells,
                table_layout="complex" if complex_layout or len(headers) != len(cells) else "simple")
        footnotes = _text(node.find("table-wrap-foot"))
        if footnotes:
            add(footnotes, section, heading + " / " + caption, "table_note")

    def walk(node, section="other", heading="正文"):
        for child in node:
            if child.tag == "sec":
                title = _text(child.find("title")) or heading
                kind = _section(title)
                walk(child, kind if kind != "other" else section, title)
            elif child.tag == "table-wrap":
                table(child, section, heading)
            elif child.tag == "p":
                add(_text(child), section, heading, "paragraph")
            elif child.tag not in ("title", "ref-list", "supplementary-material", "fig"):
                walk(child, section, heading)

    walk(body)
    for extra in (root.find("floats-group"), root.find("back")):
        if extra is not None:
            walk(extra, "other", "正文附表及附录")
    if not blocks:
        raise ValueError("empty_body")
    canonical = "\n".join(f"{block['id']}\t{block['heading']}\t{block['text']}" for block in blocks)
    return {"status": "available", "pmid": str(pmid), "pmcid": pmcid,
            "url": f"https://europepmc.org/articles/{pmcid}", "source": "europe_pmc_open_access",
            "license": _text(root.find("./front/article-meta/permissions/license")),
            "xml_sha256": hashlib.sha256(raw).hexdigest(),
            "text_sha256": hashlib.sha256(canonical.encode()).hexdigest(),
            "retrieved_at": datetime.now(timezone.utc).isoformat(), "blocks": blocks,
            "scope": "article_body_and_xml_tables", "limitations": "图像、外部补充文件及复杂合并表头的列映射未解析，不视为已审阅"}


async def _download(client, url):
    async with client.stream("GET", url) as response:
        response.raise_for_status()
        chunks, size = [], 0
        async for chunk in response.aiter_bytes():
            size += len(chunk)
            if size > MAX_BYTES:
                raise ValueError("fulltext_too_large")
            chunks.append(chunk)
        return b"".join(chunks)


async def fetch_fulltext(pmid, client=None):
    if not re.fullmatch(r"[1-9][0-9]{0,9}", str(pmid)):
        raise ValueError("invalid_pmid")
    cached = _CACHE.get(str(pmid))
    if cached and cached[0] > time.monotonic():
        return deepcopy(cached[1])
    if client is None:
        kwargs = {"timeout": 20, "trust_env": False, "follow_redirects": False}
        if PUBMED_PROXY:
            kwargs["proxy"] = PUBMED_PROXY
        async with httpx.AsyncClient(**kwargs) as owned:
            return await fetch_fulltext(pmid, owned)
    try:
        response = await client.get(BASE + "/search", params={"query": f"EXT_ID:{pmid} AND SRC:MED", "format": "json"})
        response.raise_for_status()
        matches = [item for item in response.json().get("resultList", {}).get("result", [])
                   if str(item.get("id")) == str(pmid) and item.get("source") == "MED"]
        item = matches[0] if len(matches) == 1 else {}
        pmcid = item.get("pmcid", "")
        if item.get("isOpenAccess") != "Y" or not re.fullmatch(r"PMC[1-9][0-9]*", pmcid):
            result = {"status": "unavailable", "reason": "无可通过开放接口获取的全文", "pmid": str(pmid)}
        else:
            result = parse_jats(await _download(client, BASE + f"/{pmcid}/fullTextXML"), str(pmid), pmcid)
    except (httpx.HTTPError, ET.ParseError, ValueError, KeyError) as error:
        return {"status": "error", "reason": type(error).__name__ + ": 全文获取或身份校验失败，可重试", "pmid": str(pmid)}
    _CACHE[str(pmid)] = (time.monotonic() + 3600, deepcopy(result))
    _CACHE.move_to_end(str(pmid))
    while len(_CACHE) > 64:
        _CACHE.popitem(last=False)
    return result


async def enrich_fulltexts(docs):
    semaphore = asyncio.Semaphore(3)

    async def enrich(doc):
        if doc.get("source") != "pubmed" or not is_usable_evidence(doc):
            doc["fulltext"] = {"status": "excluded", "reason": "演示、撤稿或通知不用于全文评估"}
            return
        async with semaphore:
            doc["fulltext"] = await fetch_fulltext(doc["pmid"])
    await asyncio.gather(*(enrich(doc) for doc in docs))


def fulltext_metadata(fulltext):
    return {key: value for key, value in (fulltext or {}).items() if key != "blocks"}
