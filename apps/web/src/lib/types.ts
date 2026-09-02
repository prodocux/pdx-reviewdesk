export type Scalar = string | number | boolean | null;
export type Actor = "human" | "agent";
export type ActorType = "human" | "agent" | "system";
export type InvocationChannel = "ui" | "webmcp" | "backend";
export type FindingStatus =
  | "pass"
  | "needs_review"
  | "confirmed"
  | "corrected"
  | "rejected";
export type RunStatus =
  | "idle"
  | "reviewing"
  | "findings_ready"
  | "correction_drafted"
  | "awaiting_human_approval"
  | "approved"
  | "verified"
  | "rejected"
  | "exported";

export type UiStage = "documents" | "findings" | "corrections" | "closed";
export type FindingAction =
  | "correct_subject_field"
  | "confirm_ref_observation"
  | "informational";
export type DocumentId = "product-spec" | "formula" | "coa";

export interface SourceLocator {
  page: number;
  snippet: string;
}

export interface DocumentPage {
  page: number;
  title: string;
  lines: string[];
  highlight?: string;
}

export interface DossierDocument {
  document_id: DocumentId;
  filename: string;
  document_type:
    | "product_specification"
    | "ingredient_formula"
    | "certificate_of_analysis";
  source_sha256: string;
  role: "subject" | "ref";
  pages: DocumentPage[];
}

export interface EvidenceField {
  evidence_id: string;
  document_id: DocumentId;
  field_name: string;
  normalized_value: Scalar;
  confidence: number;
  source: SourceLocator;
}

export interface Finding {
  finding_id: string;
  check_id: string;
  severity: "medium" | "high" | "critical";
  status: FindingStatus;
  title: string;
  message: string;
  evidence_refs: string[];
  expected: Scalar;
  actual: Scalar;
  authority_document: DocumentId;
  observed_document: DocumentId;
  authority_rule: string;
  action: FindingAction;
  assignee?: Actor;
}

export interface Correction {
  correction_id: string;
  finding_id: string;
  document_id: DocumentId;
  original_value: Scalar;
  corrected_value: Scalar;
  reason: string;
  actor: Actor;
  prior_bundle_digest: string;
  new_bundle_digest: string;
}

export interface ActivityEvent {
  event_id: string;
  at: string;
  actor: Actor;
  actor_type?: ActorType;
  actor_id?: string;
  invocation_channel?: InvocationChannel;
  authorization_source?: string;
  tool_call_id?: string | null;
  tool?: string;
  message: string;
  viewer_document_id?: DocumentId | null;
  viewer_page?: number | null;
}

export interface DraftCorrection {
  value: string;
  reason: string;
  finding_id?: string | null;
  document_id?: DocumentId | null;
  field?: string | null;
  current_value?: Scalar;
}

export interface Run {
  run_id: string;
  dossier_id: string;
  product_name: string;
  status: RunStatus;
  documents: DossierDocument[];
  evidence: EvidenceField[];
  findings: Finding[];
  corrections: Correction[];
  activities: ActivityEvent[];
  bundle_digest: string;
  checkpoint_id: string | null;
  approval_request_id: string | null;
  decided_by: Actor | null;
  packages: Record<string, string>;
  active_finding_id: string | null;
  viewer_document_id: DocumentId | null;
  viewer_page: number | null;
  draft_correction: DraftCorrection | null;
  stage: UiStage;
  subject_filename: string | null;
  verification_elapsed_ms?: number | null;
  updated_at?: string | null;
  approval_requested?: boolean;
  confirmation_requested?: boolean;
  reviewed_pages?: DocumentPage[];
  summary: { passed: number; confirmed?: number; unresolved?: number; review: number; total: number };
  manifest_paths?: string[];
}

export interface DossierInfo {
  dossier_id: string;
  product_name: string;
  judge_mode: boolean;
  blurb: string;
  planted: string[];
}

export interface WorkspaceSnapshot {
  webmcp: boolean;
  status: RunStatus | "idle";
  product_name?: string;
  run_id?: string;
  bundle_digest?: string;
  checkpoint_id?: string | null;
  approval_request_id?: string | null;
  active_finding_id?: string | null;
  packages?: Record<string, string>;
  viewer?: { document_id: DocumentId; page: number; why?: string } | null;
  summary?: { passed: number; review: number; total: number };
  stage?: UiStage;
  tools_changed?: boolean;
  refresh_hint?: string;
  available_tools: string[];
  findings?: Array<{
    finding_id: string;
    check_id: string;
    status: FindingStatus;
    title: string;
    action?: FindingAction;
    assignee?: Actor;
  }>;
}

export interface ToolSpec {
  name: string;
  description: string;
  inputSchema: Record<string, unknown>;
  enabled: boolean;
  stable?: boolean;
}

export interface VerifyResult {
  ok: boolean;
  status: RunStatus;
  packages: Record<string, string>;
  verification_elapsed_ms?: number | null;
  checks: Array<{ name: string; ok: boolean; expected?: string; actual?: string | null }>;
}

export interface BenchmarkRow {
  dossier_id: string;
  product_name: string;
  planted: string[];
  flagged: string[];
  hits: string[];
  misses: string[];
  false_positives: string[];
  elapsed_ms: number;
  ok: boolean;
}

export interface BenchmarkResult {
  dossiers: number;
  planted: number;
  hits: number;
  misses: number;
  false_positives: number;
  hit_rate: number;
  elapsed_ms: number;
  packages?: Record<string, string>;
  rows: BenchmarkRow[];
}
