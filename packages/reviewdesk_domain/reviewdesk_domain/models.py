from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

Scalar = str | int | float | bool | None
Actor = Literal["human", "agent"]
ActorType = Literal["human", "agent", "system"]
InvocationChannel = Literal["ui", "webmcp", "backend"]
DocumentId = Literal["product-spec", "formula", "coa"]
FindingStatus = Literal["pass", "needs_review", "confirmed", "corrected", "rejected"]
RunStatus = Literal[
    "reviewing",
    "findings_ready",
    "correction_drafted",
    "awaiting_human_approval",
    "approved",
    "verified",
    "rejected",
    "exported",
]
UiStage = Literal["documents", "findings", "corrections", "closed"]
FindingAction = Literal["correct_subject_field", "confirm_ref_observation", "informational"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DocumentPage(StrictModel):
    page: int = Field(ge=1, le=10_000)
    title: str
    lines: list[str]
    highlight: str | None = None


class DossierDocument(StrictModel):
    document_id: DocumentId
    filename: str
    document_type: Literal[
        "product_specification", "ingredient_formula", "certificate_of_analysis"
    ]
    source_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    media_type: Literal["application/pdf"] = "application/pdf"
    role: Literal["subject", "ref"] = "ref"
    pages: list[DocumentPage] = Field(min_length=1)


class SourceLocator(StrictModel):
    page: int = Field(ge=1, le=10_000)
    snippet: str = Field(max_length=2048)


class EvidenceField(StrictModel):
    evidence_id: str
    document_id: DocumentId
    field_name: str
    value_type: Literal["string", "number", "integer", "boolean", "date", "version", "null"]
    original_value: Scalar
    normalized_value: Scalar
    confidence: float = Field(ge=0, le=1)
    source: SourceLocator


class Finding(StrictModel):
    finding_id: str
    check_id: str
    severity: Literal["medium", "high", "critical"]
    status: FindingStatus
    title: str
    message: str
    reason_codes: list[str] = []
    evidence_refs: list[str]
    expected: Scalar = None
    actual: Scalar = None
    authority_document: DocumentId
    observed_document: DocumentId
    authority_rule: str
    action: FindingAction = "informational"
    assignee: Actor = "human"


class Correction(StrictModel):
    correction_id: str
    finding_id: str
    document_id: DocumentId
    original_value: Scalar
    corrected_value: Scalar
    reason: str
    actor: Actor
    prior_bundle_digest: str
    new_bundle_digest: str


class ActivityEvent(StrictModel):
    event_id: str
    at: str
    actor: Actor
    actor_type: ActorType = "human"
    actor_id: str = ""
    invocation_channel: InvocationChannel = "backend"
    authorization_source: str = "backend"
    tool_call_id: str | None = None
    tool: str | None = None
    message: str
    viewer_document_id: DocumentId | None = None
    viewer_page: int | None = None


class DraftCorrection(StrictModel):
    value: str
    reason: str
    finding_id: str | None = None
    document_id: DocumentId | None = None
    field: str | None = None
    current_value: Scalar = None


class RunView(StrictModel):
    run_id: str
    dossier_id: str
    product_name: str
    status: RunStatus
    packages: dict[str, str]
    documents: list[DossierDocument]
    evidence: list[EvidenceField]
    findings: list[Finding]
    corrections: list[Correction] = []
    activities: list[ActivityEvent] = []
    bundle_digest: str
    checkpoint_id: str | None = None
    approval_request_id: str | None = None
    decided_by: Actor | None = None
    active_finding_id: str | None = None
    viewer_document_id: DocumentId | None = None
    viewer_page: int | None = None
    draft_correction: DraftCorrection | None = None
    stage: UiStage = "documents"
    subject_filename: str | None = None
    verification_elapsed_ms: int | None = None
    updated_at: str | None = None
    approval_requested: bool = False
    confirmation_requested: bool = False
    reviewed_pages: list[DocumentPage] = []
    summary: dict[str, int]
    manifest_paths: list[str] = []
