from __future__ import annotations

from copy import deepcopy
from typing import Any

from reviewdesk_domain.models import DocumentPage, DossierDocument, EvidenceField, SourceLocator
from reviewdesk_domain.pdf import build_pdf, sha256_hex

DEMO_PRODUCT = "Harbor Calm Serum"
DEMO_DOSSIER_ID = "harbor-calm-serum-2026"


def _doc(
    document_id: str,
    filename: str,
    document_type: str,
    role: str,
    pages: list[DocumentPage],
) -> DossierDocument:
    return DossierDocument(
        document_id=document_id,  # type: ignore[arg-type]
        filename=filename,
        document_type=document_type,  # type: ignore[arg-type]
        source_sha256="0" * 64,
        role=role,  # type: ignore[arg-type]
        pages=pages,
    )


def _evidence(rows: list[tuple]) -> list[EvidenceField]:
    return [
        EvidenceField(
            evidence_id=evidence_id,
            document_id=document_id,
            field_name=field_name,
            value_type=value_type,
            original_value=value,
            normalized_value=value,
            confidence=confidence,
            source=SourceLocator(page=page, snippet=snippet),
        )
        for evidence_id, document_id, field_name, value_type, value, confidence, page, snippet in rows
    ]


HARBOR_DOCUMENTS = [
    _doc(
        "product-spec",
        "harbor-calm-serum-specification.pdf",
        "product_specification",
        "subject",
        [
            DocumentPage(
                page=1,
                title="Product specification",
                lines=[
                    "Product: Harbor Calm Serum",
                    "Manufacturer: Westbay Formulation Co.",
                    "Formula revision: 2",
                    "Intended use: leave-on facial serum",
                ],
                highlight="Formula revision: 2",
            ),
            DocumentPage(
                page=2,
                title="Finished-product limits",
                lines=[
                    "Reference batch: HCS-2608-22",
                    "Acceptable pH: 4.8–5.8",
                    "Appearance: pale amber liquid",
                    "Manufacturer: Westbay Formulation Co.",
                ],
                highlight="Acceptable pH: 4.8–5.8",
            ),
        ],
    ),
    _doc(
        "formula",
        "harbor-calm-serum-formula.pdf",
        "ingredient_formula",
        "ref",
        [
            DocumentPage(
                page=1,
                title="Approved master formula",
                lines=[
                    "Harbor Calm Serum — Master Formula",
                    "Formula revision: 3",
                    "Status: approved for manufacture",
                    "Aqua 71.20%",
                ],
                highlight="Formula revision: 3",
            ),
            DocumentPage(
                page=2,
                title="Composition notes",
                lines=[
                    "Glycerin 6.00%",
                    "Niacinamide 5.00%",
                    "Prepared by Westbay Formulation Co.",
                    "This revision supersedes revision 2.",
                ],
            ),
        ],
    ),
    _doc(
        "coa",
        "harbor-calm-serum-coa.pdf",
        "certificate_of_analysis",
        "ref",
        [
            DocumentPage(
                page=1,
                title="Certificate of analysis",
                lines=[
                    "Certificate: Harbor Calm Serum",
                    "Batch HCS-2608-22",
                    "Test date: 2026-08-18",
                    "Westbay Formulation Co. QC",
                ],
                highlight="Batch HCS-2608-22",
            ),
            DocumentPage(
                page=2,
                title="Observed results",
                lines=[
                    "pH result 6.4",
                    "Appearance: pale amber liquid",
                    "Microbial limits: Pass",
                    "This certificate records observed batch facts.",
                ],
                highlight="pH result 6.4",
            ),
        ],
    ),
]

CEDAR_DOCUMENTS = [
    _doc(
        "product-spec",
        "cedar-night-cream-specification.pdf",
        "product_specification",
        "subject",
        [
            DocumentPage(
                page=1,
                title="Product specification",
                lines=[
                    "Product: Cedar Night Cream",
                    "Manufacturer: Cedar & Oak Labs",
                    "Formula revision: 1",
                    "Intended use: overnight leave-on cream",
                ],
                highlight="Formula revision: 1",
            ),
            DocumentPage(
                page=2,
                title="Finished-product limits",
                lines=[
                    "Reference batch: CNC-2603-11",
                    "Acceptable pH: 5.0–6.0",
                    "Appearance: ivory cream",
                    "Manufacturer: Cedar & Oak Labs",
                ],
                highlight="Acceptable pH: 5.0–6.0",
            ),
        ],
    ),
    _doc(
        "formula",
        "cedar-night-cream-formula.pdf",
        "ingredient_formula",
        "ref",
        [
            DocumentPage(
                page=1,
                title="Approved master formula",
                lines=[
                    "Cedar Night Cream — Master Formula",
                    "Formula revision: 2",
                    "Status: approved for manufacture",
                    "Aqua 64.10%",
                ],
                highlight="Formula revision: 2",
            ),
            DocumentPage(
                page=2,
                title="Composition notes",
                lines=[
                    "Shea butter 8.00%",
                    "Ceramide NP 0.30%",
                    "Prepared by Cedar & Oak Labs",
                    "This revision supersedes revision 1.",
                ],
            ),
        ],
    ),
    _doc(
        "coa",
        "cedar-night-cream-coa.pdf",
        "certificate_of_analysis",
        "ref",
        [
            DocumentPage(
                page=1,
                title="Certificate of analysis",
                lines=[
                    "Certificate: Cedar Night Cream",
                    "Batch CNC-2603-11",
                    "Test date: 2026-08-12",
                    "Cedar & Oak Labs QC",
                ],
                highlight="Batch CNC-2603-11",
            ),
            DocumentPage(
                page=2,
                title="Observed results",
                lines=[
                    "pH result 5.2",
                    "Appearance: ivory cream",
                    "Microbial limits: Pass",
                    "This certificate records observed batch facts.",
                ],
                highlight="pH result 5.2",
            ),
        ],
    ),
]

DOSSIERS: dict[str, dict[str, Any]] = {
    "harbor-calm-serum-2026": {
        "dossier_id": "harbor-calm-serum-2026",
        "product_name": "Harbor Calm Serum",
        "judge_mode": True,
        "blurb": "Spec cites formula revision 2 and pH 4.8–5.8. Formula is revision 3. CoA records pH 6.4.",
        "planted": ["formula-version", "ph-range"],
        "documents": HARBOR_DOCUMENTS,
        "evidence": _evidence(
            [
                ("ev-spec-name", "product-spec", "product_name", "string", "Harbor Calm Serum", 0.99, 1, "Product: Harbor Calm Serum"),
                ("ev-spec-mfr", "product-spec", "manufacturer", "string", "Westbay Formulation Co.", 0.97, 1, "Manufacturer: Westbay Formulation Co."),
                ("ev-spec-rev", "product-spec", "formula_revision", "version", "2", 0.98, 1, "Formula revision: 2"),
                ("ev-spec-ph-min", "product-spec", "declared_ph_min", "number", 4.8, 0.97, 2, "Acceptable pH: 4.8–5.8"),
                ("ev-spec-ph-max", "product-spec", "declared_ph_max", "number", 5.8, 0.97, 2, "Acceptable pH: 4.8–5.8"),
                ("ev-spec-batch", "product-spec", "batch_number", "string", "HCS-2608-22", 0.99, 2, "Reference batch: HCS-2608-22"),
                ("ev-formula-name", "formula", "product_name", "string", "Harbor Calm Serum", 0.99, 1, "Harbor Calm Serum — Master Formula"),
                ("ev-formula-mfr", "formula", "manufacturer", "string", "Westbay Formulation Co.", 0.97, 2, "Prepared by Westbay Formulation Co."),
                ("ev-formula-rev", "formula", "formula_revision", "version", "3", 0.98, 1, "Formula revision: 3"),
                ("ev-coa-name", "coa", "product_name", "string", "Harbor Calm Serum", 0.99, 1, "Certificate: Harbor Calm Serum"),
                ("ev-coa-mfr", "coa", "manufacturer", "string", "Westbay Formulation Co.", 0.97, 1, "Westbay Formulation Co. QC"),
                ("ev-coa-batch", "coa", "batch_number", "string", "HCS-2608-22", 0.99, 1, "Batch HCS-2608-22"),
                ("ev-coa-ph", "coa", "coa_ph", "number", 6.4, 0.96, 2, "pH result 6.4"),
            ]
        ),
    },
    "cedar-night-cream-2026": {
        "dossier_id": "cedar-night-cream-2026",
        "product_name": "Cedar Night Cream",
        "judge_mode": False,
        "blurb": "Spec cites formula revision 1. Formula is revision 2. CoA pH 5.2 sits inside 5.0–6.0.",
        "planted": ["formula-version"],
        "documents": CEDAR_DOCUMENTS,
        "evidence": _evidence(
            [
                ("ev-spec-name", "product-spec", "product_name", "string", "Cedar Night Cream", 0.99, 1, "Product: Cedar Night Cream"),
                ("ev-spec-mfr", "product-spec", "manufacturer", "string", "Cedar & Oak Labs", 0.97, 1, "Manufacturer: Cedar & Oak Labs"),
                ("ev-spec-rev", "product-spec", "formula_revision", "version", "1", 0.98, 1, "Formula revision: 1"),
                ("ev-spec-ph-min", "product-spec", "declared_ph_min", "number", 5.0, 0.97, 2, "Acceptable pH: 5.0–6.0"),
                ("ev-spec-ph-max", "product-spec", "declared_ph_max", "number", 6.0, 0.97, 2, "Acceptable pH: 5.0–6.0"),
                ("ev-spec-batch", "product-spec", "batch_number", "string", "CNC-2603-11", 0.99, 2, "Reference batch: CNC-2603-11"),
                ("ev-formula-name", "formula", "product_name", "string", "Cedar Night Cream", 0.99, 1, "Cedar Night Cream — Master Formula"),
                ("ev-formula-mfr", "formula", "manufacturer", "string", "Cedar & Oak Labs", 0.97, 2, "Prepared by Cedar & Oak Labs"),
                ("ev-formula-rev", "formula", "formula_revision", "version", "2", 0.98, 1, "Formula revision: 2"),
                ("ev-coa-name", "coa", "product_name", "string", "Cedar Night Cream", 0.99, 1, "Certificate: Cedar Night Cream"),
                ("ev-coa-mfr", "coa", "manufacturer", "string", "Cedar & Oak Labs", 0.97, 1, "Cedar & Oak Labs QC"),
                ("ev-coa-batch", "coa", "batch_number", "string", "CNC-2603-11", 0.99, 1, "Batch CNC-2603-11"),
                ("ev-coa-ph", "coa", "coa_ph", "number", 5.2, 0.96, 2, "pH result 5.2"),
            ]
        ),
    },
}

DOCUMENTS = HARBOR_DOCUMENTS


def list_dossiers() -> list[dict[str, Any]]:
    return [
        {
            "dossier_id": item["dossier_id"],
            "product_name": item["product_name"],
            "judge_mode": item["judge_mode"],
            "blurb": item["blurb"],
            "planted": list(item["planted"]),
        }
        for item in DOSSIERS.values()
    ]


def load_dossier(dossier_id: str | None = None) -> dict[str, Any]:
    key = dossier_id or DEMO_DOSSIER_ID
    if key not in DOSSIERS:
        raise ValueError(f"Unknown dossier: {key}")
    pack = DOSSIERS[key]
    documents = deepcopy(pack["documents"])
    for document in documents:
        document.source_sha256 = sha256_hex(original_pdf_bytes(document))
    return {
        "dossier_id": pack["dossier_id"],
        "product_name": pack["product_name"],
        "documents": documents,
        "evidence": deepcopy(pack["evidence"]),
        "planted": list(pack["planted"]),
        "blurb": pack["blurb"],
    }


def demo_documents() -> list[DossierDocument]:
    return load_dossier(DEMO_DOSSIER_ID)["documents"]


def demo_evidence() -> list[EvidenceField]:
    return load_dossier(DEMO_DOSSIER_ID)["evidence"]


def original_pdf_bytes(document: DossierDocument) -> bytes:
    return build_pdf(
        title=document.filename,
        pages=[(page.title, page.lines) for page in document.pages],
        footer=f"Original source · {document.filename} · immutable",
    )


def reviewed_subject_pages(spec: DossierDocument, *, formula_revision: str) -> list[DocumentPage]:
    pages: list[DocumentPage] = []
    for page in spec.pages:
        lines = [
            f"Formula revision: {formula_revision}" if line.startswith("Formula revision:") else line
            for line in page.lines
        ]
        highlight = page.highlight
        if highlight and highlight.startswith("Formula revision:"):
            highlight = f"Formula revision: {formula_revision}"
        pages.append(
            DocumentPage(
                page=page.page,
                title=f"{page.title} (reviewed artifact)",
                lines=lines,
                highlight=highlight,
            )
        )
    return pages


def reviewed_subject_pdf_bytes(spec: DossierDocument, *, formula_revision: str) -> bytes:
    pages: list[tuple[str, list[str]]] = []
    for page in reviewed_subject_pages(spec, formula_revision=formula_revision):
        pages.append((page.title, page.lines))
    stem = spec.filename.removesuffix(".pdf")
    return build_pdf(
        title=f"{stem}-reviewed.pdf",
        pages=pages,
        footer="Approved subject copy · original source digest unchanged · formula_revision corrected in review copy only",
    )
