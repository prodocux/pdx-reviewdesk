from __future__ import annotations

from reviewdesk_api.service import ReviewDeskService


def _ready_for_approval(service: ReviewDeskService) -> str:
    run = service.start_demo("human")
    service.reveal_findings(run.run_id, "human")
    service.propose_correction(
        run.run_id,
        "3",
        "Approved formula revision 3 is authoritative.",
        "agent",
        finding_id="find-revision",
    )
    service.commit_correction(run.run_id, "agent")
    service.confirm_observed_fact(run.run_id, "human")
    return run.run_id


def test_agent_cannot_take_a_human_finding(tmp_path) -> None:
    service = ReviewDeskService(tmp_path)
    run = service.start_demo("human")
    service.reveal_findings(run.run_id, "human")
    try:
        service.assign_finding(run.run_id, "find-ph", "agent", "agent", channel="webmcp")
        raise AssertionError("agent must not take a human finding")
    except ValueError as exc:
        assert "Human gate" in str(exc)

    handed = service.assign_finding(run.run_id, "find-revision", "human", "agent", channel="webmcp")
    assert next(item for item in handed.findings if item.finding_id == "find-revision").assignee == "human"

    taken = service.assign_finding(run.run_id, "find-ph", "agent", "human", channel="ui")
    assert next(item for item in taken.findings if item.finding_id == "find-ph").assignee == "agent"


def test_agent_cannot_record_approval(tmp_path) -> None:
    service = ReviewDeskService(tmp_path)
    run_id = _ready_for_approval(service)
    try:
        service.decide(run_id, "agent", "approved", channel="webmcp")
        raise AssertionError("agent must not record approval")
    except ValueError as exc:
        assert "UI-only" in str(exc)

    requested = service.request_human_approval(run_id, "agent", channel="webmcp")
    assert requested.approval_requested is True
    assert requested.status == "awaiting_human_approval"

    closed = service.decide(run_id, "human", "approved", channel="ui")
    assert closed.status == "approved"
    approval = next(item for item in closed.activities if item.tool == "record_approval")
    assert approval.actor == "human"
    assert approval.invocation_channel == "ui"
    assert approval.authorization_source == "reviewdesk.ui"


def test_verify_does_not_export_and_keeps_agent_actor(tmp_path) -> None:
    service = ReviewDeskService(tmp_path)
    run_id = _ready_for_approval(service)
    service.decide(run_id, "human", "approved", channel="ui")
    verified = service.verify_package(run_id, "agent", channel="webmcp")
    assert verified["ok"] is True
    assert verified["status"] == "verified"
    view = service.view(run_id)
    assert view.status == "verified"
    assert view.summary["confirmed"] == 1
    assert view.summary["unresolved"] == 0
    event = next(item for item in view.activities if item.tool == "verify_package")
    assert event.actor == "agent"
    assert event.invocation_channel == "webmcp"
    exported = service.audit_package(run_id, "agent", channel="webmcp", tool_call_id="tc_export")
    assert exported["status"] == "exported"
    assert exported["approval"]["channel"] == "ui"
    assert exported["export"]["actor"] == "agent"
    assert exported["export"]["channel"] == "webmcp"
    assert exported["export"]["authorization_source"] == "webmcp.tool"
    event = next(item for item in service.view(run_id).activities if item.tool == "export_audit_package")
    assert event.actor == "agent"
    assert event.invocation_channel == "webmcp"
    assert event.authorization_source == "webmcp.tool"
    assert event.tool_call_id == "tc_export"
    assert service.view(run_id).status == "exported"


def _event(run, tool: str):
    return next(item for item in run.activities if item.tool == tool)


def test_actor_context_follows_webmcp_and_ui(tmp_path) -> None:
    service = ReviewDeskService(tmp_path)
    run = service.start_demo("human", channel="ui")
    opened = service.reveal_findings(
        run.run_id, "agent", channel="webmcp", tool_call_id="tc_checks"
    )
    checks = _event(opened, "run_checks")
    assert checks.actor == "agent"
    assert checks.actor_type == "agent"
    assert checks.invocation_channel == "webmcp"
    assert checks.authorization_source == "webmcp.tool"
    assert checks.tool_call_id == "tc_checks"

    selected = service.select_finding(
        run.run_id, "find-revision", "agent", channel="webmcp", tool_call_id="tc_select"
    )
    focus = _event(selected, "select_finding")
    assert focus.actor == "agent"
    assert focus.invocation_channel == "webmcp"
    assert focus.authorization_source == "webmcp.tool"

    proposed = service.propose_correction(
        run.run_id,
        "3",
        "Approved formula revision 3 is authoritative.",
        "agent",
        finding_id="find-revision",
        channel="webmcp",
        tool_call_id="tc_propose",
    )
    draft = _event(proposed, "propose_correction")
    assert draft.actor == "agent"
    assert draft.invocation_channel == "webmcp"

    committed = service.commit_correction(
        run.run_id, "agent", channel="webmcp", tool_call_id="tc_commit"
    )
    commit = _event(committed, "commit_correction")
    assert commit.actor == "agent"
    assert commit.invocation_channel == "webmcp"
    assert commit.authorization_source == "webmcp.tool"

    confirmed = service.confirm_observed_fact(
        run.run_id, "human", channel="ui", tool_call_id="tc_confirm"
    )
    observe = _event(confirmed, "confirm_observed_fact")
    assert observe.actor == "human"
    assert observe.actor_type == "human"
    assert observe.invocation_channel == "ui"
    assert observe.authorization_source == "reviewdesk.ui"
    assert observe.tool_call_id == "tc_confirm"


def test_http_passes_channel_into_activity(tmp_path, monkeypatch) -> None:
    from fastapi.testclient import TestClient
    from reviewdesk_api import main
    from reviewdesk_api.auth import CAPABILITY_HEADER, INVOCATION_HEADER

    service = ReviewDeskService(tmp_path)
    monkeypatch.setattr(main, "service", service)
    client = TestClient(main.app)
    caps = client.get("/v1/session").json()
    agent = {
        INVOCATION_HEADER: "webmcp",
        CAPABILITY_HEADER: caps["agent_capability"],
        "Content-Type": "application/json",
    }
    human = {
        INVOCATION_HEADER: "ui",
        CAPABILITY_HEADER: caps["human_capability"],
        "Content-Type": "application/json",
    }
    opened = client.post("/v1/demo-runs", headers=agent, json={})
    assert opened.status_code == 200, opened.text
    run_id = opened.json()["run_id"]
    checks = client.post(
        f"/v1/runs/{run_id}/checks",
        headers=agent,
        json={"tool_call_id": "http_checks"},
    )
    assert checks.status_code == 200, checks.text
    event = next(item for item in checks.json()["activities"] if item["tool"] == "run_checks")
    assert event["actor"] == "agent"
    assert event["invocation_channel"] == "webmcp"
    assert event["authorization_source"] == "webmcp.tool"
    assert event["tool_call_id"] == "http_checks"

    service.propose_correction(
        run_id,
        "3",
        "Approved formula revision 3 is authoritative.",
        "agent",
        finding_id="find-revision",
        channel="webmcp",
    )
    service.commit_correction(run_id, "agent", channel="webmcp")

    confirm = client.post(
        f"/v1/runs/{run_id}/confirm",
        headers=human,
        json={"tool_call_id": "http_confirm"},
    )
    assert confirm.status_code == 200, confirm.text
    observe = next(
        item for item in confirm.json()["activities"] if item["tool"] == "confirm_observed_fact"
    )
    assert observe["actor"] == "human"
    assert observe["invocation_channel"] == "ui"
    assert observe["authorization_source"] == "reviewdesk.ui"
    assert observe["tool_call_id"] == "http_confirm"

    service.decide(run_id, "human", "approved", channel="ui")
    exported = client.post(
        f"/v1/runs/{run_id}/audit-package",
        headers=agent,
        json={"tool_call_id": "http_export"},
    )
    assert exported.status_code == 200, exported.text
    payload = exported.json()
    assert payload["export"]["actor"] == "agent"
    assert payload["export"]["channel"] == "webmcp"
    trail = next(
        item for item in service.view(run_id).activities if item.tool == "export_audit_package"
    )
    assert trail.actor == "agent"
    assert trail.invocation_channel == "webmcp"
