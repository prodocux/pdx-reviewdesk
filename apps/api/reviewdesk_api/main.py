from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

from fastapi import Depends, FastAPI, File, HTTPException, Request, Response, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from reviewdesk_api.auth import (
    CAPABILITY_HEADER,
    COOKIE_NAME,
    INVOCATION_HEADER,
    Invocation,
    SessionRecord,
    authorization_source,
    derive_invocation,
    set_session_cookie,
)
from reviewdesk_api.service import ReviewDeskService, installed_packages
from reviewdesk_domain.ingest import EXTRACT_FAILURE, MAX_UPLOAD_BYTES
from reviewdesk_domain.models import Actor, DocumentId, InvocationChannel, RunView


class ActorRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    actor: Actor = "human"
    channel: InvocationChannel = "backend"
    authorization_source: str | None = Field(default=None, max_length=128)
    tool_call_id: str | None = Field(default=None, max_length=128)


class StartDemoRequest(ActorRequest):
    dossier_id: str | None = Field(default=None, max_length=128)


class SelectFindingRequest(ActorRequest):
    finding_id: str = Field(min_length=1, max_length=128)


class OpenDocumentRequest(ActorRequest):
    document_id: DocumentId
    page: int | None = Field(default=None, ge=1, le=10_000)


class ProposeCorrectionRequest(ActorRequest):
    proposed_value: str | None = Field(default=None, min_length=1, max_length=64)
    corrected_value: str | None = Field(default=None, min_length=1, max_length=64)
    reason: str = Field(min_length=3, max_length=1024)
    finding_id: str | None = Field(default=None, max_length=128)
    field: str | None = Field(default=None, max_length=64)
    document_id: DocumentId | None = None
    current_value: str | None = None
    evidence_refs: list[str] | None = None


class RewriteReferenceRequest(ActorRequest):
    document_id: DocumentId = "formula"


class RejectDraftRequest(ActorRequest):
    reason: str = Field(min_length=3, max_length=1024)


class DecisionRequest(ActorRequest):
    decision: Literal["approved", "rejected"] = "approved"


class AssignFindingRequest(ActorRequest):
    finding_id: str = Field(min_length=1, max_length=128)
    assignee: Actor


app = FastAPI(title="PDX ReviewDesk API", version="0.1.0-dev")
allowed_origins = [
    item.strip()
    for item in os.getenv(
        "REVIEWDESK_ALLOWED_ORIGINS",
        "http://localhost:5173,http://127.0.0.1:5173,http://localhost:3000,http://127.0.0.1:3000",
    ).split(",")
    if item.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", INVOCATION_HEADER, CAPABILITY_HEADER],
    allow_credentials=True,
)
service = ReviewDeskService()
DIST = Path(__file__).resolve().parents[2] / "web" / "dist"


def current_session(request: Request) -> SessionRecord:
    record = service.sessions.get(request.cookies.get(COOKIE_NAME))
    if record is None:
        raise HTTPException(401, "Open this ReviewDesk page to start a session.")
    return record


def current_invocation(
    request: Request, session: SessionRecord = Depends(current_session)
) -> Invocation:
    return derive_invocation(session, request)


def _caller(
    payload: ActorRequest | None, invocation: Invocation
) -> tuple[Actor, InvocationChannel, str, str | None]:
    return (
        invocation.actor,
        invocation.channel,
        authorization_source(invocation.channel),
        payload.tool_call_id if payload else None,
    )


def _owned(run_id: str, session: SessionRecord, work):
    def wrapped():
        service.require_owner(run_id, session.session_id)
        return work()

    return _run(wrapped)


@app.exception_handler(RequestValidationError)
async def request_validation(request: Request, _exc: RequestValidationError) -> JSONResponse:
    if request.url.path.rstrip("/").endswith("upload-runs"):
        return JSONResponse(status_code=409, content={"detail": EXTRACT_FAILURE})
    return JSONResponse(status_code=422, content={"detail": "The request could not be completed."})


def _public_error(exc: BaseException) -> str:
    text = str(exc)
    lowered = text.lower()
    if "pydantic" in lowered or "validation error" in lowered or "field required" in lowered:
        return EXTRACT_FAILURE
    return text


def spa_file(dist: Path, path: str) -> Path | None:
    root = dist.resolve()
    if not path:
        return None
    candidate = Path(path)
    if candidate.is_absolute() or ".." in candidate.parts:
        return None
    target = (root / candidate).resolve()
    if target.is_file() and target.is_relative_to(root):
        return target
    return None


async def _read_upload(upload: UploadFile, fallback: str) -> tuple[str, bytes]:
    payload = await upload.read(MAX_UPLOAD_BYTES + 1)
    name = upload.filename or fallback
    if len(payload) > MAX_UPLOAD_BYTES:
        raise HTTPException(409, f"{name} is larger than 8 MB.")
    return name, payload


def _run(work):
    try:
        return work()
    except KeyError as exc:
        raise HTTPException(404, "run not found") from exc
    except ValidationError as exc:
        raise HTTPException(409, EXTRACT_FAILURE) from exc
    except ValueError as exc:
        raise HTTPException(409, _public_error(exc)) from exc


@app.get("/health")
def health() -> dict:
    packages = installed_packages()
    return {
        "status": "ok",
        "prodocux": packages["prodocux"],
        "pdx_artifact_engine": packages["pdx-artifact-engine"],
        "verifier": "prodocux.evidence_bundle_v1",
        "orchestrator": "pdx.approval_and_checkpoint_v1",
    }


@app.get("/v1/session")
def session_boot(request: Request, response: Response) -> dict:
    record = service.sessions.get(request.cookies.get(COOKIE_NAME))
    if record is None:
        record = service.sessions.create()
        set_session_cookie(response, request, record.session_id)
    return {
        "ok": True,
        "human_capability": record.human_capability,
        "agent_capability": record.agent_capability,
    }


@app.post("/v1/demo-runs", response_model=RunView)
def start_demo(
    payload: StartDemoRequest | None = None,
    invocation: Invocation = Depends(current_invocation),
) -> RunView:
    actor, channel, auth, tool_call_id = _caller(payload, invocation)
    dossier_id = payload.dossier_id if payload else None
    return service.start_demo(
        actor,
        dossier_id,
        channel=channel,
        authorization_source=auth,
        tool_call_id=tool_call_id,
        owner_session_id=invocation.session.session_id,
    )


@app.post("/v1/upload-runs", response_model=RunView)
async def start_from_uploads(
    subject: UploadFile = File(...),
    formula: UploadFile = File(...),
    coa: UploadFile = File(...),
    invocation: Invocation = Depends(current_invocation),
) -> RunView:
    actor, channel, auth, tool_call_id = _caller(None, invocation)
    files = {
        "product-spec": await _read_upload(subject, "subject.pdf"),
        "formula": await _read_upload(formula, "formula.pdf"),
        "coa": await _read_upload(coa, "coa.pdf"),
    }
    return _run(
        lambda: service.start_from_uploads(
            actor,
            files,
            channel=channel,
            authorization_source=auth,
            tool_call_id=tool_call_id,
            owner_session_id=invocation.session.session_id,
        )
    )


@app.get("/v1/dossiers")
def dossiers(_session: SessionRecord = Depends(current_session)) -> dict:
    return {"dossiers": service.dossiers()}


@app.post("/v1/benchmark")
def run_benchmark(_invocation: Invocation = Depends(current_invocation)) -> dict:
    return service.benchmark()


@app.get("/v1/benchmark")
def get_benchmark(_session: SessionRecord = Depends(current_session)) -> dict:
    if service.last_benchmark is None:
        return service.benchmark()
    return service.last_benchmark


@app.get("/v1/runs")
def list_runs(session: SessionRecord = Depends(current_session)) -> dict:
    return {"runs": service.list_runs(owner_session_id=session.session_id)}


@app.get("/v1/runs/{run_id}", response_model=RunView)
def get_run(run_id: str, session: SessionRecord = Depends(current_session)) -> RunView:
    return _owned(run_id, session, lambda: service.view(run_id))


@app.post("/v1/runs/{run_id}/checks", response_model=RunView)
def reveal_findings(
    run_id: str,
    payload: ActorRequest | None = None,
    invocation: Invocation = Depends(current_invocation),
) -> RunView:
    actor, channel, auth, tool_call_id = _caller(payload, invocation)
    return _owned(
        run_id,
        invocation.session,
        lambda: service.reveal_findings(
            run_id,
            actor,
            channel=channel,
            authorization_source=auth,
            tool_call_id=tool_call_id,
        ),
    )


@app.post("/v1/runs/{run_id}/select-finding", response_model=RunView)
def select_finding(
    run_id: str,
    payload: SelectFindingRequest,
    invocation: Invocation = Depends(current_invocation),
) -> RunView:
    actor, channel, auth, tool_call_id = _caller(payload, invocation)
    return _owned(
        run_id,
        invocation.session,
        lambda: service.select_finding(
            run_id,
            payload.finding_id,
            actor,
            channel=channel,
            authorization_source=auth,
            tool_call_id=tool_call_id,
        ),
    )


@app.post("/v1/runs/{run_id}/assign-finding", response_model=RunView)
def assign_finding(
    run_id: str,
    payload: AssignFindingRequest,
    invocation: Invocation = Depends(current_invocation),
) -> RunView:
    actor, channel, auth, tool_call_id = _caller(payload, invocation)
    return _owned(
        run_id,
        invocation.session,
        lambda: service.assign_finding(
            run_id,
            payload.finding_id,
            payload.assignee,
            actor,
            channel=channel,
            authorization_source=auth,
            tool_call_id=tool_call_id,
        ),
    )


@app.post("/v1/runs/{run_id}/request-human-confirmation", response_model=RunView)
def request_human_confirmation(
    run_id: str,
    payload: ActorRequest | None = None,
    invocation: Invocation = Depends(current_invocation),
) -> RunView:
    actor, channel, auth, tool_call_id = _caller(payload, invocation)
    return _owned(
        run_id,
        invocation.session,
        lambda: service.request_human_confirmation(
            run_id,
            actor,
            channel=channel,
            authorization_source=auth,
            tool_call_id=tool_call_id,
        ),
    )


@app.post("/v1/runs/{run_id}/request-human-approval", response_model=RunView)
def request_human_approval(
    run_id: str,
    payload: ActorRequest | None = None,
    invocation: Invocation = Depends(current_invocation),
) -> RunView:
    actor, channel, auth, tool_call_id = _caller(payload, invocation)
    return _owned(
        run_id,
        invocation.session,
        lambda: service.request_human_approval(
            run_id,
            actor,
            channel=channel,
            authorization_source=auth,
            tool_call_id=tool_call_id,
        ),
    )


@app.post("/v1/runs/{run_id}/open-document", response_model=RunView)
def open_document(
    run_id: str,
    payload: OpenDocumentRequest,
    invocation: Invocation = Depends(current_invocation),
) -> RunView:
    actor, channel, auth, tool_call_id = _caller(payload, invocation)
    return _owned(
        run_id,
        invocation.session,
        lambda: service.open_document(
            run_id,
            payload.document_id,
            payload.page,
            actor,
            channel=channel,
            authorization_source=auth,
            tool_call_id=tool_call_id,
        ),
    )


@app.post("/v1/runs/{run_id}/propose-correction", response_model=RunView)
def propose_correction(
    run_id: str,
    payload: ProposeCorrectionRequest,
    invocation: Invocation = Depends(current_invocation),
) -> RunView:
    value = payload.proposed_value or payload.corrected_value
    if not value:
        raise HTTPException(422, "proposed_value is required")
    actor, channel, auth, tool_call_id = _caller(payload, invocation)
    return _owned(
        run_id,
        invocation.session,
        lambda: service.propose_correction(
            run_id,
            value,
            payload.reason,
            actor,
            finding_id=payload.finding_id,
            field=payload.field,
            document_id=payload.document_id,
            channel=channel,
            authorization_source=auth,
            tool_call_id=tool_call_id,
        ),
    )


@app.post("/v1/runs/{run_id}/rewrite-locked-reference", response_model=RunView)
def rewrite_locked_reference(
    run_id: str,
    payload: RewriteReferenceRequest,
    invocation: Invocation = Depends(current_invocation),
) -> RunView:
    actor, channel, auth, tool_call_id = _caller(payload, invocation)
    return _owned(
        run_id,
        invocation.session,
        lambda: service.rewrite_locked_reference(
            run_id,
            payload.document_id,
            actor,
            channel=channel,
            authorization_source=auth,
            tool_call_id=tool_call_id,
        ),
    )


@app.post("/v1/runs/{run_id}/reject-draft", response_model=RunView)
def reject_draft(
    run_id: str,
    payload: RejectDraftRequest,
    invocation: Invocation = Depends(current_invocation),
) -> RunView:
    actor, channel, auth, tool_call_id = _caller(payload, invocation)
    return _owned(
        run_id,
        invocation.session,
        lambda: service.reject_draft(
            run_id,
            payload.reason,
            actor,
            channel=channel,
            authorization_source=auth,
            tool_call_id=tool_call_id,
        ),
    )


@app.post("/v1/runs/{run_id}/corrections", response_model=RunView)
def commit_correction(
    run_id: str,
    payload: ActorRequest | None = None,
    invocation: Invocation = Depends(current_invocation),
) -> RunView:
    actor, channel, auth, tool_call_id = _caller(payload, invocation)
    return _owned(
        run_id,
        invocation.session,
        lambda: service.commit_correction(
            run_id,
            actor,
            channel=channel,
            authorization_source=auth,
            tool_call_id=tool_call_id,
        ),
    )


@app.post("/v1/runs/{run_id}/confirm", response_model=RunView)
def confirm(
    run_id: str,
    payload: ActorRequest | None = None,
    invocation: Invocation = Depends(current_invocation),
) -> RunView:
    actor, channel, auth, tool_call_id = _caller(payload, invocation)
    return _owned(
        run_id,
        invocation.session,
        lambda: service.confirm_observed_fact(
            run_id,
            actor,
            channel=channel,
            authorization_source=auth,
            tool_call_id=tool_call_id,
        ),
    )


@app.post("/v1/runs/{run_id}/decision", response_model=RunView)
def decide(
    run_id: str,
    payload: DecisionRequest,
    invocation: Invocation = Depends(current_invocation),
) -> RunView:
    actor, channel, auth, tool_call_id = _caller(payload, invocation)
    return _owned(
        run_id,
        invocation.session,
        lambda: service.decide(
            run_id,
            actor,
            payload.decision,
            channel=channel,
            authorization_source=auth,
            tool_call_id=tool_call_id,
        ),
    )


@app.post("/v1/runs/{run_id}/audit-package")
def audit_package(
    run_id: str,
    payload: ActorRequest | None = None,
    invocation: Invocation = Depends(current_invocation),
) -> dict:
    actor, channel, auth, tool_call_id = _caller(payload, invocation)
    return _owned(
        run_id,
        invocation.session,
        lambda: service.audit_package(
            run_id,
            actor,
            channel=channel,
            authorization_source=auth,
            tool_call_id=tool_call_id,
        ),
    )


@app.post("/v1/runs/{run_id}/verify-package")
def verify_package(
    run_id: str,
    payload: ActorRequest | None = None,
    invocation: Invocation = Depends(current_invocation),
) -> dict:
    actor, channel, auth, tool_call_id = _caller(payload, invocation)
    return _owned(
        run_id,
        invocation.session,
        lambda: service.verify_package(
            run_id,
            actor,
            channel=channel,
            authorization_source=auth,
            tool_call_id=tool_call_id,
        ),
    )


@app.get("/v1/runs/{run_id}/documents/{document_id}/file")
def download_source(
    run_id: str, document_id: DocumentId, session: SessionRecord = Depends(current_session)
):
    path, filename = _owned(run_id, session, lambda: service.source_file(run_id, document_id))
    return FileResponse(path, media_type="application/pdf", filename=filename)


@app.get("/v1/runs/{run_id}/subject-file")
def download_subject(run_id: str, session: SessionRecord = Depends(current_session)):
    path, filename = _owned(run_id, session, lambda: service.subject_file(run_id))
    return FileResponse(path, media_type="application/pdf", filename=filename)


if DIST.is_dir():
    app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")

    @app.get("/{path:path}")
    def spa(path: str):
        target = spa_file(DIST, path)
        if target is not None:
            return FileResponse(target)
        return FileResponse(DIST / "index.html")
