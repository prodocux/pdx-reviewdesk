from __future__ import annotations

import time
from copy import deepcopy
from typing import Any

from reviewdesk_domain.cases import EXTRA_BENCHMARK
from reviewdesk_domain.fixture import DEMO_DOSSIER_ID, original_pdf_bytes
from reviewdesk_domain.pdf import sha256_hex
from reviewdesk_domain.policy import compile_pif_checks


def benchmark_packs() -> list[dict[str, Any]]:
    from reviewdesk_domain.fixture import load_dossier

    packs = [load_dossier(DEMO_DOSSIER_ID), load_dossier("cedar-night-cream-2026")]
    for item in EXTRA_BENCHMARK:
        documents = deepcopy(item["documents"])
        for document in documents:
            document.source_sha256 = sha256_hex(original_pdf_bytes(document))
        packs.append({**item, "documents": documents, "evidence": deepcopy(item["evidence"])})
    return packs


def score_pack(pack: dict[str, Any], verifier) -> dict[str, Any]:
    documents = pack["documents"]
    evidence = pack["evidence"]
    payload = [item.model_dump(mode="json") for item in documents]
    request = compile_pif_checks(evidence, payload, f"bench-{pack['dossier_id']}")
    started = time.perf_counter()
    verification = verifier.verify(request)
    elapsed_ms = int((time.perf_counter() - started) * 1000)
    flagged = {item["check_id"] for item in verification["results"] if item["status"] != "pass"}
    planted = set(pack["planted"])
    hits = sorted(planted & flagged)
    misses = sorted(planted - flagged)
    false_positives = sorted(flagged - planted)
    return {
        "dossier_id": pack["dossier_id"],
        "product_name": pack["product_name"],
        "planted": sorted(planted),
        "flagged": sorted(flagged),
        "hits": hits,
        "misses": misses,
        "false_positives": false_positives,
        "elapsed_ms": elapsed_ms,
        "ok": not misses and not false_positives,
    }


def run_benchmark(verifier) -> dict[str, Any]:
    rows = [score_pack(pack, verifier) for pack in benchmark_packs()]
    planted = sum(len(item["planted"]) for item in rows)
    hits = sum(len(item["hits"]) for item in rows)
    misses = sum(len(item["misses"]) for item in rows)
    false_positives = sum(len(item["false_positives"]) for item in rows)
    return {
        "dossiers": len(rows),
        "planted": planted,
        "hits": hits,
        "misses": misses,
        "false_positives": false_positives,
        "hit_rate": round(hits / planted, 4) if planted else 1.0,
        "elapsed_ms": sum(item["elapsed_ms"] for item in rows),
        "rows": rows,
    }
