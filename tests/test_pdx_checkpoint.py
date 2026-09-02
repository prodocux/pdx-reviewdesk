from __future__ import annotations

from reviewdesk_api.service import ReviewDeskService


def test_correction_replaces_pdx_checkpoint_and_keeps_source_digests(tmp_path) -> None:
    service = ReviewDeskService(tmp_path)
    run = service.start_demo("agent")
    locked = [item.source_sha256 for item in run.documents]
    prior_checkpoint = run.checkpoint_id
    prior_digest = run.bundle_digest
    failed = {item.check_id for item in run.findings if item.status == "needs_review"}
    assert failed == {"formula-version", "ph-range"}

    service.propose_correction(run.run_id, "3", "Approved formula revision 3 is authoritative.", "agent")
    corrected = service.commit_correction(run.run_id, "human")
    assert [item.source_sha256 for item in corrected.documents] == locked
    assert corrected.checkpoint_id != prior_checkpoint
    assert corrected.bundle_digest != prior_digest
    revision = next(item for item in corrected.findings if item.check_id == "formula-version")
    assert revision.status == "corrected"
    ph = next(item for item in corrected.findings if item.check_id == "ph-range")
    assert ph.status == "needs_review"

    confirmed = service.confirm_observed_fact(run.run_id, "human")
    assert next(item for item in confirmed.findings if item.check_id == "ph-range").status == "confirmed"
    closed = service.decide(run.run_id, "human", "approved")
    assert closed.status == "approved"
    assert [item.source_sha256 for item in closed.documents] == locked
    assert closed.packages["prodocux"] == "0.3.0rc4"
    assert closed.packages["pdx-artifact-engine"] == "0.3.0a4"


def test_approval_and_ph_confirm_are_gated(tmp_path) -> None:
    service = ReviewDeskService(tmp_path)
    run = service.start_demo("human")
    try:
        service.confirm_observed_fact(run.run_id, "agent")
        raise AssertionError("ph confirm must wait for the revision")
    except ValueError as exc:
        assert "formula revision" in str(exc)
    try:
        service.decide(run.run_id, "agent", "approved")
        raise AssertionError("approval must wait for review")
    except ValueError as exc:
        assert "UI-only" in str(exc) or "still need review" in str(exc)
