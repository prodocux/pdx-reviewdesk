from __future__ import annotations

import httpx


def extract_upload_pages(filename: str, payload: bytes) -> list[list[str]]:
    """Page text via published ProDocuX intake, not a ReviewDesk PDF parser."""
    from prodocux_kernel.intake.pdf import extract_pdf_bytes

    try:
        pages, _truncated = extract_pdf_bytes(payload, filename=filename)
    except ValueError as exc:
        raise ValueError(
            "ProDocuX could not read this PDF. Use a selectable-text PDF, not an image-only scan."
        ) from exc
    extracted: list[list[str]] = []
    for page in pages:
        lines = [line.strip() for line in str(page.get("text") or "").splitlines() if line.strip()]
        extracted.append(lines)
    return extracted or [[]]


class LocalProDocuXVerifier:
    """Call the installed PyPI `prodocux` package in-process."""

    def verify(self, request: dict) -> dict:
        from prodocux_kernel.verification.evidence import verify_evidence_bundle

        return verify_evidence_bundle(request)

    def extract_pages(self, filename: str, payload: bytes) -> list[list[str]]:
        return extract_upload_pages(filename, payload)


class HttpProDocuXVerifier:
    """Optional colocated Kernel HTTP surface; still requires the PyPI package in CI."""

    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")

    def verify(self, request: dict) -> dict:
        response = httpx.post(
            f"{self.base_url}/verify/evidence-bundle",
            json=request,
            timeout=30,
        )
        response.raise_for_status()
        return response.json()

    def extract_pages(self, filename: str, payload: bytes) -> list[list[str]]:
        return extract_upload_pages(filename, payload)
