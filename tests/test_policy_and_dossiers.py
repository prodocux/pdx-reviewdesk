from __future__ import annotations

from reviewdesk_api.service import ReviewDeskService


def test_ph_finding_cannot_use_revision_correction(tmp_path) -> None:
    service = ReviewDeskService(tmp_path)
    run = service.start_demo("human")
    service.reveal_findings(run.run_id, "human")
    service.select_finding(run.run_id, "find-ph", "human")
    try:
        service.propose_correction(
            run.run_id,
            "5.2",
            "Rewrite the certificate to pass the range.",
            "agent",
            finding_id="find-ph",
        )
        raise AssertionError("pH rewrite must be policy-gated")
    except ValueError as exc:
        assert "Policy gate" in str(exc)
        assert "find-ph" in str(exc)


def test_locked_reference_rewrite_is_refused(tmp_path) -> None:
    service = ReviewDeskService(tmp_path)
    run = service.start_demo("human")
    try:
        service.rewrite_locked_reference(run.run_id, "formula", "agent")
        raise AssertionError("formula rewrite must fail")
    except ValueError as exc:
        assert "Policy gate" in str(exc)
        assert "locked" in str(exc)


def test_cedar_dossier_only_plants_revision_mismatch(tmp_path) -> None:
    service = ReviewDeskService(tmp_path)
    harbor = service.start_demo("human", "harbor-calm-serum-2026")
    cedar = service.start_demo("human", "cedar-night-cream-2026")
    harbor_fail = {item.check_id for item in harbor.findings if item.status == "needs_review"}
    cedar_fail = {item.check_id for item in cedar.findings if item.status == "needs_review"}
    assert harbor_fail == {"formula-version", "ph-range"}
    assert cedar_fail == {"formula-version"}
    assert harbor.status == "reviewing"
    assert cedar.product_name == "Cedar Night Cream"
    assert harbor.verification_elapsed_ms is not None

    service.propose_correction(cedar.run_id, "2", "Approved formula revision 2 is authoritative.", "human")
    assert service.view(cedar.run_id).status == "correction_drafted"
    corrected = service.commit_correction(cedar.run_id, "human")
    assert next(item for item in corrected.findings if item.check_id == "formula-version").status == "corrected"
    assert corrected.status == "awaiting_human_approval"
    closed = service.decide(cedar.run_id, "human", "approved")
    verified = service.verify_package(cedar.run_id)
    assert closed.status == "approved"
    assert verified["ok"] is True
    assert verified["status"] == "verified"
