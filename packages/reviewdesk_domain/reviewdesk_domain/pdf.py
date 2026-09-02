from __future__ import annotations

import hashlib
import zlib


def _escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def build_pdf(
    *,
    title: str,
    pages: list[tuple[str, list[str]]],
    footer: str,
    compress: bool = False,
) -> bytes:
    """Build a small PDF 1.4 document without extra dependencies.

    `compress=True` wraps content streams with FlateDecode, matching ordinary
    exported PDFs. The fixture path stays uncompressed so it is easy to inspect.
    """
    content_objects: list[bytes] = []
    for heading, lines in pages:
        chunks = ["BT", "/F1 16 Tf", "72 780 Td", f"({_escape(heading)}) Tj"]
        for line in lines:
            chunks.extend(["0 -22 Td", "/F1 11 Tf", f"({_escape(line)}) Tj"])
        chunks.extend(["0 -40 Td", "/F1 8 Tf", f"({_escape(footer)}) Tj", "ET"])
        content_objects.append("\n".join(chunks).encode("latin-1", "replace"))

    objects: list[bytes] = []
    objects.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    kids = " ".join(f"{3 + index} 0 R" for index in range(len(pages)))
    objects.append(f"<< /Type /Pages /Count {len(pages)} /Kids [{kids}] >>".encode())
    content_id_start = 3 + len(pages)
    font_id = content_id_start + len(pages)
    for index, _stream in enumerate(content_objects):
        objects.append(
            (
                f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
                f"/Resources << /Font << /F1 {font_id} 0 R >> >> "
                f"/Contents {content_id_start + index} 0 R >>"
            ).encode()
        )
    for stream in content_objects:
        payload = zlib.compress(stream) if compress else stream
        filt = " /Filter /FlateDecode" if compress else ""
        objects.append(f"<< /Length {len(payload)}{filt} >>\nstream\n".encode() + payload + b"\nendstream")
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")

    out = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for index, payload in enumerate(objects, start=1):
        offsets.append(len(out))
        out.extend(f"{index} 0 obj\n".encode())
        out.extend(payload)
        out.extend(b"\nendobj\n")
    xref_at = len(out)
    out.extend(f"xref\n0 {len(objects) + 1}\n".encode())
    out.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        out.extend(f"{offset:010d} 00000 n \n".encode())
    out.extend(
        (
            f"trailer << /Size {len(objects) + 1} /Root 1 0 R /Info << "
            f"/Title ({_escape(title)}) >> >>\nstartxref\n{xref_at}\n%%EOF\n"
        ).encode()
    )
    return bytes(out)


def sha256_hex(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()
