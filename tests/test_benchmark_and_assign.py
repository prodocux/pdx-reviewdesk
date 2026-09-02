from __future__ import annotations

from reviewdesk_api.service import ReviewDeskService
from reviewdesk_domain.benchmark import run_benchmark


def test_benchmark_has_ten_dossiers_and_twenty_plants(tmp_path) -> None:
    service = ReviewDeskService(tmp_path)
    result = service.benchmark()
    assert result["dossiers"] == 10
    assert result["planted"] == 20
    assert result["hits"] == 20
    assert result["misses"] == 0
    assert result["false_positives"] == 0
    assert result["hit_rate"] == 1.0
    live = run_benchmark(service.verifier)
    assert live["planted"] == 20


def test_agent_cannot_act_on_human_assigned_ph(tmp_path) -> None:
    service = ReviewDeskService(tmp_path)
    run = service.start_demo("human")
    service.reveal_findings(run.run_id, "human")
    opened = service.view(run.run_id)
    ph = next(item for item in opened.findings if item.finding_id == "find-ph")
    revision = next(item for item in opened.findings if item.finding_id == "find-revision")
    assert ph.assignee == "human"
    assert revision.assignee == "agent"

    service.propose_correction(
        run.run_id,
        "3",
        "Approved formula revision 3 is authoritative.",
        "agent",
        finding_id="find-revision",
    )
    service.commit_correction(run.run_id, "agent")
    try:
        service.confirm_observed_fact(run.run_id, "agent")
        raise AssertionError("agent must not confirm a human-assigned finding")
    except ValueError as exc:
        assert "assigned to the human" in str(exc)

    service.assign_finding(run.run_id, "find-ph", "agent", "human")
    confirmed = service.confirm_observed_fact(run.run_id, "agent")
    assert next(item for item in confirmed.findings if item.finding_id == "find-ph").status == "confirmed"
    assert next(item for item in confirmed.findings if item.finding_id == "find-ph").assignee == "agent"


def test_reassigning_revision_to_human_blocks_the_agent(tmp_path) -> None:
    service = ReviewDeskService(tmp_path)
    run = service.start_demo("human")
    service.reveal_findings(run.run_id, "human")
    service.assign_finding(run.run_id, "find-revision", "human", "human")
    try:
        service.propose_correction(
            run.run_id,
            "3",
            "Approved formula revision 3 is authoritative.",
            "agent",
            finding_id="find-revision",
        )
        raise AssertionError("agent must not draft a human-assigned correction")
    except ValueError as exc:
        assert "assigned to the human" in str(exc)
    human_draft = service.propose_correction(
        run.run_id,
        "3",
        "Human took the revision correction.",
        "human",
        finding_id="find-revision",
    )
    assert human_draft.draft_correction is not None
