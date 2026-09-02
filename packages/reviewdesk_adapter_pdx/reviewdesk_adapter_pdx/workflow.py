from __future__ import annotations

import uuid
from datetime import UTC, datetime

from pdx_artifact_core import (
    ApprovalLedger,
    build_resumed_plan,
    cancel_checkpoint,
    canonical_digest,
    create_approval_request,
    create_checkpoint,
)


class ApprovalWorkflow:
    def __init__(self) -> None:
        self.ledger = ApprovalLedger()

    def open(self, *, run_id: str, evidence_bundle: dict) -> tuple[dict, dict, dict]:
        plan = {
            "schema_version": "pdx_execution_plan_v1",
            "request_id": run_id,
            "producer": {"type": "reviewdesk.policy", "name": "Harbor Calm Serum demo"},
            "intent": {
                "artifact_type": "audit_package",
                "summary": "ReviewDesk dossier review",
            },
            "steps": [
                {
                    "id": "load",
                    "kind": "tool",
                    "tool": "reviewdesk.load_fixture",
                    "inputs": {},
                },
                {
                    "id": "verify",
                    "kind": "verify",
                    "verification": [
                        {
                            "id": "evidence-bundle",
                            "check": "prodocux.evidence_bundle",
                            "fail_action": "ask_human",
                        }
                    ],
                    "depends_on": ["load"],
                },
                {
                    "id": "approval",
                    "kind": "approval",
                    "depends_on": ["verify"],
                    "policies": {"approval_required": True},
                },
                {
                    "id": "report",
                    "kind": "transform",
                    "transform": "reviewdesk.report",
                    "depends_on": ["approval"],
                },
            ],
            "policies": {"default_approval_required": False},
        }
        digest = canonical_digest(evidence_bundle)
        checkpoint = create_checkpoint(
            plan=plan,
            run_id=run_id,
            subject_digest=digest,
            completed_step_ids=["load", "verify"],
            pending_step_ids=["approval", "report"],
            evidence_digests={"bundle": digest},
        )
        request = create_approval_request(
            checkpoint, summary="Review deterministic dossier findings"
        )
        return plan, checkpoint, request

    def decide(
        self,
        *,
        plan: dict,
        checkpoint: dict,
        request: dict,
        actor_id: str,
        decision: str,
    ) -> tuple[dict, dict | None]:
        record = {
            "decision_id": str(uuid.uuid4()),
            "approval_request_id": request["approval_request_id"],
            "checkpoint_id": checkpoint["checkpoint_id"],
            "idempotency_key": f"{checkpoint['checkpoint_id']}:{actor_id}:{decision}",
            "actor_id": actor_id,
            "decision": decision,
            "subject_digest": checkpoint["subject_digest"],
            "plan_digest": checkpoint["plan_digest"],
            "evidence_digests": checkpoint["evidence_digests"],
            "decided_at": datetime.now(UTC).isoformat(),
        }
        saved = self.ledger.record(checkpoint, request, record)
        resumed = (
            build_resumed_plan(plan, checkpoint, saved) if decision == "approved" else None
        )
        return saved, resumed

    def replace_after_correction(
        self, *, run_id: str, old_checkpoint: dict, evidence_bundle: dict
    ) -> tuple[dict, dict, dict, dict]:
        cancelled = cancel_checkpoint(old_checkpoint)
        plan, checkpoint, request = self.open(run_id=run_id, evidence_bundle=evidence_bundle)
        return cancelled, plan, checkpoint, request
