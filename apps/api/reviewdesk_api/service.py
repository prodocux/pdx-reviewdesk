from __future__ import annotations

import functools
import json
import os
import re
import threading
import time
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path
from typing import Any, Literal

from pdx_artifact_core import canonical_digest, validate_execution_plan
from reviewdesk_adapter_pdx import ApprovalWorkflow
from reviewdesk_api.auth import SessionStore
from reviewdesk_adapter_prodocux import HttpProDocuXVerifier, LocalProDocuXVerifier
from reviewdesk_domain.benchmark import run_benchmark
from reviewdesk_domain.fixture import (
    list_dossiers,
    load_dossier,
    original_pdf_bytes,
    reviewed_subject_pages,
    reviewed_subject_pdf_bytes,
)
from reviewdesk_domain.ingest import pack_from_uploads, subject_display_name
from reviewdesk_domain.models import (
    ActivityEvent,
    Actor,
    Correction,
    DocumentId,
    DraftCorrection,
    EvidenceField,
    InvocationChannel,
    RunView,
)
from reviewdesk_domain.pdf import sha256_hex
from reviewdesk_domain.policy import CORRECTION_TARGET, compile_pif_checks, findings_from_verification

ROOT = Path(__file__).resolve().parents[3]
_RUN_ID = re.compile(r"^run_[a-f0-9]{12}$")


def require_run_id(run_id: str) -> str:
    if not _RUN_ID.fullmatch(run_id):
        raise KeyError(run_id)
    return run_id


def require_relative_artifact(name: str) -> Path:
    relative = Path(name)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError("invalid artifact path")
    return relative


def installed_packages() -> dict[str, str]:
    return {
        "prodocux": version("prodocux"),
        "pdx-artifact-engine": version("pdx-artifact-engine"),
    }


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _actor_id(actor: Actor) -> str:
    return f"reviewdesk-{actor}"


class ReviewDeskService:
    def __init__(self, runs_dir: Path | None = None) -> None:
        self.runs_dir = (runs_dir or Path(os.getenv("REVIEWDESK_RUNS_DIR", ROOT / "runs"))).resolve()
        self.runs_dir.mkdir(parents=True, exist_ok=True)
        self.runs: dict[str, dict[str, Any]] = {}
        self.approvals = ApprovalWorkflow()
        base = os.getenv("PRODOCUX_V1_BASE_URL", "").strip()
        if base and not base.startswith(("http://", "https://")):
            raise ValueError("PRODOCUX_V1_BASE_URL must be an http(s) URL.")
        self.verifier = HttpProDocuXVerifier(base) if base else LocalProDocuXVerifier()
        self.packages = installed_packages()
        self.last_benchmark: dict[str, Any] | None = None
        self.sessions = SessionStore(self.runs_dir / "_sessions")
        self._lock_table = threading.Lock()
        self._run_locks: dict[str, threading.RLock] = {}

    def _lock_for(self, run_id: str) -> threading.RLock:
        with self._lock_table:
            lock = self._run_locks.get(run_id)
            if lock is None:
                lock = threading.RLock()
                self._run_locks[run_id] = lock
            return lock

    def start_demo(
        self,
        actor: Actor,
        dossier_id: str | None = None,
        *,
        channel: InvocationChannel = "backend",
        authorization_source: str | None = None,
        tool_call_id: str | None = None,
        owner_session_id: str | None = None,
    ) -> RunView:
        run_id = f"run_{uuid.uuid4().hex[:12]}"
        pack = load_dossier(dossier_id)
        with self._lock_for(run_id):
            return self._open_run(
                run_id,
                pack,
                actor,
                "start_demo_audit",
                channel=channel,
                authorization_source=authorization_source,
                tool_call_id=tool_call_id,
                owner_session_id=owner_session_id,
            )

    def start_from_uploads(
        self,
        actor: Actor,
        files: dict[str, tuple[str, bytes]],
        *,
        channel: InvocationChannel = "backend",
        authorization_source: str | None = None,
        tool_call_id: str | None = None,
        owner_session_id: str | None = None,
    ) -> RunView:
        run_id = f"run_{uuid.uuid4().hex[:12]}"
        pack = pack_from_uploads(files)
        with self._lock_for(run_id):
            return self._open_run(
                run_id,
                pack,
                actor,
                "ingest_dropped_dossier",
                channel=channel,
                authorization_source=authorization_source,
                tool_call_id=tool_call_id,
                owner_session_id=owner_session_id,
            )

    def dossiers(self) -> list[dict[str, Any]]:
        return list_dossiers()

    def benchmark(self) -> dict[str, Any]:
        result = run_benchmark(self.verifier)
        result["packages"] = self.packages
        self.last_benchmark = result
        return result

    def assign_finding(
        self,
        run_id: str,
        finding_id: str,
        assignee: Actor,
        actor: Actor,
        *,
        channel: InvocationChannel = "backend",
        authorization_source: str | None = None,
        tool_call_id: str | None = None,
    ) -> RunView:
        actor, channel, auth, tool_call_id = self._bind_call(
            actor, channel, authorization_source, tool_call_id
        )
        if (actor == "agent" or channel == "webmcp") and assignee == "agent":
            raise ValueError(
                "Human gate: the agent cannot take a finding. Assign it to the human, "
                "or a human must reassign it in the UI."
            )
        state = self._get(run_id)
        if state["status"] in {"approved", "verified", "rejected", "exported"}:
            raise ValueError("Assignments are closed after the audit is decided.")
        finding = next((item for item in state["findings"] if item.finding_id == finding_id), None)
        if finding is None:
            raise ValueError(f"Unknown finding: {finding_id}")
        finding.assignee = assignee
        self._activity(
            state,
            actor,
            "assign_finding",
            f"Assigned {finding.finding_id} ({finding.check_id}) to the {assignee}.",
            channel=channel,
            authorization_source=auth,
            tool_call_id=tool_call_id,
        )
        self._persist(state)
        return self.view(run_id)

    def request_human_confirmation(
        self,
        run_id: str,
        actor: Actor,
        *,
        channel: InvocationChannel = "backend",
        authorization_source: str | None = None,
        tool_call_id: str | None = None,
    ) -> RunView:
        actor, channel, auth, tool_call_id = self._bind_call(
            actor, channel, authorization_source, tool_call_id
        )
        state = self._get(run_id)
        finding = next(
            (
                item
                for item in state["findings"]
                if item.check_id == "ph-range" and item.status == "needs_review"
            ),
            None,
        )
        if finding is None:
            raise ValueError("No observed pH deviation is waiting for confirmation.")
        if finding.assignee != "human":
            raise ValueError("This observation is assigned to the agent. Call confirm_observed_fact.")
        revision = next(
            (item for item in state["findings"] if item.check_id == "formula-version"),
            None,
        )
        if revision and revision.status == "needs_review":
            raise ValueError("Resolve the formula revision correction first.")
        state["confirmation_requested"] = True
        self._activity(
            state,
            actor,
            "request_human_confirmation",
            (
                f"Requested human confirmation of {finding.finding_id}: CoA pH {finding.actual} "
                "stays as an observed batch fact. The agent cannot confirm this gate."
            ),
            channel=channel,
            authorization_source=auth,
            tool_call_id=tool_call_id,
        )
        self._persist(state)
        return self.view(run_id)

    def request_human_approval(
        self,
        run_id: str,
        actor: Actor,
        *,
        channel: InvocationChannel = "backend",
        authorization_source: str | None = None,
        tool_call_id: str | None = None,
    ) -> RunView:
        actor, channel, auth, tool_call_id = self._bind_call(
            actor, channel, authorization_source, tool_call_id
        )
        state = self._get(run_id)
        self._refresh_status(state)
        if state["status"] != "awaiting_human_approval":
            raise ValueError("Human approval can be requested only after findings are resolved.")
        state["approval_requested"] = True
        checkpoint_id = state["checkpoint"]["checkpoint_id"]
        self._activity(
            state,
            actor,
            "request_human_approval",
            (
                f"Requested human approval of PDX checkpoint {checkpoint_id}. "
                "record_approval is UI-only and cannot be called by the agent."
            ),
            channel=channel,
            authorization_source=auth,
            tool_call_id=tool_call_id,
        )
        self._persist(state)
        return self.view(run_id)

    def _assignees(self, state: dict[str, Any]) -> dict[str, str]:
        return {item.check_id: item.assignee for item in state.get("findings") or [] if item.assignee}

    def _refuse_agent_on_human_finding(self, finding, actor: Actor) -> None:
        if actor == "agent" and finding.assignee == "human":
            raise ValueError(
                f"{finding.finding_id} is assigned to the human. "
                "Reassign it with assign_finding, or let the human act."
            )

    def reveal_findings(
        self,
        run_id: str,
        actor: Actor,
        *,
        channel: InvocationChannel = "backend",
        authorization_source: str | None = None,
        tool_call_id: str | None = None,
    ) -> RunView:
        actor, channel, auth, tool_call_id = self._bind_call(
            actor, channel, authorization_source, tool_call_id
        )
        state = self._get(run_id)
        if state["stage"] not in {"documents", "findings"}:
            raise ValueError("Findings are already open for this run.")
        if state["stage"] == "documents":
            state["stage"] = "findings"
            state["status"] = "findings_ready"
            first = next((item for item in state["findings"] if item.status == "needs_review"), None)
            if first is not None:
                self._focus_finding(state, first)
            review = sum(item.status == "needs_review" for item in state["findings"])
            passed = sum(item.status in {"pass", "corrected"} for item in state["findings"])
            elapsed = state.get("verification_elapsed_ms")
            timing = f" ProDocuX returned in {elapsed} ms." if elapsed is not None else ""
            self._activity(
                state,
                actor,
                "run_checks",
                f"Opened ProDocuX findings. {review} need review, {passed} passed.{timing}",
                channel=channel,
                authorization_source=auth,
                tool_call_id=tool_call_id,
            )
            self._persist(state)
        return self.view(run_id)

    def select_finding(
        self,
        run_id: str,
        finding_id: str,
        actor: Actor,
        *,
        channel: InvocationChannel = "backend",
        authorization_source: str | None = None,
        tool_call_id: str | None = None,
    ) -> RunView:
        actor, channel, auth, tool_call_id = self._bind_call(
            actor, channel, authorization_source, tool_call_id
        )
        state = self._get(run_id)
        if state["stage"] == "documents":
            raise ValueError("Open the findings step before selecting a finding.")
        finding = next((item for item in state["findings"] if item.finding_id == finding_id), None)
        if finding is None:
            raise ValueError(f"Unknown finding: {finding_id}")
        if finding.status == "needs_review":
            state["stage"] = "corrections"
        self._focus_finding(state, finding)
        self._activity(
            state,
            actor,
            "select_finding",
            f"Focused {finding.check_id}: {finding.title}",
            channel=channel,
            authorization_source=auth,
            tool_call_id=tool_call_id,
        )
        self._persist(state)
        return self.view(run_id)

    def _focus_finding(self, state: dict[str, Any], finding) -> None:
        page = 1
        target_doc = (
            finding.observed_document
            if finding.action in {"correct_subject_field", "confirm_ref_observation"}
            else finding.authority_document
        )
        if finding.evidence_refs:
            match = next(
                (
                    item
                    for item in state["evidence"]
                    if item.evidence_id in finding.evidence_refs and item.document_id == target_doc
                ),
                None,
            )
            if match is None:
                match = next(
                    (
                        item
                        for item in state["evidence"]
                        if item.evidence_id == finding.evidence_refs[0]
                    ),
                    None,
                )
            if match is not None:
                page = match.source.page
                target_doc = match.document_id
        state["active_finding_id"] = finding.finding_id
        state["viewer_document_id"] = target_doc
        state["viewer_page"] = page

    def open_document(
        self,
        run_id: str,
        document_id: DocumentId,
        page: int | None,
        actor: Actor,
        *,
        channel: InvocationChannel = "backend",
        authorization_source: str | None = None,
        tool_call_id: str | None = None,
    ) -> RunView:
        actor, channel, auth, tool_call_id = self._bind_call(
            actor, channel, authorization_source, tool_call_id
        )
        state = self._get(run_id)
        document = next(
            (item for item in state["documents"] if item.document_id == document_id),
            None,
        )
        if document is None:
            raise ValueError(f"Unknown document: {document_id}")
        target = page or 1
        if not any(item.page == target for item in document.pages):
            raise ValueError(f"Document {document_id} has no page {target}")
        state["viewer_document_id"] = document_id
        state["viewer_page"] = target
        self._activity(
            state,
            actor,
            "open_source_document",
            f"Opened {document.filename} at page {target}. Source digest {document.source_sha256[:12]}… is unchanged.",
            channel=channel,
            authorization_source=auth,
            tool_call_id=tool_call_id,
        )
        self._persist(state)
        return self.view(run_id)

    def propose_correction(
        self,
        run_id: str,
        corrected_value: str,
        reason: str,
        actor: Actor,
        *,
        finding_id: str | None = None,
        field: str | None = None,
        document_id: DocumentId | None = None,
        channel: InvocationChannel = "backend",
        authorization_source: str | None = None,
        tool_call_id: str | None = None,
    ) -> RunView:
        actor, channel, auth, tool_call_id = self._bind_call(
            actor, channel, authorization_source, tool_call_id
        )
        state = self._get(run_id)
        finding = self._resolve_correction_finding(state, finding_id, document_id, field, actor)
        if len(reason.strip()) < 3:
            raise ValueError("Give an audit reason the human can read before commit.")
        target_document, field_name = CORRECTION_TARGET[finding.check_id]
        current = next(
            (
                item.normalized_value
                for item in state["evidence"]
                if item.document_id == target_document and item.field_name == field_name
            ),
            finding.actual,
        )
        state["draft_correction"] = DraftCorrection(
            value=str(corrected_value).strip(),
            reason=reason.strip(),
            finding_id=finding.finding_id,
            document_id=target_document,
            field=field_name,
            current_value=current,
        )
        state["status"] = "correction_drafted"
        self._activity(
            state,
            actor,
            "propose_correction",
            (
                f"Proposed subject {field_name} {current} → {corrected_value} on {finding.finding_id}. "
                "Locked source PDF is still untouched."
            ),
            channel=channel,
            authorization_source=auth,
            tool_call_id=tool_call_id,
        )
        self._persist(state)
        return self.view(run_id)

    def rewrite_locked_reference(
        self,
        run_id: str,
        document_id: DocumentId,
        actor: Actor,
        *,
        channel: InvocationChannel = "backend",
        authorization_source: str | None = None,
        tool_call_id: str | None = None,
    ) -> RunView:
        actor, channel, auth, tool_call_id = self._bind_call(
            actor, channel, authorization_source, tool_call_id
        )
        state = self._get(run_id)
        document = next(
            (item for item in state["documents"] if item.document_id == document_id),
            None,
        )
        if document is None:
            raise ValueError(f"Unknown document: {document_id}")
        self._activity(
            state,
            actor,
            "rewrite_locked_reference",
            f"Policy gate blocked a rewrite of {document.filename}. References stay immutable.",
            channel=channel,
            authorization_source=auth,
            tool_call_id=tool_call_id,
        )
        self._persist(state)
        raise ValueError(
            f"Policy gate: {document_id} is a locked {document.role} document. "
            "ReviewDesk will not overwrite reference PDFs. Correct a subject field, or confirm a reference observation."
        )

    def reject_draft(
        self,
        run_id: str,
        reason: str,
        actor: Actor,
        *,
        channel: InvocationChannel = "backend",
        authorization_source: str | None = None,
        tool_call_id: str | None = None,
    ) -> RunView:
        actor, channel, auth, tool_call_id = self._bind_call(
            actor, channel, authorization_source, tool_call_id
        )
        state = self._get(run_id)
        draft = state.get("draft_correction")
        if draft is None:
            raise ValueError("There is no correction draft to reject.")
        if len(reason.strip()) < 3:
            raise ValueError("Record why the draft is rejected.")
        state["draft_correction"] = None
        self._refresh_status(state)
        self._activity(
            state,
            actor,
            "reject_draft",
            f"Rejected draft {draft.field}={draft.value}. Human reason: {reason.strip()}. Agent proposal was retained in the log.",
            channel=channel,
            authorization_source=auth,
            tool_call_id=tool_call_id,
        )
        self._persist(state)
        return self.view(run_id)

    def _resolve_correction_finding(
        self,
        state: dict[str, Any],
        finding_id: str | None,
        document_id: DocumentId | None,
        field: str | None,
        actor: Actor,
    ):
        if document_id:
            document = next(
                (item for item in state["documents"] if item.document_id == document_id),
                None,
            )
            if document is not None and document.role == "ref":
                raise ValueError(
                    f"Policy gate: {document_id} is a locked reference. "
                    "Correct the subject specification field only. Call rewrite_locked_reference to demonstrate the refusal."
                )
        selected_id = finding_id or state.get("active_finding_id")
        finding = next(
            (item for item in state["findings"] if item.finding_id == selected_id),
            None,
        )
        if finding is None:
            finding = next(
                (
                    item
                    for item in state["findings"]
                    if item.check_id == "formula-version" and item.status == "needs_review"
                ),
                None,
            )
        if finding is None:
            raise ValueError("No finding is waiting for a subject-field correction.")
        if finding.action == "confirm_ref_observation":
            raise ValueError(
                f"Policy gate: {finding.finding_id} ({finding.check_id}) is a locked reference observation "
                f"(actual={finding.actual}). Do not rewrite {finding.observed_document}. Use confirm_observed_fact."
            )
        self._refuse_agent_on_human_finding(finding, actor)
        if finding.action != "correct_subject_field" or finding.status != "needs_review":
            raise ValueError(
                f"{finding.finding_id} is not an open subject-field correction. Current action={finding.action}, status={finding.status}."
            )
        target_document, field_name = CORRECTION_TARGET.get(finding.check_id, (None, None))
        if field and field_name and field != field_name:
            raise ValueError(
                f"Field {field} cannot be corrected on {finding.finding_id}. Expected {field_name} on {target_document}."
            )
        if document_id and target_document and document_id != target_document:
            raise ValueError(
                f"Document {document_id} is not the correction target for {finding.finding_id}."
            )
        return finding

    def commit_correction(
        self,
        run_id: str,
        actor: Actor,
        *,
        channel: InvocationChannel = "backend",
        authorization_source: str | None = None,
        tool_call_id: str | None = None,
    ) -> RunView:
        actor, channel, auth, tool_call_id = self._bind_call(
            actor, channel, authorization_source, tool_call_id
        )
        state = self._get(run_id)
        draft = state.get("draft_correction")
        if draft is None:
            raise ValueError("Propose a correction before committing.")
        finding = next(
            (
                item
                for item in state["findings"]
                if item.check_id == "formula-version" and item.status == "needs_review"
            ),
            None,
        )
        if finding is None:
            raise ValueError("The formula-version finding is not open.")
        self._refuse_agent_on_human_finding(finding, actor)
        locked = [item.source_sha256 for item in state["documents"]]
        prior = state["bundle_digest"]
        target_document, field_name = CORRECTION_TARGET["formula-version"]
        for item in state["evidence"]:
            if item.document_id == target_document and item.field_name == field_name:
                item.normalized_value = draft.value
                break
        else:
            raise ValueError("Correction target evidence was not found.")
        verification = self._verify(state, f"verify-{run_id}-c{len(state['corrections']) + 1}")
        state["corrected_checks"].add("formula-version")
        state["findings"] = findings_from_verification(
            verification,
            corrected_checks=state["corrected_checks"],
            confirmed_checks=state["confirmed_checks"],
            assignees=self._assignees(state),
        )
        bundle = self._bundle_payload(state)
        cancelled, plan, checkpoint, approval = self.approvals.replace_after_correction(
            run_id=run_id,
            old_checkpoint=state["checkpoint"],
            evidence_bundle=bundle,
        )
        errors = validate_execution_plan(plan)
        if errors:
            raise RuntimeError("invalid ReviewDesk execution plan: " + "; ".join(errors))
        digest = canonical_digest(bundle)
        state.update(
            verification=verification,
            plan=plan,
            checkpoint=checkpoint,
            approval=approval,
            cancelled_checkpoint=cancelled,
            bundle_digest=digest,
            draft_correction=None,
        )
        state["corrections"].append(
            Correction(
                correction_id=f"cor_{uuid.uuid4().hex[:12]}",
                finding_id=finding.finding_id,
                document_id=target_document,
                original_value=finding.actual,
                corrected_value=draft.value,
                reason=draft.reason,
                actor=actor,
                prior_bundle_digest=prior,
                new_bundle_digest=digest,
            )
        )
        if [item.source_sha256 for item in state["documents"]] != locked:
            raise RuntimeError("Source document digests must remain immutable.")
        focused = next(
            (item for item in state["findings"] if item.status == "needs_review"),
            finding,
        )
        state["active_finding_id"] = focused.finding_id
        self._refresh_status(state)
        self._activity(
            state,
            actor,
            "commit_correction",
            f"Committed specification revision {draft.value}, reran ProDocuX, and replaced PDX checkpoint {checkpoint['checkpoint_id']}.",
            channel=channel,
            authorization_source=auth,
            tool_call_id=tool_call_id,
        )
        self._persist(state)
        return self.view(run_id)

    def confirm_observed_fact(
        self,
        run_id: str,
        actor: Actor,
        *,
        channel: InvocationChannel = "backend",
        authorization_source: str | None = None,
        tool_call_id: str | None = None,
    ) -> RunView:
        actor, channel, auth, tool_call_id = self._bind_call(
            actor, channel, authorization_source, tool_call_id
        )
        state = self._get(run_id)
        revision = next(
            (item for item in state["findings"] if item.check_id == "formula-version"),
            None,
        )
        if revision and revision.status == "needs_review":
            raise ValueError("Resolve the formula revision correction first.")
        finding = next(
            (
                item
                for item in state["findings"]
                if item.check_id == "ph-range" and item.status == "needs_review"
            ),
            None,
        )
        if finding is None:
            raise ValueError("No observed pH deviation is waiting for confirmation.")
        self._refuse_agent_on_human_finding(finding, actor)
        state["confirmed_checks"].add("ph-range")
        state["findings"] = findings_from_verification(
            state["verification"],
            corrected_checks=state["corrected_checks"],
            confirmed_checks=state["confirmed_checks"],
            assignees=self._assignees(state),
        )
        state["active_finding_id"] = finding.finding_id
        self._refresh_status(state)
        self._activity(
            state,
            actor,
            "confirm_observed_fact",
            "Confirmed the certificate pH as an observed batch fact. ProDocuX still reports the range failure; the certificate source digest is unchanged.",
            channel=channel,
            authorization_source=auth,
            tool_call_id=tool_call_id,
        )
        self._persist(state)
        return self.view(run_id)

    def decide(
        self,
        run_id: str,
        actor: Actor,
        decision: Literal["approved", "rejected"],
        *,
        channel: InvocationChannel = "backend",
        authorization_source: str | None = None,
        tool_call_id: str | None = None,
    ) -> RunView:
        actor, channel, auth, tool_call_id = self._bind_call(
            actor, channel, authorization_source, tool_call_id
        )
        if actor == "agent" or channel == "webmcp":
            raise ValueError(
                "Human gate: record_approval is UI-only. Call request_human_approval."
            )
        state = self._get(run_id)
        if state["status"] in {"approved", "verified", "rejected", "exported"}:
            raise ValueError("run is not awaiting approval")
        if decision == "approved" and any(
            item.status == "needs_review" for item in state["findings"]
        ):
            raise ValueError("Approval is blocked while findings still need review.")
        self._refresh_status(state)
        if decision == "approved" and state["status"] != "awaiting_human_approval":
            raise ValueError("Approval is blocked while findings still need review.")
        saved, resumed = self.approvals.decide(
            plan=state["plan"],
            checkpoint=state["checkpoint"],
            request=state["approval"],
            actor_id=_actor_id(actor),
            decision=decision,
        )
        state["status"] = "approved" if decision == "approved" else "rejected"
        state["stage"] = "closed"
        state["decided_by"] = actor
        state["decision"] = saved
        state["resumed_plan"] = resumed
        if decision == "approved":
            spec = next(item for item in state["documents"] if item.document_id == "product-spec")
            revision = next(
                (
                    str(item.normalized_value)
                    for item in state["evidence"]
                    if item.document_id == "product-spec" and item.field_name == "formula_revision"
                ),
                "3",
            )
            stem = spec.filename.removesuffix(".pdf")
            subject_name = f"{stem}-reviewed.pdf"
            payload = reviewed_subject_pdf_bytes(spec, formula_revision=revision)
            self._write_bytes(run_id, f"subject/{subject_name}", payload)
            state["subject_filename"] = subject_name
            state["reviewed_pages"] = reviewed_subject_pages(spec, formula_revision=revision)
        artifact_manifest = {
            "schema_version": "reviewdesk_artifact_manifest_v1",
            "run_id": run_id,
            "packages": self.packages,
            "input_digests": {
                item.document_id: item.source_sha256 for item in state["documents"]
            },
            "evidence_bundle_digest": state["bundle_digest"],
            "verification_digest": canonical_digest(state["verification"]),
            "decision_digest": canonical_digest(saved),
        }
        run_manifest = {
            "schema_version": "reviewdesk_run_manifest_v1",
            "run_id": run_id,
            "status": state["status"],
            "completed_at": _now(),
            "checkpoint_id": state["checkpoint"]["checkpoint_id"],
        }
        self._write(run_id, "approval_decision.json", saved)
        self._write(run_id, "artifact_manifest.json", artifact_manifest)
        self._write(run_id, "run_manifest.json", run_manifest)
        state["manifest_paths"] = [
            "artifact_manifest.json",
            "run_manifest.json",
            "approval_decision.json",
        ]
        self._activity(
            state,
            actor,
            "record_approval",
            (
                f"Recorded {decision} on PDX checkpoint {state['checkpoint']['checkpoint_id']}."
                + (
                    " The reviewed subject PDF is now downloadable; original source files stay locked."
                    if decision == "approved"
                    else ""
                )
            ),
            channel=channel,
            authorization_source=auth,
            tool_call_id=tool_call_id,
        )
        self._persist(state)
        return self.view(run_id)

    def audit_package(
        self,
        run_id: str,
        actor: Actor = "human",
        *,
        channel: InvocationChannel = "backend",
        authorization_source: str | None = None,
        tool_call_id: str | None = None,
    ) -> dict[str, Any]:
        actor, channel, auth, tool_call_id = self._bind_call(
            actor, channel, authorization_source, tool_call_id
        )
        state = self._get(run_id)
        if state["status"] not in {"approved", "verified", "exported"}:
            raise ValueError("Export is available after approval.")
        view = self.view(run_id)
        state["status"] = "exported"
        state["stage"] = "closed"
        self._activity(
            state,
            actor,
            "export_audit_package",
            "Exported the checksummed audit package. Source PDF bytes are not included.",
            channel=channel,
            authorization_source=auth,
            tool_call_id=tool_call_id,
        )
        self._persist(state)
        return {
            "schema_version": "pdx_reviewdesk_audit_v1",
            "packages": self.packages,
            **view.model_dump(mode="json"),
            "status": "exported",
            "approval": {
                "actor": state.get("decided_by"),
                "channel": "ui",
                "authorization_source": "reviewdesk.ui",
                "checkpoint_id": state["checkpoint"]["checkpoint_id"],
            },
            "export": {
                "actor": actor,
                "channel": channel,
                "authorization_source": auth,
                "tool_call_id": tool_call_id,
            },
        }

    def verify_package(
        self,
        run_id: str,
        actor: Actor = "human",
        *,
        channel: InvocationChannel = "backend",
        authorization_source: str | None = None,
        tool_call_id: str | None = None,
    ) -> dict[str, Any]:
        actor, channel, auth, tool_call_id = self._bind_call(
            actor, channel, authorization_source, tool_call_id
        )
        state = self._get(run_id)
        if state["status"] not in {"approved", "verified", "exported"}:
            raise ValueError("Verify is available after approval.")
        checks: list[dict[str, Any]] = []
        for document in state["documents"]:
            path = self.runs_dir / run_id / "source" / f"{document.document_id}.pdf"
            actual = sha256_hex(path.read_bytes()) if path.is_file() else None
            checks.append(
                {
                    "name": f"source:{document.document_id}",
                    "ok": actual == document.source_sha256,
                    "expected": document.source_sha256,
                    "actual": actual,
                }
            )
        live_bundle = canonical_digest(self._bundle_payload(state))
        checks.append(
            {
                "name": "evidence_bundle_digest",
                "ok": live_bundle == state["bundle_digest"],
                "expected": state["bundle_digest"],
                "actual": live_bundle,
            }
        )
        verification_digest = canonical_digest(state["verification"])
        checks.append(
            {
                "name": "verification_digest",
                "ok": True,
                "actual": verification_digest,
            }
        )
        for name in state.get("manifest_paths", []):
            path = self.runs_dir / run_id / name
            checks.append({"name": f"manifest:{name}", "ok": path.is_file()})
        subject_name = state.get("subject_filename")
        if subject_name:
            path = self.runs_dir / run_id / "subject" / subject_name
            checks.append({"name": "reviewed_subject_pdf", "ok": path.is_file()})
        ok = all(item["ok"] for item in checks)
        if ok and state["status"] == "approved":
            state["status"] = "verified"
            state["stage"] = "closed"
        if ok:
            self._activity(
                state,
                actor,
                "verify_package",
                "Verified source digests, evidence bundle digest, manifests, and reviewed subject PDF.",
                channel=channel,
                authorization_source=auth,
                tool_call_id=tool_call_id,
            )
            self._persist(state)
        return {
            "ok": ok,
            "status": state["status"],
            "packages": self.packages,
            "verification_elapsed_ms": state.get("verification_elapsed_ms"),
            "checks": checks,
        }

    def view(self, run_id: str) -> RunView:
        state = self._get(run_id)
        findings = state["findings"]
        passed = sum(item.status in {"pass", "corrected"} for item in findings)
        review = sum(item.status == "needs_review" for item in findings)
        confirmed = sum(item.status == "confirmed" for item in findings)
        product_name = state.get("product_name") or ""
        if not product_name or product_name == "Uploaded dossier":
            spec = next(
                (item for item in state["documents"] if item.document_id == "product-spec"),
                None,
            )
            if spec is not None:
                product_name = subject_display_name(spec.filename)
        return RunView(
            run_id=state["run_id"],
            dossier_id=state["dossier_id"],
            product_name=product_name,
            status=state["status"],
            packages=self.packages,
            documents=state["documents"],
            evidence=state["evidence"],
            findings=findings,
            corrections=state["corrections"],
            activities=state["activities"],
            bundle_digest=state["bundle_digest"],
            checkpoint_id=state["checkpoint"]["checkpoint_id"],
            approval_request_id=state["approval"]["approval_request_id"],
            decided_by=state.get("decided_by"),
            active_finding_id=state.get("active_finding_id"),
            viewer_document_id=state.get("viewer_document_id"),
            viewer_page=state.get("viewer_page"),
            draft_correction=state.get("draft_correction"),
            stage=state.get("stage", "documents"),
            subject_filename=state.get("subject_filename"),
            verification_elapsed_ms=state.get("verification_elapsed_ms"),
            updated_at=state.get("updated_at"),
            approval_requested=bool(state.get("approval_requested")),
            confirmation_requested=bool(state.get("confirmation_requested")),
            reviewed_pages=list(state.get("reviewed_pages") or []),
            summary={
                "passed": passed,
                "confirmed": confirmed,
                "unresolved": review,
                "review": review,
                "total": len(findings),
            },
            manifest_paths=state.get("manifest_paths", []),
        )

    def require_owner(self, run_id: str, session_id: str) -> None:
        state = self._get(run_id)
        if state.get("owner_session_id") != session_id:
            raise KeyError(run_id)

    def list_runs(self, owner_session_id: str | None = None) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        seen: set[str] = set()
        for run_id, state in self.runs.items():
            seen.add(run_id)
            if owner_session_id is not None and state.get("owner_session_id") != owner_session_id:
                continue
            rows.append(
                {
                    "run_id": run_id,
                    "dossier_id": state.get("dossier_id"),
                    "product_name": state.get("product_name"),
                    "status": state.get("status"),
                    "updated_at": state.get("updated_at"),
                    "stage": state.get("stage"),
                }
            )
        if self.runs_dir.is_dir():
            for path in self.runs_dir.glob("*/run_state.json"):
                run_id = path.parent.name
                if run_id in seen:
                    continue
                raw = json.loads(path.read_text(encoding="utf-8"))
                if owner_session_id is not None and raw.get("owner_session_id") != owner_session_id:
                    continue
                rows.append(
                    {
                        "run_id": run_id,
                        "dossier_id": raw.get("dossier_id"),
                        "product_name": raw.get("product_name"),
                        "status": raw.get("status"),
                        "updated_at": raw.get("updated_at"),
                        "stage": raw.get("stage"),
                    }
                )
        rows.sort(key=lambda item: item.get("updated_at") or "", reverse=True)
        return rows

    def source_file(self, run_id: str, document_id: DocumentId) -> tuple[Path, str]:
        state = self._get(run_id)
        document = next(
            (item for item in state["documents"] if item.document_id == document_id),
            None,
        )
        if document is None:
            raise ValueError(f"Unknown document: {document_id}")
        path = self._run_file(run_id, f"source/{document_id}.pdf")
        if not path.is_file():
            raise KeyError(run_id)
        return path, Path(document.filename).name

    def subject_file(self, run_id: str) -> tuple[Path, str]:
        state = self._get(run_id)
        if state["status"] not in {"approved", "verified", "exported"}:
            raise ValueError("The reviewed subject file is available after approval.")
        name = Path(state.get("subject_filename") or "subject-reviewed.pdf").name
        path = self._run_file(run_id, f"subject/{name}")
        if not path.is_file():
            raise KeyError(run_id)
        return path, name

    def _open_run(
        self,
        run_id: str,
        pack: dict[str, Any],
        actor: Actor,
        tool: str,
        *,
        channel: InvocationChannel = "backend",
        authorization_source: str | None = None,
        tool_call_id: str | None = None,
        owner_session_id: str | None = None,
    ) -> RunView:
        actor, channel, authorization_source, tool_call_id = self._bind_call(
            actor, channel, authorization_source, tool_call_id
        )
        documents = pack["documents"]
        evidence = pack["evidence"]
        document_payload = [
            item.model_dump(mode="json") for item in documents
        ]
        request = compile_pif_checks(
            evidence,
            document_payload,
            f"verify-{run_id}",
            extractor_id=pack.get("extractor_id", "reviewdesk.fixture"),
            extraction_method=pack.get("extraction_method", "host_supplied"),
        )
        started = time.perf_counter()
        verification = self.verifier.verify(request)
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        findings = findings_from_verification(
            verification, corrected_checks=set(), confirmed_checks=set()
        )
        bundle = {
            "documents": [
                {
                    "document_id": item.document_id,
                    "source_sha256": item.source_sha256,
                }
                for item in documents
            ],
            "evidence": [
                {
                    "evidence_id": item.evidence_id,
                    "document_id": item.document_id,
                    "field_name": item.field_name,
                    "normalized_value": item.normalized_value,
                }
                for item in evidence
            ],
        }
        plan, checkpoint, approval = self.approvals.open(
            run_id=run_id, evidence_bundle=bundle
        )
        errors = validate_execution_plan(plan)
        if errors:
            raise RuntimeError("invalid ReviewDesk execution plan: " + "; ".join(errors))
        spec = next(item for item in documents if item.document_id == "product-spec")
        state = {
            "run_id": run_id,
            "dossier_id": pack["dossier_id"],
            "product_name": pack["product_name"],
            "status": "reviewing",
            "stage": "documents",
            "documents": documents,
            "evidence": evidence,
            "verification": verification,
            "verification_elapsed_ms": elapsed_ms,
            "findings": findings,
            "corrections": [],
            "activities": [],
            "corrected_checks": set(),
            "confirmed_checks": set(),
            "plan": plan,
            "checkpoint": checkpoint,
            "approval": approval,
            "bundle_digest": canonical_digest(bundle),
            "decided_by": None,
            "active_finding_id": None,
            "viewer_document_id": spec.document_id,
            "viewer_page": 1,
            "draft_correction": None,
            "subject_filename": None,
            "reviewed_pages": [],
            "approval_requested": False,
            "confirmation_requested": False,
            "updated_at": _now(),
            "manifest_paths": [],
            "extractor_id": pack.get("extractor_id", "reviewdesk.fixture"),
            "extraction_method": pack.get("extraction_method", "host_supplied"),
            "owner_session_id": owner_session_id,
        }
        self.runs[run_id] = state
        source_bytes: dict[str, bytes] = pack.get("source_bytes") or {}
        for document in documents:
            payload = source_bytes.get(document.document_id)
            if payload is None:
                payload = original_pdf_bytes(document)
            if sha256_hex(payload) != document.source_sha256:
                raise RuntimeError(f"Source PDF digest mismatch for {document.document_id}")
            self._write_bytes(run_id, f"source/{document.document_id}.pdf", payload)
        self._write(run_id, "evidence_bundle_request.json", request)
        self._write(run_id, "verification_result.json", verification)
        self._write(run_id, "approval_request.json", approval)
        self._activity(
            state,
            actor,
            tool,
            (
                f"Opened {pack['product_name']}. Subject is the product specification; "
                f"formula and CoA are locked references. Role was set at ingest, not guessed later. "
                f"ProDocuX checks ran in {elapsed_ms} ms and stay hidden until run_checks."
            ),
            channel=channel,
            authorization_source=authorization_source,
            tool_call_id=tool_call_id,
        )
        self._persist(state)
        return self.view(run_id)

    def _refresh_status(self, state: dict[str, Any]) -> None:
        if state["status"] in {"approved", "verified", "rejected", "exported"}:
            return
        open_review = any(item.status == "needs_review" for item in state["findings"])
        if not open_review:
            state["status"] = "awaiting_human_approval"
        elif state.get("draft_correction") is not None:
            state["status"] = "correction_drafted"
        elif state.get("stage") == "documents":
            state["status"] = "reviewing"
        else:
            state["status"] = "findings_ready"

    def _verify(self, state: dict[str, Any], request_id: str) -> dict:
        document_payload = [item.model_dump(mode="json") for item in state["documents"]]
        request = compile_pif_checks(
            state["evidence"],
            document_payload,
            request_id,
            extractor_id=state.get("extractor_id", "reviewdesk.fixture"),
            extraction_method=state.get("extraction_method", "host_supplied"),
        )
        verification = self.verifier.verify(request)
        self._write(state["run_id"], "evidence_bundle_request.json", request)
        self._write(state["run_id"], "verification_result.json", verification)
        return verification

    def _bundle_payload(self, state: dict[str, Any]) -> dict:
        return {
            "documents": [
                {
                    "document_id": item.document_id,
                    "source_sha256": item.source_sha256,
                }
                for item in state["documents"]
            ],
            "evidence": [
                {
                    "evidence_id": item.evidence_id,
                    "document_id": item.document_id,
                    "field_name": item.field_name,
                    "normalized_value": item.normalized_value,
                }
                for item in state["evidence"]
            ],
        }

    def _bind_call(
        self,
        actor: Actor,
        channel: InvocationChannel = "backend",
        authorization_source: str | None = None,
        tool_call_id: str | None = None,
    ) -> tuple[Actor, InvocationChannel, str, str | None]:
        if channel == "webmcp":
            actor = "agent"
        elif channel == "ui":
            actor = "human"
        auth = authorization_source or (
            "webmcp.tool" if channel == "webmcp" else "reviewdesk.ui" if channel == "ui" else "backend"
        )
        return actor, channel, auth, tool_call_id

    def _activity(
        self,
        state: dict[str, Any],
        actor: Actor,
        tool: str,
        message: str,
        *,
        channel: InvocationChannel = "backend",
        authorization_source: str | None = None,
        tool_call_id: str | None = None,
        actor_type: str | None = None,
    ) -> None:
        auth = authorization_source or (
            "webmcp.tool" if channel == "webmcp" else "reviewdesk.ui" if channel == "ui" else "backend"
        )
        now = _now()
        state["updated_at"] = now
        state["activities"] = [
            ActivityEvent(
                event_id=f"act_{uuid.uuid4().hex[:12]}",
                at=now,
                actor=actor,
                actor_type=actor_type or actor,
                actor_id=_actor_id(actor),
                invocation_channel=channel,
                authorization_source=auth,
                tool_call_id=tool_call_id,
                tool=tool,
                message=message,
                viewer_document_id=state.get("viewer_document_id"),
                viewer_page=state.get("viewer_page"),
            ),
            *state["activities"],
        ]

    def _get(self, run_id: str) -> dict[str, Any]:
        run_id = require_run_id(run_id)
        if run_id in self.runs:
            return self.runs[run_id]
        path = self._run_file(run_id, "run_state.json")
        if not path.is_file():
            raise KeyError(run_id)
        raw = json.loads(path.read_text(encoding="utf-8"))
        from reviewdesk_domain.models import DocumentPage, DossierDocument, Finding

        raw["documents"] = [DossierDocument.model_validate(item) for item in raw["documents"]]
        raw["evidence"] = [EvidenceField.model_validate(item) for item in raw["evidence"]]
        raw["findings"] = [Finding.model_validate(item) for item in raw["findings"]]
        raw["corrections"] = [Correction.model_validate(item) for item in raw.get("corrections", [])]
        raw["activities"] = [ActivityEvent.model_validate(item) for item in raw.get("activities", [])]
        raw["reviewed_pages"] = [
            DocumentPage.model_validate(item) if isinstance(item, dict) else item
            for item in raw.get("reviewed_pages") or []
        ]
        raw["draft_correction"] = (
            DraftCorrection.model_validate(raw["draft_correction"])
            if raw.get("draft_correction")
            else None
        )
        raw["corrected_checks"] = set(raw.get("corrected_checks", []))
        raw["confirmed_checks"] = set(raw.get("confirmed_checks", []))
        raw.setdefault("stage", "documents")
        raw.setdefault("subject_filename", None)
        raw.setdefault("verification_elapsed_ms", None)
        raw.setdefault("extractor_id", "reviewdesk.fixture")
        raw.setdefault("extraction_method", "host_supplied")
        raw.setdefault("owner_session_id", None)
        raw.setdefault("approval_requested", False)
        raw.setdefault("confirmation_requested", False)
        raw.setdefault("updated_at", None)
        if raw.get("status") == "awaiting_approval":
            raw["status"] = "reviewing"
        if raw.get("status") == "completed_with_review":
            raw["status"] = "approved"
        self.runs[run_id] = raw
        return raw

    def _persist(self, state: dict[str, Any]) -> None:
        serializable = {
            **state,
            "documents": [item.model_dump(mode="json") for item in state["documents"]],
            "evidence": [item.model_dump(mode="json") for item in state["evidence"]],
            "findings": [item.model_dump(mode="json") for item in state["findings"]],
            "corrections": [item.model_dump(mode="json") for item in state["corrections"]],
            "activities": [item.model_dump(mode="json") for item in state["activities"]],
            "draft_correction": None
            if state.get("draft_correction") is None
            else state["draft_correction"].model_dump(mode="json"),
            "corrected_checks": sorted(state["corrected_checks"]),
            "confirmed_checks": sorted(state["confirmed_checks"]),
            "reviewed_pages": [
                item.model_dump(mode="json") if hasattr(item, "model_dump") else item
                for item in state.get("reviewed_pages") or []
            ],
            "updated_at": state.get("updated_at") or _now(),
        }
        self._write(state["run_id"], "run_state.json", serializable)

    def _run_dir(self, run_id: str) -> Path:
        run_id = require_run_id(run_id)
        root = self.runs_dir.resolve()
        target = (root / run_id).resolve()
        if not target.is_relative_to(root):
            raise KeyError(run_id)
        return target

    def _run_file(self, run_id: str, name: str) -> Path:
        root = self._run_dir(run_id)
        relative = require_relative_artifact(name)
        target = (root / relative).resolve()
        if not target.is_relative_to(root):
            raise ValueError("invalid artifact path")
        return target

    def _write(self, run_id: str, name: str, value: object) -> None:
        target = self._run_file(run_id, name)
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_name(f"{target.name}.tmp")
        tmp.write_text(
            json.dumps(value, indent=2, ensure_ascii=False, default=str),
            encoding="utf-8",
        )
        os.replace(tmp, target)

    def _write_bytes(self, run_id: str, name: str, payload: bytes) -> None:
        target = self._run_file(run_id, name)
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_name(f"{target.name}.tmp")
        tmp.write_bytes(payload)
        os.replace(tmp, target)


def _exclusive_run(fn: Callable[..., Any]) -> Callable[..., Any]:
    @functools.wraps(fn)
    def wrapper(self: ReviewDeskService, run_id: str, *args: Any, **kwargs: Any) -> Any:
        with self._lock_for(run_id):
            return fn(self, run_id, *args, **kwargs)

    return wrapper


for _name in (
    "assign_finding",
    "request_human_confirmation",
    "request_human_approval",
    "reveal_findings",
    "select_finding",
    "open_document",
    "propose_correction",
    "rewrite_locked_reference",
    "reject_draft",
    "commit_correction",
    "confirm_observed_fact",
    "decide",
    "audit_package",
    "verify_package",
    "view",
    "require_owner",
    "source_file",
    "subject_file",
):
    setattr(ReviewDeskService, _name, _exclusive_run(getattr(ReviewDeskService, _name)))
