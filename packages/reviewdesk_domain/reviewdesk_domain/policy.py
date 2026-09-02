from __future__ import annotations

import hashlib
import json

from reviewdesk_domain.models import EvidenceField, Finding

RULE_SET_ID = "reviewdesk.dossier.demo"
RULE_SET_VERSION = "1"

FINDING_META = {
    "product-identity": {
        "finding_id": "find-identity",
        "severity": "high",
        "title": "Product identity matches across the dossier",
        "authority_document": "formula",
        "observed_document": "product-spec",
        "authority_rule": "The three source documents must name the same product.",
        "action": "informational",
    },
    "formula-version": {
        "finding_id": "find-revision",
        "severity": "critical",
        "title": "Specification must cite the approved formula revision",
        "authority_document": "formula",
        "observed_document": "product-spec",
        "authority_rule": "The approved master formula governs the revision. Correct the specification reference only.",
        "action": "correct_subject_field",
    },
    "batch-identity": {
        "finding_id": "find-batch",
        "severity": "medium",
        "title": "Specification and certificate share a batch identity",
        "authority_document": "product-spec",
        "observed_document": "coa",
        "authority_rule": "Batch identity is shared, but observed results stay on the certificate.",
        "action": "informational",
    },
    "ph-range": {
        "finding_id": "find-ph",
        "severity": "high",
        "title": "Observed pH is outside the specification range",
        "authority_document": "product-spec",
        "observed_document": "coa",
        "authority_rule": "The specification sets the limit. The certificate records the observation and must not be overwritten unless extraction itself is wrong.",
        "action": "confirm_ref_observation",
    },
    "required-manufacturer": {
        "finding_id": "find-manufacturer",
        "severity": "medium",
        "title": "Manufacturer evidence is present",
        "authority_document": "formula",
        "observed_document": "product-spec",
        "authority_rule": "Manufacturer identity must be present on the governing documents.",
        "action": "informational",
    },
}

CORRECTION_TARGET = {
    "formula-version": ("product-spec", "formula_revision"),
}


def _digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _ids(evidence: list[EvidenceField], field_name: str) -> list[str]:
    return [item.evidence_id for item in evidence if item.field_name == field_name]


def _value(evidence: list[EvidenceField], document_id: str, field_name: str):
    match = next(
        (
            item
            for item in evidence
            if item.document_id == document_id and item.field_name == field_name
        ),
        None,
    )
    return None if match is None else match.normalized_value


def compile_pif_checks(
    evidence: list[EvidenceField],
    documents: list[dict],
    request_id: str,
    *,
    extractor_id: str = "reviewdesk.fixture",
    extraction_method: str = "host_supplied",
) -> dict:
    checks: list[dict] = []
    product_ids = _ids(evidence, "product_name")
    if product_ids:
        checks.append(
            {
                "check_id": "product-identity",
                "kind": "equality",
                "evidence_ids": product_ids,
                "minimum_confidence": 0.9,
            }
        )
    formula_rev = next(
        (
            item.evidence_id
            for item in evidence
            if item.document_id == "formula" and item.field_name == "formula_revision"
        ),
        None,
    )
    spec_rev = next(
        (
            item.evidence_id
            for item in evidence
            if item.document_id == "product-spec" and item.field_name == "formula_revision"
        ),
        None,
    )
    if formula_rev and spec_rev:
        checks.append(
            {
                "check_id": "formula-version",
                "kind": "version_match",
                "evidence_ids": [formula_rev, spec_rev],
                "minimum_confidence": 0.9,
            }
        )
    batch_ids = [
        item.evidence_id
        for item in evidence
        if item.field_name == "batch_number" and item.document_id in {"product-spec", "coa"}
    ]
    if len(batch_ids) >= 2:
        checks.append(
            {
                "check_id": "batch-identity",
                "kind": "equality",
                "evidence_ids": batch_ids,
                "minimum_confidence": 0.9,
            }
        )
    coa_ph = next(
        (
            item.evidence_id
            for item in evidence
            if item.document_id == "coa" and item.field_name == "coa_ph"
        ),
        None,
    )
    ph_min = _value(evidence, "product-spec", "declared_ph_min")
    ph_max = _value(evidence, "product-spec", "declared_ph_max")
    if coa_ph and isinstance(ph_min, (int, float)) and isinstance(ph_max, (int, float)):
        checks.append(
            {
                "check_id": "ph-range",
                "kind": "numeric_range",
                "evidence_ids": [coa_ph],
                "minimum": float(ph_min),
                "maximum": float(ph_max),
                "minimum_confidence": 0.9,
            }
        )
    manufacturer_ids = _ids(evidence, "manufacturer")
    if manufacturer_ids:
        checks.append(
            {
                "check_id": "required-manufacturer",
                "kind": "presence",
                "evidence_ids": manufacturer_ids,
                "minimum_confidence": 0.85,
            }
        )
    rules = {"id": RULE_SET_ID, "version": RULE_SET_VERSION, "checks": checks}
    document_map = {item["document_id"]: item for item in documents}
    payload_evidence = []
    for item in evidence:
        document = document_map[item.document_id]
        payload_evidence.append(
            {
                "evidence_id": item.evidence_id,
                "document_id": item.document_id,
                "field_name": item.field_name,
                "value_type": item.value_type,
                "value": item.normalized_value,
                "confidence": item.confidence,
                "source_reference": {
                    "schema_version": "prodocux_source_reference_v1",
                    "source_sha256": document["source_sha256"],
                    "media_type": "application/pdf",
                    "locator": {"kind": "pdf_page", "page": item.source.page},
                    "snippet": item.source.snippet,
                    "extraction": {
                        "method": extraction_method,
                        "extractor_id": extractor_id,
                        "extractor_version": "demo-v1",
                    },
                    "truncated": False,
                },
            }
        )
    return {
        "schema_version": "prodocux_evidence_bundle_request_v1",
        "request_id": request_id,
        "rule_set": {
            "id": RULE_SET_ID,
            "version": RULE_SET_VERSION,
            "sha256": _digest(rules),
        },
        "documents": [
            {
                "document_id": item["document_id"],
                "source_sha256": item["source_sha256"],
                "media_type": "application/pdf",
            }
            for item in documents
        ],
        "evidence": payload_evidence,
        "checks": checks,
    }


def default_assignee(action: str) -> str:
    return "agent" if action == "correct_subject_field" else "human"


def findings_from_verification(
    verification: dict,
    *,
    corrected_checks: set[str],
    confirmed_checks: set[str],
    assignees: dict[str, str] | None = None,
) -> list[Finding]:
    findings: list[Finding] = []
    for result in verification["results"]:
        meta = FINDING_META[result["check_id"]]
        if result["status"] == "pass":
            status = "corrected" if result["check_id"] in corrected_checks else "pass"
        elif result["check_id"] in confirmed_checks:
            status = "confirmed"
        else:
            status = "needs_review"
        findings.append(
            Finding(
                finding_id=meta["finding_id"],
                check_id=result["check_id"],
                severity=meta["severity"],
                status=status,
                title=meta["title"],
                message=_message(result),
                reason_codes=list(result.get("reason_codes") or []),
                evidence_refs=list(result.get("evidence_ids") or []),
                expected=result.get("expected"),
                actual=result.get("actual"),
                authority_document=meta["authority_document"],
                observed_document=meta["observed_document"],
                authority_rule=meta["authority_rule"],
                action=meta["action"],
                assignee=(assignees or {}).get(result["check_id"]) or default_assignee(meta["action"]),
            )
        )
    return findings


def _message(result: dict) -> str:
    codes = result.get("reason_codes") or []
    code = codes[0] if codes else "UNKNOWN"
    expected, actual = result.get("expected"), result.get("actual")
    return {
        "VERSION_MISMATCH": (
            f"The specification cites revision {actual}, but the approved formula is revision {expected}. "
            "Correct the normalized specification reference. Do not rewrite the source PDF."
        ),
        "VERSIONS_MATCH": "The specification cites the approved formula revision.",
        "VALUE_ABOVE_MAXIMUM": (
            f"The specification allows up to {expected}. The certificate records pH {actual} as an observed batch fact. "
            "Confirm the deviation; do not rewrite the certificate."
        ),
        "VALUE_BELOW_MINIMUM": (
            f"The specification requires at least {expected}. The certificate records {actual}."
        ),
        "VALUE_WITHIN_RANGE": "The certificate pH is inside the specification range.",
        "VALUES_EQUAL": "Values agree across source documents.",
        "VALUE_MISMATCH": f"Expected {expected}; found {actual}.",
        "VALUE_PRESENT": "Required evidence is present.",
        "VALUE_MISSING": "Required evidence is missing.",
    }.get(code, code.replace("_", " ").title())
