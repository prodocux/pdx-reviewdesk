import type {
  Actor,
  BenchmarkResult,
  DocumentId,
  DossierInfo,
  Finding,
  InvocationChannel,
  Run,
  ToolSpec,
  VerifyResult,
  WorkspaceSnapshot,
} from "./types";
import { ensureSession, invocationHeaders } from "./session";

const API = (import.meta.env.VITE_API_URL as string | undefined) ?? "";

export const UPLOAD_EXTRACT_HELP =
  "This PDF could not extract the required fields. ProDocuX reads selectable PDF text, including ordinary compressed streams. ReviewDesk then looks for labels such as Product, Formula revision, Acceptable pH, and pH result. Scanned or image-only PDFs need OCR, which this demo does not enable.";

function isInternalDetail(text: string): boolean {
  return /pydantic|validation error|field required|input_value|model_type/i.test(text);
}

function detailMessage(body: unknown, fallback: string, upload = false): string {
  const detail = (body as { detail?: unknown } | undefined)?.detail;
  if (typeof detail === "string") {
    if (isInternalDetail(detail)) return upload ? UPLOAD_EXTRACT_HELP : fallback;
    return detail;
  }
  if (Array.isArray(detail)) {
    return upload ? UPLOAD_EXTRACT_HELP : fallback;
  }
  return fallback;
}

export const STALE_TOOL_MESSAGE =
  "Workspace changed; refresh available tools and retry";

const GENERIC_CORRECTION_SCHEMA = {
  type: "object",
  properties: {
    finding_id: { type: "string", description: "Finding id such as find-revision or find-ph" },
    field: { type: "string", description: "Subject field name, for example formula_revision" },
    current_value: { type: "string" },
    proposed_value: { type: "string" },
    reason: { type: "string", minLength: 3 },
    evidence_refs: { type: "array", items: { type: "string" } },
    document_id: { type: "string", enum: ["product-spec", "formula", "coa"] },
  },
  required: ["finding_id", "proposed_value", "reason"],
  additionalProperties: false,
};

function callBody(actor: Actor, channel: InvocationChannel, extra: Record<string, unknown> = {}): string {
  const extraAuth = extra.authorization_source;
  const extraTool = extra.tool_call_id;
  const toolCallId =
    typeof extraTool === "string"
      ? extraTool
      : typeof crypto !== "undefined" && "randomUUID" in crypto
        ? crypto.randomUUID()
        : undefined;
  return JSON.stringify({
    ...extra,
    actor,
    channel,
    authorization_source:
      typeof extraAuth === "string"
        ? extraAuth
        : channel === "webmcp"
          ? "webmcp.tool"
          : channel === "ui"
            ? "reviewdesk.ui"
            : "backend",
    tool_call_id: toolCallId,
  });
}

async function request(path: string, init?: RequestInit, channel: InvocationChannel = "ui"): Promise<Run> {
  await ensureSession();
  const response = await fetch(`${API}${path}`, {
    ...init,
    credentials: "include",
    headers: {
      "Content-Type": "application/json",
      ...invocationHeaders(channel),
      ...(init?.headers ?? {}),
    },
  });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(detailMessage(body, "The request could not be completed."));
  }
  return body as Run;
}

export function startDemo(actor: Actor, dossierId?: string, channel: InvocationChannel = "ui"): Promise<Run> {
  return request("/v1/demo-runs", {
    method: "POST",
    body: callBody(actor, channel, { dossier_id: dossierId ?? null }),
  }, channel);
}

export async function startFromUploads(
  _actor: Actor,
  files: { subject: File; formula: File; coa: File },
): Promise<Run> {
  const body = new FormData();
  body.append("subject", files.subject);
  body.append("formula", files.formula);
  body.append("coa", files.coa);
  await ensureSession();
  const response = await fetch(`${API}/v1/upload-runs`, {
    method: "POST",
    body,
    credentials: "include",
    headers: invocationHeaders("ui"),
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(detailMessage(payload, UPLOAD_EXTRACT_HELP, true));
  }
  return payload as Run;
}

export async function listDossiers(): Promise<DossierInfo[]> {
  await ensureSession();
  const response = await fetch(`${API}/v1/dossiers`, { credentials: "include" });
  const body = (await response.json()) as { dossiers?: DossierInfo[] };
  return body.dossiers ?? [];
}

export function getRun(runId: string): Promise<Run> {
  return request(`/v1/runs/${runId}`);
}

export function revealFindings(runId: string, actor: Actor, channel: InvocationChannel = "ui"): Promise<Run> {
  return request(`/v1/runs/${runId}/checks`, {
    method: "POST",
    body: callBody(actor, channel),
  }, channel);
}

export function selectFinding(
  runId: string,
  findingId: string,
  actor: Actor,
  channel: InvocationChannel = "ui",
): Promise<Run> {
  return request(`/v1/runs/${runId}/select-finding`, {
    method: "POST",
    body: callBody(actor, channel, { finding_id: findingId }),
  }, channel);
}

export function assignFinding(
  runId: string,
  findingId: string,
  assignee: Actor,
  actor: Actor,
  channel: InvocationChannel = "ui",
): Promise<Run> {
  return request(`/v1/runs/${runId}/assign-finding`, {
    method: "POST",
    body: callBody(actor, channel, { finding_id: findingId, assignee }),
  }, channel);
}

export async function runBenchmark(): Promise<BenchmarkResult> {
  await ensureSession();
  const response = await fetch(`${API}/v1/benchmark`, {
    method: "POST",
    credentials: "include",
    headers: invocationHeaders("ui"),
  });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error("Benchmark could not be completed.");
  }
  return body as BenchmarkResult;
}

export function openSourceDocument(
  runId: string,
  documentId: DocumentId,
  page: number | undefined,
  actor: Actor,
  channel: InvocationChannel = "ui",
): Promise<Run> {
  return request(`/v1/runs/${runId}/open-document`, {
    method: "POST",
    body: callBody(actor, channel, { document_id: documentId, page }),
  }, channel);
}

export function proposeCorrection(
  runId: string,
  input: {
    proposed_value: string;
    reason: string;
    finding_id?: string;
    field?: string;
    document_id?: DocumentId;
    current_value?: string;
  },
  actor: Actor,
  channel: InvocationChannel = "ui",
): Promise<Run> {
  return request(`/v1/runs/${runId}/propose-correction`, {
    method: "POST",
    body: callBody(actor, channel, input),
  }, channel);
}

export function commitCorrection(
  runId: string,
  actor: Actor,
  channel: InvocationChannel = "ui",
): Promise<Run> {
  return request(`/v1/runs/${runId}/corrections`, {
    method: "POST",
    body: callBody(actor, channel),
  }, channel);
}

export function confirmObservedFact(
  runId: string,
  actor: Actor,
  channel: InvocationChannel = "ui",
): Promise<Run> {
  return request(`/v1/runs/${runId}/confirm`, {
    method: "POST",
    body: callBody(actor, channel),
  }, channel);
}

export function requestHumanConfirmation(
  runId: string,
  actor: Actor,
  channel: InvocationChannel = "ui",
): Promise<Run> {
  return request(`/v1/runs/${runId}/request-human-confirmation`, {
    method: "POST",
    body: callBody(actor, channel),
  }, channel);
}

export function requestHumanApproval(
  runId: string,
  actor: Actor,
  channel: InvocationChannel = "ui",
): Promise<Run> {
  return request(`/v1/runs/${runId}/request-human-approval`, {
    method: "POST",
    body: callBody(actor, channel),
  }, channel);
}

export function rejectDraft(
  runId: string,
  reason: string,
  actor: Actor,
  channel: InvocationChannel = "ui",
): Promise<Run> {
  return request(`/v1/runs/${runId}/reject-draft`, {
    method: "POST",
    body: callBody(actor, channel, { reason }),
  }, channel);
}

export async function rewriteLockedReference(
  runId: string,
  documentId: DocumentId,
  actor: Actor,
  channel: InvocationChannel = "ui",
): Promise<Run> {
  try {
    return await request(`/v1/runs/${runId}/rewrite-locked-reference`, {
      method: "POST",
      body: callBody(actor, channel, { document_id: documentId }),
    }, channel);
  } catch (reason) {
    const run = await getRun(runId).catch(() => null);
    const error = reason instanceof Error ? reason : new Error("Policy gate blocked the rewrite.");
    (error as Error & { run?: Run }).run = run ?? undefined;
    throw error;
  }
}

export function recordApproval(
  runId: string,
  actor: Actor,
  channel: InvocationChannel = "ui",
): Promise<Run> {
  return request(`/v1/runs/${runId}/decision`, {
    method: "POST",
    body: callBody(actor, channel, { decision: "approved" }),
  }, channel);
}

export async function exportAuditPackage(
  runId: string,
  actor: Actor = "human",
  channel: InvocationChannel = "ui",
): Promise<Record<string, unknown>> {
  await ensureSession();
  const response = await fetch(`${API}/v1/runs/${runId}/audit-package`, {
    method: "POST",
    credentials: "include",
    headers: {
      "Content-Type": "application/json",
      ...invocationHeaders(channel),
    },
    body: callBody(actor, channel),
  });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = (body as { detail?: string }).detail;
    throw new Error(typeof detail === "string" ? detail : "Export is not available.");
  }
  return body as Record<string, unknown>;
}

export async function verifyPackage(
  runId: string,
  actor: Actor = "human",
  channel: InvocationChannel = "ui",
): Promise<VerifyResult> {
  await ensureSession();
  const response = await fetch(`${API}/v1/runs/${runId}/verify-package`, {
    method: "POST",
    credentials: "include",
    headers: {
      "Content-Type": "application/json",
      ...invocationHeaders(channel),
    },
    body: callBody(actor, channel),
  });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = (body as { detail?: string }).detail;
    throw new Error(typeof detail === "string" ? detail : "Verify is not available.");
  }
  return body as VerifyResult;
}

export function sourceFileUrl(runId: string, documentId: DocumentId): string {
  return `${API}/v1/runs/${runId}/documents/${documentId}/file`;
}

export function subjectFileUrl(runId: string): string {
  return `${API}/v1/runs/${runId}/subject-file`;
}

export function summarize(run: Run): {
  passed: number;
  confirmed: number;
  unresolved: number;
  review: number;
  total: number;
} {
  return {
    passed: run.summary.passed,
    confirmed: run.summary.confirmed ?? 0,
    unresolved: run.summary.unresolved ?? run.summary.review,
    review: run.summary.unresolved ?? run.summary.review,
    total: run.summary.total,
  };
}

export function isClosed(run: Run | null): boolean {
  return (
    run?.status === "approved" ||
    run?.status === "verified" ||
    run?.status === "exported" ||
    run?.status === "rejected"
  );
}

function activeFinding(run: Run | null): Finding | undefined {
  if (!run) return undefined;
  return run.findings.find((item) => item.finding_id === run.active_finding_id);
}

function proposeTool(run: Run | null, atCorrections: boolean): ToolSpec {
  const finding = activeFinding(run);
  if (finding?.action === "confirm_ref_observation") {
    return {
      name: "propose_correction",
      description:
        `Blocked for ${finding.finding_id} (${finding.check_id}). This is a locked reference observation ` +
        `(actual=${String(finding.actual)} on ${finding.observed_document}). ` +
        (finding.assignee === "human"
          ? "Do not rewrite the reference. Call request_human_confirmation. "
          : "Do not rewrite the reference. Call confirm_observed_fact, or rewrite_locked_reference to see the policy refusal. ") +
        `Currently assigned to the ${finding.assignee ?? "human"}.`,
      inputSchema: GENERIC_CORRECTION_SCHEMA,
      enabled: atCorrections,
    };
  }
  if (finding?.action === "correct_subject_field" && finding.status === "needs_review") {
    const owner = finding.assignee ?? "agent";
    return {
      name: "propose_correction",
      description:
        owner === "human"
          ? `Blocked: ${finding.finding_id} is assigned to the human. The agent cannot take this finding. Wait, or the human must reassign it in the UI.`
          : `Propose a subject-field correction for ${finding.finding_id}. ` +
            `Field formula_revision is currently ${String(finding.actual)}; authority expects ${String(finding.expected)}. ` +
            "Never overwrites the locked source PDF. Assigned to the agent.",
      inputSchema: GENERIC_CORRECTION_SCHEMA,
      enabled: atCorrections,
    };
  }
  return {
    name: "propose_correction",
    description:
      "Propose a subject-field correction. Requires finding_id, proposed_value, and reason. Reference documents are locked.",
    inputSchema: GENERIC_CORRECTION_SCHEMA,
    enabled: false,
  };
}

export function availableTools(run: Run | null): ToolSpec[] {
  const stage = run?.stage ?? "documents";
  const finding = activeFinding(run);
  const reviewOpen = run?.findings.some((item) => item.status === "needs_review") ?? false;
  const revisionOpen =
    run?.findings.find((item) => item.check_id === "formula-version")?.status === "needs_review";
  const phOpen =
    run?.findings.find((item) => item.check_id === "ph-range")?.status === "needs_review";
  const complete = isClosed(run);
  const atDocuments = Boolean(run) && stage === "documents";
  const atFindings = Boolean(run) && stage === "findings";
  const atCorrections = Boolean(run) && stage === "corrections";
  const canApprove = Boolean(run) && !reviewOpen && !complete && run?.status === "awaiting_human_approval";
  return [
    {
      name: "get_workspace_state",
      description:
        "Return the current ReviewDesk state: status machine, stage, findings, open document, checkpoint digest, and which tools are available right now.",
      inputSchema: { type: "object", properties: {}, additionalProperties: false },
      enabled: true,
      stable: true,
    },
    {
      name: "start_demo_audit",
      description: complete
        ? "The current audit is closed. Call this to start a NEW Harbor Calm Serum run. Do not reload the page; a refresh of this URL restores the same closed run. The previous run is unchanged. If the human will drop PDFs instead, call new_review first."
        : "Open a canned dossier. Default is Harbor Calm Serum. Custom PDFs must be dropped by the human into the three slots. ProDocuX extracts selectable text; the files still need Product, Formula revision, Acceptable pH, and pH result labels. WebMCP cannot send binary files.",
      inputSchema: {
        type: "object",
        properties: {
          dossier_id: {
            type: "string",
            enum: ["harbor-calm-serum-2026", "cedar-night-cream-2026"],
          },
        },
        additionalProperties: false,
      },
      enabled: true,
      stable: true,
    },
    {
      name: "new_review",
      description: complete
        ? "This audit is closed. Call this instead of reloading. Reloading /runs/{id} restores the same closed run. Returns to the empty desk so the human can drop three PDFs, or so start_demo_audit can open a fresh Harbor run. The previous run stays at its URL."
        : run
          ? "Leave the current run and return to the empty desk. The previous run stays at its URL. Prefer this after Audit closed."
          : "Already on the empty desk. The human can drop three PDFs, or call start_demo_audit.",
      inputSchema: { type: "object", properties: {}, additionalProperties: false },
      enabled: Boolean(run),
      stable: true,
    },
    {
      name: "run_benchmark",
      description:
        "Run 10 dossiers (20 planted discrepancies) through the live ProDocuX checks. Returns hit rate, misses, and false positives. Does not change the open review.",
      inputSchema: { type: "object", properties: {}, additionalProperties: false },
      enabled: true,
      stable: true,
    },
    {
      name: "run_checks",
      description:
        "Reveal ProDocuX findings for this dossier. Stay on Documents until this tool or the human Run checks action is used.",
      inputSchema: { type: "object", properties: {}, additionalProperties: false },
      enabled: atDocuments,
    },
    {
      name: "select_finding",
      description:
        "Focus a finding and open the evidence page. Selecting a needs-review item moves the shared desk into Corrections.",
      inputSchema: {
        type: "object",
        properties: {
          finding_id: { type: "string", description: "Finding id such as find-revision or find-ph" },
        },
        required: ["finding_id"],
        additionalProperties: false,
      },
      enabled: (atFindings || atCorrections) && !complete,
    },
    {
      name: "assign_finding",
      description:
        "Hand a finding to the human. The agent cannot take a human-assigned finding; that reassignment is UI-only.",
      inputSchema: {
        type: "object",
        properties: {
          finding_id: { type: "string" },
          assignee: { type: "string", enum: ["human"] },
        },
        required: ["finding_id", "assignee"],
        additionalProperties: false,
      },
      enabled: (atFindings || atCorrections) && !complete,
    },
    {
      name: "open_source_document",
      description:
        "Open the exact source document and page. Use product-spec for the subject, formula or coa for locked references.",
      inputSchema: {
        type: "object",
        properties: {
          document_id: { type: "string", enum: ["product-spec", "formula", "coa"] },
          page: { type: "integer", minimum: 1, maximum: 4 },
        },
        required: ["document_id"],
        additionalProperties: false,
      },
      enabled: Boolean(run),
      stable: true,
    },
    proposeTool(run, atCorrections),
    {
      name: "commit_correction",
      description:
        "Human or agent commits the subject-field draft. ProDocuX re-verifies; PDX cancels and replaces the checkpoint.",
      inputSchema: { type: "object", properties: {}, additionalProperties: false },
      enabled: atCorrections && Boolean(revisionOpen) && Boolean(run?.draft_correction),
    },
    {
      name: "reject_draft",
      description:
        "Human rejects the current correction draft and records a reason. The agent proposal stays in the audit log.",
      inputSchema: {
        type: "object",
        properties: { reason: { type: "string", minLength: 3 } },
        required: ["reason"],
        additionalProperties: false,
      },
      enabled: atCorrections && Boolean(run?.draft_correction),
    },
    {
      name: "confirm_observed_fact",
      description:
        `Confirm ${finding?.finding_id ?? "find-ph"}: CoA pH ${String(finding?.actual ?? "")} stays as an observed batch fact. Do not rewrite the certificate.`,
      inputSchema: { type: "object", properties: {}, additionalProperties: false },
      enabled:
        atCorrections &&
        Boolean(phOpen) &&
        !revisionOpen &&
        run?.findings.find((item) => item.check_id === "ph-range")?.assignee === "agent",
    },
    {
      name: "request_human_confirmation",
      description:
        `Ask the human to confirm ${finding?.finding_id ?? "find-ph"}: CoA pH ${String(
          run?.findings.find((item) => item.check_id === "ph-range")?.actual ?? "",
        )} is an observed batch fact. The agent cannot confirm a human-assigned finding.`,
      inputSchema: { type: "object", properties: {}, additionalProperties: false },
      enabled:
        atCorrections &&
        Boolean(phOpen) &&
        !revisionOpen &&
        run?.findings.find((item) => item.check_id === "ph-range")?.assignee === "human",
    },
    {
      name: "rewrite_locked_reference",
      description:
        "Attempt to overwrite a locked reference (formula or CoA). ReviewDesk policy will refuse. Use this to demonstrate the safety fail.",
      inputSchema: {
        type: "object",
        properties: {
          document_id: { type: "string", enum: ["formula", "coa"] },
        },
        required: ["document_id"],
        additionalProperties: false,
      },
      enabled: Boolean(run) && !complete,
    },
    {
      name: "request_human_approval",
      description:
        "Ask the human to approve the current digest-bound PDX checkpoint. The WebMCP tool surface cannot invoke human-only approval.",
      inputSchema: { type: "object", properties: {}, additionalProperties: false },
      enabled: canApprove,
    },
    {
      name: "verify_package",
      description:
        "Recompute source digests and the evidence bundle digest. Proves the export has not been tampered with. Does not mark the run exported.",
      inputSchema: { type: "object", properties: {}, additionalProperties: false },
      enabled: run?.status === "approved" || run?.status === "verified" || run?.status === "exported",
    },
    {
      name: "export_audit_package",
      description:
        "Download a checksummed audit JSON package. Source PDF bytes are not included; use the original and subject file links instead.",
      inputSchema: { type: "object", properties: {}, additionalProperties: false },
      enabled: run?.status === "approved" || run?.status === "verified" || run?.status === "exported",
    },
  ];
}

export function snapshot(run: Run | null, webmcp: boolean, previousTools?: string[]): WorkspaceSnapshot {
  const tools = availableTools(run)
    .filter((tool) => tool.enabled)
    .map((tool) => tool.name);
  const changed = previousTools !== undefined && previousTools.join("|") !== tools.join("|");
  const finding = activeFinding(run);
  if (!run) {
    return {
      webmcp,
      status: "idle",
      available_tools: tools,
      tools_changed: changed,
      refresh_hint: changed ? STALE_TOOL_MESSAGE : undefined,
      next_action: "Call start_demo_audit, or wait for the human to drop three PDFs.",
    };
  }
  const complete = isClosed(run);
  return {
    webmcp,
    status: run.status,
    product_name: run.product_name,
    run_id: run.run_id,
    bundle_digest: run.bundle_digest,
    checkpoint_id: run.checkpoint_id,
    approval_request_id: run.approval_request_id,
    active_finding_id: run.active_finding_id,
    packages: run.packages,
    viewer:
      run.viewer_document_id && run.viewer_page
        ? {
            document_id: run.viewer_document_id,
            page: run.viewer_page,
            why: finding ? `${finding.finding_id}: ${finding.title}` : "Subject orientation",
          }
        : null,
    summary: run.summary,
    stage: run.stage,
    available_tools: tools,
    tools_changed: changed,
    refresh_hint: changed ? STALE_TOOL_MESSAGE : undefined,
    next_action: complete
      ? "Audit closed. Do not reload this URL; it restores the same closed run. Call new_review for an empty desk, or start_demo_audit for a new Harbor run."
      : undefined,
    findings:
      run.stage === "documents"
        ? undefined
        : run.findings.map((item) => ({
            finding_id: item.finding_id,
            check_id: item.check_id,
            status: item.status,
            title: item.title,
            action: item.action,
            assignee: item.assignee,
          })),
  };
}
