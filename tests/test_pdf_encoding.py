from __future__ import annotations

from reviewdesk_domain.fixture import load_dossier, original_pdf_bytes
from reviewdesk_domain.pdf import build_pdf


def test_pdf_keeps_em_dash_instead_of_question_mark() -> None:
    payload = build_pdf(
        title="formula.pdf",
        pages=[("Approved formula", ["Harbor Calm Serum — Master Formula"])],
        footer="footer",
    )
    stream = payload.split(b"stream\n", 1)[1].split(b"\nendstream", 1)[0]
    assert b"Harbor Calm Serum \x97 Master Formula" in stream
    assert b"Harbor Calm Serum ? Master Formula" not in stream
    assert b"/Encoding /WinAnsiEncoding" in payload


def test_fixture_formula_pdf_does_not_show_question_mark_title() -> None:
    formula = next(item for item in load_dossier()["documents"] if item.document_id == "formula")
    payload = original_pdf_bytes(formula)
    stream = payload.split(b"stream\n", 1)[1].split(b"\nendstream", 1)[0]
    assert b"Harbor Calm Serum ? Master Formula" not in stream
    assert b"Master Formula" in stream
