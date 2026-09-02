from __future__ import annotations

from reviewdesk_api.main import spa_file
from reviewdesk_api.service import ReviewDeskService, require_relative_artifact
from reviewdesk_domain.ingest import MAX_UPLOAD_BYTES, pack_from_uploads, safe_upload_filename


def test_run_id_rejects_path_traversal(tmp_path) -> None:
    service = ReviewDeskService(tmp_path)
    run = service.start_demo("human")
    outside = tmp_path.parent / "secret.txt"
    outside.write_text("nope", encoding="utf-8")
    for bad in ("../secret", "..\\secret", "/", "runs", run.run_id + "/../" + run.run_id):
        try:
            service.view(bad)
            raise AssertionError(f"must reject {bad}")
        except KeyError:
            pass
    path, _name = service.source_file(run.run_id, "product-spec")
    assert path.is_relative_to(tmp_path.resolve())


def test_artifact_paths_stay_inside_run_dir(tmp_path) -> None:
    try:
        require_relative_artifact("../outside.json")
        raise AssertionError("parent traversal must fail")
    except ValueError:
        pass
    service = ReviewDeskService(tmp_path)
    run = service.start_demo("human")
    try:
        service._write(run.run_id, "../escape.json", {"ok": False})
        raise AssertionError("write escape must fail")
    except ValueError:
        pass
    assert not (tmp_path / "escape.json").exists()


def test_spa_file_stays_inside_dist(tmp_path) -> None:
    dist = tmp_path / "dist"
    assets = dist / "assets"
    assets.mkdir(parents=True)
    (assets / "app.js").write_text("ok", encoding="utf-8")
    (tmp_path / "secret.env").write_text("token", encoding="utf-8")
    assert spa_file(dist, "assets/app.js") == (assets / "app.js").resolve()
    assert spa_file(dist, "../secret.env") is None
    assert spa_file(dist, str(tmp_path / "secret.env")) is None
    assert spa_file(dist, "") is None


def test_upload_filename_strips_paths_and_control_chars() -> None:
    assert safe_upload_filename(r"..\..\evil.pdf", "fallback.pdf") == "evil.pdf"
    assert "\r" not in safe_upload_filename("a.pdf\r\nContent-Type: text/html", "fallback.pdf")
    assert safe_upload_filename("..", "slot.pdf") == "slot.pdf"


def test_upload_rejects_oversize_payload() -> None:
    too_big = b"%PDF-1.4\n" + (b"x" * (MAX_UPLOAD_BYTES + 1))
    try:
        pack_from_uploads(
            {
                "product-spec": ("spec.pdf", too_big),
                "formula": ("formula.pdf", b"%PDF-1.4\n"),
                "coa": ("coa.pdf", b"%PDF-1.4\n"),
            }
        )
        raise AssertionError("oversize upload must fail")
    except ValueError as exc:
        assert "8 MB" in str(exc)


def test_http_verifier_url_must_be_http(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("PRODOCUX_V1_BASE_URL", "file:///etc/passwd")
    try:
        ReviewDeskService(tmp_path)
        raise AssertionError("file URL must be rejected")
    except ValueError as exc:
        assert "http(s)" in str(exc)
