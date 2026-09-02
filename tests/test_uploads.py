from __future__ import annotations

from reviewdesk_api.service import ReviewDeskService
from reviewdesk_domain.fixture import load_dossier, original_pdf_bytes
from reviewdesk_domain.ingest import extract_pdf_pages, pack_from_uploads
from reviewdesk_domain.pdf import build_pdf


def _files_from_pack(dossier_id: str) -> dict[str, tuple[str, bytes]]:
    pack = load_dossier(dossier_id)
    return {
        item.document_id: (item.filename, original_pdf_bytes(item))
        for item in pack["documents"]
    }


def test_upload_slots_lock_refs_and_follow_extracted_values(tmp_path) -> None:
    service = ReviewDeskService(tmp_path)
    harbor = _files_from_pack("harbor-calm-serum-2026")
    run = service.start_from_uploads("human", harbor)
    assert run.dossier_id.startswith("upload-")
    assert next(item for item in run.documents if item.document_id == "product-spec").role == "subject"
    assert all(item.role == "ref" for item in run.documents if item.document_id != "product-spec")
    failed = {item.check_id for item in run.findings if item.status == "needs_review"}
    assert failed == {"formula-version", "ph-range"}
    assert run.product_name == "Harbor Calm Serum"

    swapped = dict(harbor)
    swapped["product-spec"] = harbor["formula"]
    swapped["formula"] = harbor["product-spec"]
    classified = pack_from_uploads(swapped)
    subject = next(item for item in classified["documents"] if item.role == "subject")
    formula = next(item for item in classified["documents"] if item.document_id == "formula")
    assert subject.document_id == "product-spec"
    assert "Master Formula" in " ".join(line for page in subject.pages for line in page.lines)
    assert formula.role == "ref"
    uploaded = next(item for item in run.documents if item.document_id == "formula")
    facsimile = " ".join(line for page in uploaded.pages for line in page.lines)
    assert "Harbor Calm Serum ? Master Formula" not in facsimile
    assert "Master Formula" in facsimile


def test_upload_rejects_missing_subject_slot(tmp_path) -> None:
    harbor = _files_from_pack("harbor-calm-serum-2026")
    del harbor["product-spec"]
    try:
        pack_from_uploads(harbor)
        raise AssertionError("subject slot must be required")
    except ValueError as exc:
        assert "subject" in str(exc).lower() or "product-spec" in str(exc)


def test_changed_subject_revision_changes_findings(tmp_path) -> None:
    service = ReviewDeskService(tmp_path)
    harbor = _files_from_pack("harbor-calm-serum-2026")
    aligned = build_pdf(
        title="aligned-spec.pdf",
        pages=[
            (
                "Product specification",
                [
                    "Product: Harbor Calm Serum",
                    "Manufacturer: Westbay Formulation Co.",
                    "Formula revision: 3",
                    "Intended use: leave-on facial serum",
                ],
            ),
            (
                "Finished-product limits",
                [
                    "Reference batch: HCS-2608-22",
                    "Acceptable pH: 4.8-5.8",
                    "Appearance: pale amber liquid",
                    "Manufacturer: Westbay Formulation Co.",
                ],
            ),
        ],
        footer="Original source · aligned-spec.pdf · immutable",
    )
    harbor["product-spec"] = ("aligned-spec.pdf", aligned)
    run = service.start_from_uploads("human", harbor)
    failed = {item.check_id for item in run.findings if item.status == "needs_review"}
    assert "formula-version" not in failed
    assert "ph-range" in failed
    pack = pack_from_uploads(harbor)
    assert pack["extractor_id"] == "prodocux.intake.pdf"
    assert pack["extraction_method"] == "native_text"


def test_flate_compressed_upload_extracts_fields(tmp_path) -> None:
    service = ReviewDeskService(tmp_path)
    harbor = _files_from_pack("harbor-calm-serum-2026")
    compressed = {
        document_id: (filename, _compress_like_export(payload))
        for document_id, (filename, payload) in harbor.items()
    }
    run = service.start_from_uploads("human", compressed)
    failed = {item.check_id for item in run.findings if item.status == "needs_review"}
    assert failed == {"formula-version", "ph-range"}


def test_upload_without_product_label_uses_subject_filename(tmp_path) -> None:
    spec = build_pdf(
        title="westbay-serum-spec.pdf",
        pages=[
            (
                "Specification",
                ["Formula revision: 2", "Acceptable pH: 4.8-5.8", "Reference batch: HCS-2608-22"],
            )
        ],
        footer="spec",
    )
    formula = build_pdf(
        title="westbay-serum-formula.pdf",
        pages=[("Formula", ["Formula revision: 3", "Prepared by Westbay Formulation Co."])],
        footer="formula",
    )
    coa = build_pdf(
        title="westbay-serum-coa.pdf",
        pages=[("Certificate", ["Batch HCS-2608-22", "pH result 6.4"])],
        footer="coa",
    )
    pack = pack_from_uploads(
        {
            "product-spec": ("westbay-serum-spec.pdf", spec),
            "formula": ("westbay-serum-formula.pdf", formula),
            "coa": ("westbay-serum-coa.pdf", coa),
        }
    )
    assert pack["product_name"] == "westbay-serum-spec"
    service = ReviewDeskService(tmp_path)
    run = service.start_from_uploads(
        "human",
        {
            "product-spec": ("westbay-serum-spec.pdf", spec),
            "formula": ("westbay-serum-formula.pdf", formula),
            "coa": ("westbay-serum-coa.pdf", coa),
        },
    )
    assert run.product_name == "westbay-serum-spec"
    assert "Uploaded dossier" not in run.product_name


def test_unreadable_pdf_raises_friendly_extract_error() -> None:
    blank = build_pdf(
        title="blank.pdf",
        pages=[("Blank page", ["No labeled fields on this page."])],
        footer="blank",
        compress=True,
    )
    files = {
        "product-spec": ("spec.pdf", blank),
        "formula": ("formula.pdf", blank),
        "coa": ("coa.pdf", blank),
    }
    try:
        pack_from_uploads(files)
        raise AssertionError("unlabeled PDFs must fail before ProDocuX")
    except ValueError as exc:
        message = str(exc)
        assert "could not extract the required fields" in message
        assert "pydantic" not in message.lower()
        assert "Formula revision" in message


def _compress_like_export(payload: bytes) -> bytes:
    pages = extract_pdf_pages(payload)
    titled = []
    for index, lines in enumerate(pages, start=1):
        heading = lines[0] if lines else f"Page {index}"
        body = lines[1:] if len(lines) > 1 else lines
        titled.append((heading, body or [heading]))
    return build_pdf(
        title="compressed.pdf",
        pages=titled or [("Empty", ["Empty"])],
        footer="compressed",
        compress=True,
    )
