import { describe, expect, it } from "vitest";
import { availableTools, snapshot } from "../lib/api";
import { nextHumanAction } from "../components/ActionCenter";
import type { Run } from "../lib/types";

function runWith(findings: Run["findings"], extra: Partial<Run> = {}): Run {
  return {
    run_id: "run_test",
    dossier_id: "harbor-calm-serum-2026",
    product_name: "Harbor Calm Serum",
    status: extra.status ?? "findings_ready",
    packages: { prodocux: "0.3.0rc4", "pdx-artifact-engine": "0.3.0a4" },
    documents: [],
    evidence: [],
    findings,
    corrections: [],
    activities: [],
    bundle_digest: "a".repeat(64),
    checkpoint_id: "chk_test",
    approval_request_id: "apr_test",
    decided_by: null,
    active_finding_id: findings[0]?.finding_id ?? null,
    viewer_document_id: "formula",
    viewer_page: 1,
    draft_correction: null,
    stage: extra.stage ?? "corrections",
    subject_filename: extra.subject_filename ?? null,
    summary: {
      passed: findings.filter((item) => item.status === "pass" || item.status === "corrected").length,
      review: findings.filter((item) => item.status === "needs_review").length,
      total: findings.length,
    },
    ...extra,
  };
}

const FINDING_IDS: Record<string, string> = {
  "formula-version": "find-revision",
  "ph-range": "find-ph",
};

const finding = (
  check_id: string,
  status: Run["findings"][number]["status"],
): Run["findings"][number] => ({
  finding_id: FINDING_IDS[check_id] ?? `find-${check_id}`,
  check_id,
  severity: "high",
  status,
  title: check_id,
  message: check_id,
  evidence_refs: [],
  expected: check_id === "ph-range" ? "4.8–5.8" : 3,
  actual: check_id === "ph-range" ? 6.4 : 2,
  authority_document: "formula",
  observed_document: check_id === "ph-range" ? "coa" : "product-spec",
  authority_rule: "rule",
  action: check_id === "formula-version" ? "correct_subject_field" : check_id === "ph-range" ? "confirm_ref_observation" : "informational",
  assignee: check_id === "formula-version" ? "agent" : "human",
});

describe("tool catalog follows backend run state", () => {
  it("enables correction tools only while formula-version needs review", () => {
    const open = runWith([
      finding("formula-version", "needs_review"),
      finding("ph-range", "needs_review"),
    ]);
    const names = (current: Run) =>
      availableTools(current)
        .filter((tool) => tool.enabled)
        .map((tool) => tool.name);
    expect(names(open)).toContain("propose_correction");
    expect(names(open)).not.toContain("confirm_observed_fact");
    expect(names(open)).not.toContain("commit_correction");

    const drafted = runWith(open.findings, {
      draft_correction: { value: "3", reason: "Match the approved formula." },
    });
    expect(names(drafted)).toContain("commit_correction");

    const after = runWith([
      finding("formula-version", "corrected"),
      finding("ph-range", "needs_review"),
    ]);
    expect(names(after)).toContain("request_human_confirmation");
    expect(names(after)).not.toContain("confirm_observed_fact");
    expect(names(after)).not.toContain("propose_correction");

    const agentPh = runWith([
      finding("formula-version", "corrected"),
      { ...finding("ph-range", "needs_review"), assignee: "agent" },
    ]);
    expect(names(agentPh)).toContain("confirm_observed_fact");
    expect(names(agentPh)).not.toContain("request_human_confirmation");

    const ready = runWith(
      [finding("formula-version", "corrected"), finding("ph-range", "confirmed")],
      { status: "awaiting_human_approval", stage: "corrections" },
    );
    expect(names(ready)).toContain("request_human_approval");
    expect(names(ready)).not.toContain("record_approval");
    expect(snapshot(ready, true).available_tools).toContain("request_human_approval");
    expect(snapshot(ready, true).available_tools).not.toContain("record_approval");

    const closed = runWith(ready.findings, { status: "approved", stage: "closed" });
    expect(names(closed)).toContain("export_audit_package");
    expect(names(closed)).toContain("verify_package");
    expect(names(closed)).not.toContain("record_approval");
  });

  it("does not advertise a revision schema while find-ph is focused", () => {
    const ph = runWith(
      [finding("formula-version", "corrected"), finding("ph-range", "needs_review")],
      { stage: "corrections", active_finding_id: "find-ph", status: "findings_ready" },
    );
    const propose = availableTools(ph).find((tool) => tool.name === "propose_correction");
    expect(propose?.enabled).toBe(true);
    expect(propose?.description).toContain("find-ph");
    expect(propose?.description).toContain("6.4");
    expect(propose?.description).not.toContain("usually 3");
    expect(propose?.description).not.toContain("specification revision");
    expect(JSON.stringify(propose?.inputSchema)).toContain("proposed_value");
    expect(JSON.stringify(propose?.inputSchema)).not.toContain("usually 3");
    expect(propose?.description.toLowerCase()).toContain("locked reference");
    expect(availableTools(ph).find((tool) => tool.name === "confirm_observed_fact")?.enabled).toBe(false);
    expect(availableTools(ph).find((tool) => tool.name === "request_human_confirmation")?.enabled).toBe(true);
  });

  it("marks tools_changed only when the sequential catalog actually changes", () => {
    const documents = runWith(
      [finding("formula-version", "needs_review"), finding("ph-range", "needs_review")],
      { stage: "documents", status: "reviewing" },
    );
    const opened = snapshot({ ...documents, viewer_page: 2 }, true);
    const stillDocuments = snapshot({ ...documents, viewer_page: 3 }, true, opened.available_tools);
    expect(stillDocuments.tools_changed).toBe(false);
    expect(stillDocuments.refresh_hint).toBeUndefined();

    const findings = snapshot(
      { ...documents, stage: "findings", status: "findings_ready" },
      true,
      stillDocuments.available_tools,
    );
    expect(findings.tools_changed).toBe(true);
    expect(findings.refresh_hint).toContain("Workspace changed; refresh available tools and retry");
  });

  it("keeps findings and corrections tools closed until the documents step advances", () => {
    const loaded = runWith(
      [finding("formula-version", "needs_review"), finding("ph-range", "needs_review")],
      { stage: "documents" },
    );
    const names = availableTools(loaded)
      .filter((tool) => tool.enabled)
      .map((tool) => tool.name);
    expect(names).toContain("run_checks");
    expect(names).not.toContain("propose_correction");
    expect(names).not.toContain("select_finding");
    expect(snapshot(loaded, true).findings).toBeUndefined();
  });

  it("keeps the approve CTA short when the checkpoint id is long", () => {
    const ready = runWith(
      [finding("formula-version", "corrected"), finding("ph-range", "confirmed")],
      { status: "awaiting_human_approval", stage: "corrections", checkpoint_id: "chk_" + "a".repeat(40) },
    );
    const action = nextHumanAction(ready);
    expect(action?.id).toBe("approve");
    expect(action?.primary).toBe("Approve");
    expect(action?.title.length ?? 0).toBeLessThan(40);
    expect(action?.title).toContain("…");
  });

  it("keeps run_benchmark available while idle and assign_finding after findings open", () => {
    const idle = availableTools(null)
      .filter((tool) => tool.enabled)
      .map((tool) => tool.name);
    expect(idle).toContain("run_benchmark");
    expect(idle).not.toContain("assign_finding");

    const findings = runWith(
      [finding("formula-version", "needs_review"), finding("ph-range", "needs_review")],
      { stage: "findings", status: "findings_ready" },
    );
    const names = availableTools(findings)
      .filter((tool) => tool.enabled)
      .map((tool) => tool.name);
    expect(names).toContain("assign_finding");
    expect(names).toContain("run_benchmark");
  });

  it("blocks propose_correction copy when the revision is assigned to the human", () => {
    const blocked = runWith([
      { ...finding("formula-version", "needs_review"), assignee: "human" },
      finding("ph-range", "needs_review"),
    ]);
    const propose = availableTools(blocked).find((tool) => tool.name === "propose_correction");
    expect(propose?.description).toContain("assigned to the human");
    expect(propose?.description).toContain("cannot take this finding");
  });
});
