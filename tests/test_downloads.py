from __future__ import annotations

from reviewdesk_api.service import ReviewDeskService
from reviewdesk_domain.fixture import original_pdf_bytes, reviewed_subject_pdf_bytes
from reviewdesk_domain.pdf import sha256_hex


def test_originals_and_reviewed_subject_are_downloadable(tmp_path) -> None:
    service = ReviewDeskService(tmp_path)
    run = service.start_demo("human")
    assert run.stage == "documents"
    assert run.subject_filename is None
    for document in run.documents:
        path, filename = service.source_file(run.run_id, document.document_id)
        payload = path.read_bytes()
        assert filename == document.filename
        assert payload.startswith(b"%PDF-")
        assert sha256_hex(payload) == document.source_sha256
        assert original_pdf_bytes(document) == payload

    try:
        service.subject_file(run.run_id)
        raise AssertionError("subject file must wait for approval")
    except ValueError as exc:
        assert "after approval" in str(exc)

    opened = service.reveal_findings(run.run_id, "human")
    assert opened.stage == "findings"
    selected = service.select_finding(run.run_id, "find-revision", "human")
    assert selected.stage == "corrections"

    service.propose_correction(run.run_id, "3", "Approved formula revision 3 is authoritative.", "human")
    service.commit_correction(run.run_id, "human")
    service.confirm_observed_fact(run.run_id, "human")
    closed = service.decide(run.run_id, "human", "approved")
    assert closed.stage == "closed"
    assert closed.status == "approved"
    assert closed.subject_filename == "harbor-calm-serum-specification-reviewed.pdf"

    subject_path, subject_name = service.subject_file(run.run_id)
    reviewed = subject_path.read_bytes()
    spec = next(item for item in closed.documents if item.document_id == "product-spec")
    assert subject_name.endswith(".pdf")
    assert reviewed.startswith(b"%PDF-")
    assert b"Formula revision: 3" in reviewed
    assert reviewed == reviewed_subject_pdf_bytes(spec, formula_revision="3")
    locked = service.source_file(run.run_id, "product-spec")[0].read_bytes()
    assert b"Formula revision: 2" in locked
    assert sha256_hex(locked) == spec.source_sha256
