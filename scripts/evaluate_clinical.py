"""Frozen closed-corpus ASGI benchmark. Model-authored labels are not expert gold."""
import argparse
import asyncio
from copy import deepcopy
import csv
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import unicodedata
from unittest.mock import AsyncMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
FIELDS = ("population", "intervention", "comparison", "outcome")


def digest(value):
    if not isinstance(value, bytes):
        value = json.dumps(value, ensure_ascii=False, sort_keys=True).encode()
    return hashlib.sha256(value).hexdigest()


def text_digest(content, newline=b"\n"):
    """Hash logical UTF-8 text independent of Git autocrlf.

    v1 source hashes were frozen from a Windows CRLF checkout. Recreate that
    canonical representation when verifying them, preserving original hashes.
    Application/evaluator fingerprints use canonical LF instead.
    """
    return digest(content.replace(b"\r\n", b"\n").replace(b"\n", newline))


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_json(path, value):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def load_benchmark(folder):
    folder = Path(folder)
    manifest = read_json(folder / "manifest.json")
    for name in ("corpus.json", "queries.json", "judgments.csv"):
        if text_digest((folder / name).read_bytes(), b"\r\n") != manifest["files"].get(name):
            raise ValueError("frozen benchmark changed: " + name)
    corpus, queries = read_json(folder / "corpus.json"), read_json(folder / "queries.json")
    ids = [str(d["pmid"]) for d in corpus]
    qids = [q["id"] for q in queries]
    if len(set(ids)) != len(ids) or len(set(qids)) != len(qids) or not ids or not qids:
        raise ValueError("empty or duplicate benchmark IDs")
    if len({q["query"] for q in queries}) != len(queries):
        raise ValueError("duplicate questions")
    for q in queries:
        if set(q["gold_pico"]) != set(FIELDS):
            raise ValueError("all four PICO fields required")
        if not set(q["pico_matched_pmids"]) <= set(q["topic_relevant_pmids"]) <= set(ids):
            raise ValueError("invalid judgment reference")
    with (folder / "judgments.csv").open(encoding="utf-8-sig", newline="") as source:
        judgments = list(csv.DictReader(source))
    expected = {(q["id"], p) for q in queries for p in ids}
    if len(judgments) != len(expected) or {(r["query_id"], r["pmid"]) for r in judgments} != expected:
        raise ValueError("incomplete/duplicate judgment pool")
    lookup = {q["id"]: q for q in queries}
    for row in judgments:
        q = lookup[row["query_id"]]
        if (row["topic_relevant"] != str(int(row["pmid"] in q["topic_relevant_pmids"]))
                or row["pico_match"] != str(int(row["pmid"] in q["pico_matched_pmids"]))):
            raise ValueError("CSV/JSON judgments disagree")
    return manifest, corpus, queries


def check_independence(corpus, queries):
    ids = {str(d["pmid"]) for d in corpus}
    for name in ("features.csv", "features_large.csv"):
        with (ROOT / "data" / name).open(encoding="utf-8") as source:
            train_ids = {row["pmid"] for row in csv.DictReader(source)}
        if ids & train_ids:
            raise ValueError("benchmark/training PMID overlap: " + name)
    tests = "\n".join(p.read_text(encoding="utf-8") for p in (ROOT / "tests").glob("test_*.py"))
    if any(q["query"] in tests for q in queries):
        raise ValueError("benchmark question already in unit-test source")


def claim_id(query_id, sentence):
    return digest({"query_id": query_id, "sentence": sentence})


def payload_hash(run):
    return digest({k: v for k, v in run.items() if k != "run_sha256"})


async def run_benchmark(folder, output, mode="extractive"):
    import httpx
    from app import main
    manifest, corpus, queries = load_benchmark(folder)
    check_independence(corpus, queries)
    if Path(output).exists() or Path(output).with_suffix(".review.json").exists():
        raise FileExistsError("choose a new --output; preserve previous runs and reviews")
    if mode == "llm" and not main.LLM_API_KEY:
        raise ValueError("LLM mode requires configured credentials; never substitute extractive results")
    code = {p.name: text_digest(p.read_bytes()) for p in sorted((ROOT / "app").glob("*.py"))}
    run = {"benchmark_sha256": digest(manifest), "application_sha256": digest(code),
           "evaluator_sha256": text_digest(Path(__file__).read_bytes()),
           "hash_normalization": {"frozen_v1_files": "UTF-8 CRLF", "source_code": "UTF-8 LF"},
           "git_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
           "mode_requested": mode, "scope": manifest["scope"], "retmax": manifest["retrieval_k"],
           "annotation_kind": manifest["annotation_kind"], "expert_review_status": manifest["expert_review_status"],
           "cases": []}
    key = main.LLM_API_KEY if mode == "llm" else ""
    # Run actual offline BM25 -> screening -> ASGI answer pipeline on frozen
    # source documents. Only external acquisition and research risk scores are
    # replaced; do not patch ranking, PICO, screening, or answer functions.
    with patch.object(main, "esearch", AsyncMock(side_effect=OSError("frozen offline benchmark"))), \
         patch.object(main, "load_corpus", side_effect=lambda _: deepcopy(corpus)), \
         patch.object(main, "predict_risk", return_value=None), patch.object(main, "LLM_API_KEY", key):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url="http://benchmark") as client:
            for q in queries:
                request = {"query": q["query"], "retmax": manifest["retrieval_k"]}
                search = await client.post("/api/search", json=request)
                answer = await client.post("/api/answer", json=request)
                search.raise_for_status()
                answer.raise_for_status()
                s, a = search.json(), answer.json()
                if [d["pmid"] for d in s["results"]] != [d["pmid"] for d in a["results"]]:
                    raise ValueError("search/answer candidate drift")
                run["cases"].append({"query_id": q["id"], "pico": s["pico"],
                    "results": [d["pmid"] for d in s["results"]], "screening": s["screening"],
                    "mode": a["mode"], "sentences": a["sentences"],
                    "fallback_reason": a["llm_fallback_reason"]})
    run["run_sha256"] = payload_hash(run)
    write_json(output, run)
    review = {"run_sha256": run["run_sha256"], "reviewer": "", "reviewer_kind": "pending",
              "items": [{"claim_id": claim_id(c["query_id"], s), "query_id": c["query_id"],
                         "sentence": s, "faithful": None, "answers_question": None,
                         "rationale": ""} for c in run["cases"] for s in c["sentences"]]}
    write_json(Path(output).with_suffix(".review.json"), review)
    return run


def ratio(n, d):
    return {"numerator": n, "denominator": d, "rate": n / d if d else None}


def normalized(items):
    return {unicodedata.normalize("NFKC", x).lower().strip() for x in items}


def score_cases(queries, cases, reviews):
    counts = dict(returned=0, topic=0, matched=0, expected=0, hits=0,
                  answerable=0, nonempty=0, success=0, no_evidence=0, correct_abstention=0,
                  pico_exact=0, faithful=0, judged=0, claims=0, responsive=0,
                  responsive_queries=0, supported_answer_queries=0)
    fields = {field: {"tp": 0, "fp": 0, "fn": 0, "exact": 0} for field in FIELDS}
    for q, c in zip(queries, cases):
        returned = c["results"]
        matched = set(q["pico_matched_pmids"])
        counts["returned"] += len(returned)
        counts["topic"] += len(set(returned) & set(q["topic_relevant_pmids"]))
        hits = len(set(returned) & matched)
        counts["matched"] += hits
        counts["expected"] += len(matched)
        counts["hits"] += hits
        counts["answerable"] += bool(matched)
        counts["success"] += bool(hits)
        counts["nonempty"] += bool(c["sentences"]) and bool(matched)
        counts["no_evidence"] += not matched
        counts["correct_abstention"] += not matched and not c["sentences"]
        exact = True
        for field in FIELDS:
            gold, predicted = normalized(q["gold_pico"][field]), normalized(c["pico"][field])
            fields[field]["tp"] += len(gold & predicted)
            fields[field]["fp"] += len(predicted - gold)
            fields[field]["fn"] += len(gold - predicted)
            fields[field]["exact"] += gold == predicted
            exact &= gold == predicted
        counts["pico_exact"] += exact
        responsive_query, supported_query = False, False
        for sentence in c["sentences"]:
            counts["claims"] += 1
            review = reviews.get(claim_id(q["id"], sentence))
            if review and type(review["faithful"]) is bool and type(review["answers_question"]) is bool:
                counts["judged"] += 1
                counts["faithful"] += review["faithful"]
                counts["responsive"] += review["answers_question"]
                responsive_query |= review["answers_question"]
                # Empty output and merely on-topic methods do not earn success.
                supported_query |= (review["faithful"] and review["answers_question"]
                                    and sentence["pmid"] in matched)
        counts["responsive_queries"] += bool(matched) and responsive_query
        counts["supported_answer_queries"] += bool(matched) and supported_query
    fully_reviewed = counts["judged"] == counts["claims"]
    return {"query_n": len(queries),
            "topic_precision_at_5": ratio(counts["topic"], counts["returned"]),
            "pico_document_match_at_5": ratio(counts["matched"], counts["returned"]),
            "closed_pool_recall_at_5": ratio(counts["hits"], counts["expected"]),
            "answerable_query_hit_at_5": ratio(counts["success"], counts["answerable"]),
            "pico_query_exact": ratio(counts["pico_exact"], len(queries)),
            "answer_coverage": ratio(counts["nonempty"], counts["answerable"]),
            "no_evidence_abstention": ratio(counts["correct_abstention"], counts["no_evidence"]),
            "claim_review_coverage": ratio(counts["judged"], counts["claims"]),
            "summary_faithfulness": ratio(counts["faithful"], counts["judged"]) if fully_reviewed else None,
            "summary_responsiveness": ratio(counts["responsive"], counts["judged"]) if fully_reviewed else None,
            "supported_answer_coverage": ratio(counts["supported_answer_queries"], counts["answerable"]) if fully_reviewed else None,
            "pico_fields": fields}


def score_benchmark(folder, run_path, review_path=None):
    manifest, corpus, queries = load_benchmark(folder)
    run = read_json(run_path)
    if run.get("run_sha256") != payload_hash(run) or run["benchmark_sha256"] != digest(manifest):
        raise ValueError("run or benchmark hash mismatch")
    if [c["query_id"] for c in run["cases"]] != [q["id"] for q in queries]:
        raise ValueError("missing, reordered or duplicate cases")
    known = {d["pmid"] for d in corpus}
    claims = {claim_id(c["query_id"], s) for c in run["cases"] for s in c["sentences"]}
    for case in run["cases"]:
        if (len(case["results"]) > run["retmax"] or len(set(case["results"])) != len(case["results"])
                or not set(case["results"]) <= known or set(case["pico"]) != set(FIELDS)
                or any(s["pmid"] not in case["results"] for s in case["sentences"])):
            raise ValueError("invalid returned source/PICO")
    reviews, review_kind = {}, "pending"
    if review_path:
        review = read_json(review_path)
        if review["run_sha256"] != run["run_sha256"]:
            raise ValueError("stale review")
        if len(review["items"]) != len(claims) or {r["claim_id"] for r in review["items"]} != claims:
            raise ValueError("incomplete, duplicate or foreign review")
        review_kind = review["reviewer_kind"]
        for item in review["items"]:
            if claim_id(item["query_id"], item["sentence"]) != item["claim_id"]:
                raise ValueError("review sentence changed")
            if type(item["faithful"]) is not bool or type(item["answers_question"]) is not bool or not item["rationale"].strip():
                raise ValueError("unjudged claims: complete all booleans and rationales")
        if not review["reviewer"].strip() or review_kind not in ("model_authored_source_review", "human_expert"):
            raise ValueError("reviewer identity and kind required")
        reviews = {item["claim_id"]: item for item in review["items"]}
    summary = {"benchmark_sha256": run["benchmark_sha256"], "run_sha256": run["run_sha256"],
               "annotation_kind": manifest["annotation_kind"], "expert_review_status": manifest["expert_review_status"],
               "summary_reviewer_kind": review_kind, "scope": run["scope"],
               "mode_requested": run["mode_requested"], "llm_success_queries": sum(c["mode"] == "llm" for c in run["cases"]),
               "all": score_cases(queries, run["cases"], reviews), "by_language": {}}
    for language in sorted({q["language"] for q in queries}):
        indices = [i for i, q in enumerate(queries) if q["language"] == language]
        summary["by_language"][language] = score_cases([queries[i] for i in indices], [run["cases"][i] for i in indices], reviews)
    summary["by_answer_mode"] = {}
    for mode in sorted({c["mode"] for c in run["cases"]}):
        indices = [i for i, c in enumerate(run["cases"]) if c["mode"] == mode]
        summary["by_answer_mode"][mode] = score_cases([queries[i] for i in indices], [run["cases"][i] for i in indices], reviews)
    summary["llm_faithfulness"] = (summary["by_answer_mode"].get("llm") or {}).get("summary_faithfulness")
    return summary


def main():
    ap = argparse.ArgumentParser(__doc__)
    ap.add_argument("action", choices=("run", "score"))
    ap.add_argument("--benchmark", type=Path, default=ROOT / "evaluation/clinical_v1")
    ap.add_argument("--output", type=Path, default=ROOT / "evaluation/clinical_v1/baseline_run.json")
    ap.add_argument("--review", type=Path)
    ap.add_argument("--mode", choices=("extractive", "llm"), default="extractive")
    args = ap.parse_args()
    if args.action == "run":
        asyncio.run(run_benchmark(args.benchmark, args.output, args.mode))
    else:
        result = score_benchmark(args.benchmark, args.output, args.review)
        write_json(args.output.with_suffix(".metrics.json"), result)
        print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
