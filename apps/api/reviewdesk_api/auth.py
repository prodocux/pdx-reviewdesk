from __future__ import annotations

import json
import os
import re
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal

from fastapi import HTTPException, Request, Response

from reviewdesk_domain.models import Actor, InvocationChannel

COOKIE_NAME = "reviewdesk_session"
INVOCATION_HEADER = "x-reviewdesk-invocation"
CAPABILITY_HEADER = "x-reviewdesk-capability"
SESSION_TTL = timedelta(days=7)
_SESSION_ID = re.compile(r"^[A-Za-z0-9_-]{20,128}$")


@dataclass(frozen=True)
class SessionRecord:
    session_id: str
    human_capability: str
    agent_capability: str
    created_at: str
    expires_at: str


@dataclass(frozen=True)
class Invocation:
    session: SessionRecord
    actor: Actor
    channel: InvocationChannel


def _now() -> datetime:
    return datetime.now(UTC)


def session_is_expired(record: SessionRecord, now: datetime | None = None) -> bool:
    try:
        expires = datetime.fromisoformat(record.expires_at)
    except ValueError:
        return True
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=UTC)
    return (now or _now()) >= expires


class SessionStore:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, session_id: str) -> Path:
        if not _SESSION_ID.fullmatch(session_id):
            raise KeyError(session_id)
        return self.root / f"{session_id}.json"

    def create(self) -> SessionRecord:
        self.purge_expired()
        now = _now()
        record = SessionRecord(
            session_id=secrets.token_urlsafe(32),
            human_capability=secrets.token_urlsafe(32),
            agent_capability=secrets.token_urlsafe(32),
            created_at=now.isoformat(),
            expires_at=(now + SESSION_TTL).isoformat(),
        )
        self._save(record)
        return record

    def get(self, session_id: str | None) -> SessionRecord | None:
        if not session_id or not _SESSION_ID.fullmatch(session_id):
            return None
        path = self._path(session_id)
        if not path.is_file():
            return None
        raw = json.loads(path.read_text(encoding="utf-8"))
        try:
            record = SessionRecord(
                session_id=str(raw["session_id"]),
                human_capability=str(raw["human_capability"]),
                agent_capability=str(raw["agent_capability"]),
                created_at=str(raw.get("created_at") or ""),
                expires_at=str(raw.get("expires_at") or ""),
            )
        except (KeyError, TypeError):
            return None
        if not record.created_at or not record.expires_at or session_is_expired(record):
            path.unlink(missing_ok=True)
            return None
        return record

    def purge_expired(self) -> None:
        for path in self.root.glob("*.json"):
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
                record = SessionRecord(
                    session_id=str(raw["session_id"]),
                    human_capability=str(raw["human_capability"]),
                    agent_capability=str(raw["agent_capability"]),
                    created_at=str(raw.get("created_at") or ""),
                    expires_at=str(raw.get("expires_at") or ""),
                )
            except (OSError, json.JSONDecodeError, KeyError, TypeError):
                continue
            if not record.expires_at or session_is_expired(record):
                path.unlink(missing_ok=True)

    def _save(self, record: SessionRecord) -> None:
        path = self._path(record.session_id)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(
            json.dumps(
                {
                    "session_id": record.session_id,
                    "human_capability": record.human_capability,
                    "agent_capability": record.agent_capability,
                    "created_at": record.created_at,
                    "expires_at": record.expires_at,
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        os.replace(tmp, path)


def cookie_settings(request: Request) -> dict[str, object]:
    https = request.url.scheme == "https" or os.getenv("RENDER", "").lower() in {"true", "1"}
    return {
        "httponly": True,
        "secure": https,
        "samesite": "none" if https else "lax",
        "path": "/",
        "max_age": int(SESSION_TTL.total_seconds()),
    }


def set_session_cookie(response: Response, request: Request, session_id: str) -> None:
    response.set_cookie(COOKIE_NAME, session_id, **cookie_settings(request))


def derive_invocation(session: SessionRecord, request: Request) -> Invocation:
    if session_is_expired(session):
        raise HTTPException(401, "Session expired. Refresh this ReviewDesk page.")
    header = (request.headers.get(INVOCATION_HEADER) or "").strip().lower()
    token = request.headers.get(CAPABILITY_HEADER) or ""
    if header == "webmcp" and token and secrets.compare_digest(token, session.agent_capability):
        return Invocation(session=session, actor="agent", channel="webmcp")
    if header in {"", "ui"} and token and secrets.compare_digest(token, session.human_capability):
        return Invocation(session=session, actor="human", channel="ui")
    raise HTTPException(401, "A valid session capability is required.")


def authorization_source(channel: InvocationChannel) -> Literal["webmcp.tool", "reviewdesk.ui", "backend"]:
    if channel == "webmcp":
        return "webmcp.tool"
    if channel == "ui":
        return "reviewdesk.ui"
    return "backend"
