from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from reviewdesk_api import main
from reviewdesk_api.auth import CAPABILITY_HEADER, INVOCATION_HEADER
from reviewdesk_api.service import ReviewDeskService


@pytest.fixture
def client(tmp_path):
    previous = main.service
    main.service = ReviewDeskService(tmp_path)
    try:
        yield TestClient(main.app)
    finally:
        main.service = previous


def _session(client: TestClient, *, agent: bool = False) -> dict[str, str]:
    started = client.get("/v1/session")
    assert started.status_code == 200, started.text
    body = started.json()
    token = body["agent_capability"] if agent else body["human_capability"]
    return {
        INVOCATION_HEADER: "webmcp" if agent else "ui",
        CAPABILITY_HEADER: token,
        "Content-Type": "application/json",
    }


def test_anonymous_cannot_list_or_forge_human_approval(client: TestClient) -> None:
    listed = client.get("/v1/runs")
    assert listed.status_code == 401

    forged = client.post(
        "/v1/demo-runs",
        json={"actor": "agent", "channel": "ui"},
    )
    assert forged.status_code == 401

    human = _session(client)
    opened = client.post("/v1/demo-runs", headers=human, json={"actor": "agent", "channel": "ui"})
    assert opened.status_code == 200
    run_id = opened.json()["run_id"]
    assert opened.json()["activities"][0]["actor"] == "human"
    assert opened.json()["activities"][0]["invocation_channel"] == "ui"

    decision = client.post(
        f"/v1/runs/{run_id}/decision",
        json={"actor": "agent", "channel": "ui", "decision": "approved"},
    )
    assert decision.status_code == 401

    agent = _session(client, agent=True)
    blocked = client.post(
        f"/v1/runs/{run_id}/decision",
        headers=agent,
        json={"actor": "human", "channel": "ui", "decision": "approved"},
    )
    assert blocked.status_code == 409
    assert "UI-only" in blocked.json()["detail"]


def test_runs_and_pdfs_are_session_scoped(client: TestClient) -> None:
    human = _session(client)
    opened = client.post("/v1/demo-runs", headers=human, json={})
    run_id = opened.json()["run_id"]
    listed = client.get("/v1/runs")
    assert listed.status_code == 200
    assert [item["run_id"] for item in listed.json()["runs"]] == [run_id]
    pdf = client.get(f"/v1/runs/{run_id}/documents/product-spec/file")
    assert pdf.status_code == 200
    assert pdf.content.startswith(b"%PDF")

    other = TestClient(main.app)
    _session(other)
    assert other.get("/v1/runs").json()["runs"] == []
    assert other.get(f"/v1/runs/{run_id}").status_code == 404
    assert other.get(f"/v1/runs/{run_id}/documents/product-spec/file").status_code == 404


def test_expired_session_is_rejected(tmp_path) -> None:
    from datetime import UTC, datetime, timedelta

    from reviewdesk_api.auth import SessionRecord, SessionStore

    store = SessionStore(tmp_path)
    live = store.create()
    assert store.get(live.session_id) is not None
    expired = SessionRecord(
        session_id=live.session_id,
        human_capability=live.human_capability,
        agent_capability=live.agent_capability,
        created_at=(datetime.now(UTC) - timedelta(days=8)).isoformat(),
        expires_at=(datetime.now(UTC) - timedelta(seconds=1)).isoformat(),
    )
    store._save(expired)
    assert store.get(live.session_id) is None
    assert not (tmp_path / f"{live.session_id}.json").exists()
