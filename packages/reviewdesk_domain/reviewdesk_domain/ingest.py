from __future__ import annotations

import re
from typing import Any

from reviewdesk_adapter_prodocux import extract_upload_pages
from reviewdesk_domain.models import DocumentId, DocumentPage, DossierDocument, EvidenceField, SourceLocator
from reviewdesk_domain.pdf import sha256_hex

MAX_UPLOAD_BYTES = 8 * 1024 * 1024

EXTRACT_FAILURE = (
    "This PDF could not extract the required fields. "
    "ProDocuX reads selectable PDF text, including ordinary compressed streams. "
    "ReviewDesk then looks for labels such as Product, Formula revision, Acceptable pH, and pH result. "
    "Scanned or image-only PDFs need OCR, which this demo does not enable."
)

SLOTS: dict[DocumentId, dict[str, str]] = {
    "product-spec": {
        "role": "subject",
        "document_type": "product_specification",
        "title": "Product specification",
    },
    "formula": {
        "role": "ref",
        "document_type": "ingredient_formula",
        "title": "Approved formula",
    },
    "coa": {
        "role": "ref",
        "document_type": "certificate_of_analysis",
        "title": "Certificate of analysis",
    },
}


def extract_pdf_pages(payload: bytes, filename: str = "upload.pdf") -> list[list[str]]:
    return extract_upload_pages(filename, payload)


def _find(lines: list[str], pattern: str) -> re.Match[str] | None:
    compiled = re.compile(pattern, re.I)
    for line in lines:
        match = compiled.search(line)
        if match:
            return match
    return None


def _first(lines: list[str], pattern: str) -> tuple[str, str] | None:
    match = _find(lines, pattern)
    if match is None:
        return None
    return match.group(1).strip(), match.group(0)


def _fields_for_slot(document_id: DocumentId, pages: list[list[str]]) -> list[tuple]:
    rows: list[tuple] = []
    for index, lines in enumerate(pages, start=1):
        product = (
            _first(lines, r"(?:Product|Certificate)\s*[:：]\s*(.+)$")
            or _first(lines, r"^(.+?)\s+[—\-?]\s+Master Formula")
        )
        if product:
            rows.append((f"ev-{document_id}-name", document_id, "product_name", "string", product[0], 0.95, index, product[1]))
        manufacturer = (
            _first(lines, r"Manufacturer\s*[:：]\s*(.+)$")
            or _first(lines, r"Prepared by\s+(.+)$")
            or _first(lines, r"^(.+?)\s+QC$")
        )
        if manufacturer:
            value = re.sub(r"\s+QC$", "", manufacturer[0]).strip()
            rows.append((f"ev-{document_id}-mfr", document_id, "manufacturer", "string", value, 0.93, index, manufacturer[1]))
        revision = _first(lines, r"Formula\s+revision\s*[:：]\s*([0-9]+)")
        if revision:
            rows.append(
                (f"ev-{document_id}-rev", document_id, "formula_revision", "version", revision[0], 0.96, index, revision[1])
            )
        batch = _first(lines, r"Reference batch\s*[:：]\s*([A-Z0-9-]+)") or _first(
            lines, r"^Batch\s+([A-Z0-9-]+)$"
        )
        if batch:
            rows.append((f"ev-{document_id}-batch", document_id, "batch_number", "string", batch[0], 0.95, index, batch[1]))
        ph_range = _find(lines, r"Acceptable\s*pH\s*[:：]\s*([\d.]+)\s*\W+\s*([\d.]+)")
        if ph_range:
            rows.append(
                (
                    f"ev-{document_id}-ph-min",
                    document_id,
                    "declared_ph_min",
                    "number",
                    float(ph_range.group(1)),
                    0.94,
                    index,
                    ph_range.group(0),
                )
            )
            rows.append(
                (
                    f"ev-{document_id}-ph-max",
                    document_id,
                    "declared_ph_max",
                    "number",
                    float(ph_range.group(2)),
                    0.94,
                    index,
                    ph_range.group(0),
                )
            )
        observed = _first(lines, r"pH\s+result\s*[:：]?\s*([\d.]+)")
        if observed:
            rows.append(
                (f"ev-{document_id}-ph", document_id, "coa_ph", "number", float(observed[0]), 0.94, index, observed[1])
            )
    unique: dict[str, tuple] = {}
    for row in rows:
        unique[row[0]] = row
    return list(unique.values())


def _pages(document_id: DocumentId, filename: str, extracted: list[list[str]]) -> list[DocumentPage]:
    slot = SLOTS[document_id]
    if not extracted or not extracted[0]:
        return [
            DocumentPage(
                page=1,
                title=slot["title"],
                lines=[filename, "Text extraction found no facsimile lines."],
            )
        ]
    pages: list[DocumentPage] = []
    for index, lines in enumerate(extracted, start=1):
        heading = lines[0] if lines else slot["title"]
        body = lines[1:] if len(lines) > 1 else lines
        highlight = next((line for line in lines if "revision" in line.lower() or "pH" in line), None)
        pages.append(
            DocumentPage(page=index, title=heading[:120], lines=body or [heading], highlight=highlight)
        )
    return pages


def _can_compile_checks(evidence_rows: list[tuple]) -> bool:
    present = {(row[1], row[2]) for row in evidence_rows}
    revision = ("product-spec", "formula_revision") in present and ("formula", "formula_revision") in present
    ph = (
        ("coa", "coa_ph") in present
        and ("product-spec", "declared_ph_min") in present
        and ("product-spec", "declared_ph_max") in present
    )
    return revision or ph


def _missing_labels(evidence_rows: list[tuple]) -> list[str]:
    present = {(row[1], row[2]) for row in evidence_rows}
    needed = [
        (("product-spec", "formula_revision"), "Product specification · Formula revision"),
        (("formula", "formula_revision"), "Approved formula · Formula revision"),
        (("product-spec", "declared_ph_min"), "Product specification · Acceptable pH"),
        (("coa", "coa_ph"), "Certificate of analysis · pH result"),
    ]
    return [label for key, label in needed if key not in present]


def safe_upload_filename(filename: str, fallback: str) -> str:
    name = str(filename or "").replace("\\", "/").rsplit("/", 1)[-1].strip()
    cleaned = "".join(ch for ch in name if ch.isprintable() and ch not in '<>:"|?*').strip()
    if not cleaned or cleaned in {".", ".."}:
        cleaned = fallback
    if not cleaned.lower().endswith(".pdf"):
        cleaned = f"{cleaned}.pdf"
    return cleaned[:180]


def subject_display_name(filename: str) -> str:
    stem = safe_upload_filename(filename, "subject.pdf")
    if stem.lower().endswith(".pdf"):
        stem = stem[:-4]
    return stem.strip() or "subject"


def pack_from_uploads(files: dict[str, tuple[str, bytes]]) -> dict[str, Any]:
    missing = [slot for slot in SLOTS if slot not in files]
    if missing:
        raise ValueError(
            "Drop one subject PDF and two locked reference PDFs. "
            f"Missing slots: {', '.join(missing)}."
        )
    documents: list[DossierDocument] = []
    evidence_rows: list[tuple] = []
    source_bytes: dict[str, bytes] = {}
    subject_filename = "subject.pdf"
    for document_id, slot in SLOTS.items():
        filename, payload = files[document_id]
        if len(payload) > MAX_UPLOAD_BYTES:
            raise ValueError(f"{filename} is larger than 8 MB.")
        if not payload.startswith(b"%PDF"):
            raise ValueError(f"{filename} is not a PDF. Drop a PDF into the {slot['role']} slot.")
        if slot["role"] == "subject" and document_id != "product-spec":
            raise ValueError("Only the product specification slot can be the subject.")
        if slot["role"] == "ref" and document_id == "product-spec":
            raise ValueError("References cannot be placed in the subject slot.")
        safe_name = safe_upload_filename(filename, f"{document_id}.pdf")
        extracted = extract_pdf_pages(payload, safe_name)
        document = DossierDocument(
            document_id=document_id,  # type: ignore[arg-type]
            filename=safe_name[:180],
            document_type=slot["document_type"],  # type: ignore[arg-type]
            source_sha256=sha256_hex(payload),
            role=slot["role"],  # type: ignore[arg-type]
            pages=_pages(document_id, safe_name, extracted),
        )
        documents.append(document)
        source_bytes[document_id] = payload
        evidence_rows.extend(_fields_for_slot(document_id, extracted))
        if document_id == "product-spec":
            subject_filename = safe_name
    named = next(
        (row[4] for row in evidence_rows if row[2] == "product_name" and isinstance(row[4], str) and row[4].strip()),
        None,
    )
    product_name = named.strip() if isinstance(named, str) and named.strip() else subject_display_name(subject_filename)
    if not _can_compile_checks(evidence_rows):
        labels = _missing_labels(evidence_rows)
        extra = f" Missing: {'; '.join(labels)}." if labels else ""
        raise ValueError(EXTRACT_FAILURE + extra)
    evidence = [
        EvidenceField(
            evidence_id=evidence_id,
            document_id=document_id,  # type: ignore[arg-type]
            field_name=field_name,
            value_type=value_type,  # type: ignore[arg-type]
            original_value=value,
            normalized_value=value,
            confidence=confidence,
            source=SourceLocator(page=page, snippet=snippet[:2048]),
        )
        for evidence_id, document_id, field_name, value_type, value, confidence, page, snippet in evidence_rows
    ]
    digest = sha256_hex(b"".join(source_bytes[slot] for slot in SLOTS))
    return {
        "dossier_id": f"upload-{digest[:12]}",
        "product_name": product_name,
        "documents": documents,
        "evidence": evidence,
        "source_bytes": source_bytes,
        "planted": [],
        "blurb": "Human-classified upload. Subject is editable after review; references stay locked.",
        "extractor_id": "prodocux.intake.pdf",
        "extraction_method": "native_text",
    }
