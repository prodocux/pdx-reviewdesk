import type { EvidenceField, Finding, Run } from "../lib/types";

const LABELS: Record<string, string> = {
  "product-spec": "Product specification",
  formula: "Approved formula",
  coa: "Certificate of analysis",
};

export function EvidenceChain({
  run,
  finding,
}: {
  run: Run;
  finding?: Finding;
}) {
  if (!finding) {
    return null;
  }
  const evidence = run.evidence.filter((item) => finding.evidence_refs.includes(item.evidence_id));
  const claim = evidence.find((item) => item.document_id === finding.authority_document);
  const observed = evidence.find((item) => item.document_id === finding.observed_document);
  const human = run.activities.find(
    (item) =>
      item.tool &&
      ["propose_correction", "commit_correction", "confirm_observed_fact", "reject_draft", "record_approval"].includes(
        item.tool,
      ),
  );
  return (
    <aside className="chain">
      <small>Evidence / provenance</small>
      <ol>
        <li>
          <b>Claim</b>
          <span>
            {claim
              ? `${LABELS[claim.document_id]} ${claim.field_name.replaceAll("_", " ")} = ${String(claim.normalized_value)}`
              : finding.authority_rule}
          </span>
        </li>
        <li>
          <b>Evidence</b>
          <span>
            {observed
              ? `${LABELS[observed.document_id]} page ${observed.source.page}: ${observed.source.snippet}`
              : "No locator"}
          </span>
        </li>
        <li>
          <b>Decision</b>
          <span>
            {finding.status.replaceAll("_", " ")} · {finding.check_id}
          </span>
        </li>
        <li>
          <b>Proposed action</b>
          <span>
            {finding.action === "correct_subject_field"
              ? `Correct subject field to ${String(finding.expected)}`
              : finding.action === "confirm_ref_observation"
                ? "Confirm the reference observation; do not rewrite the file"
                : "Informational — no rewrite"}
          </span>
        </li>
        <li>
          <b>Source digest</b>
          <span className="mono">
            {run.documents.find((item) => item.document_id === finding.observed_document)?.source_sha256.slice(0, 16)}…
          </span>
        </li>
        <li>
          <b>Engine</b>
          <span>
            prodocux {run.packages.prodocux}
            {run.verification_elapsed_ms != null ? ` · ${run.verification_elapsed_ms} ms` : ""}
          </span>
        </li>
        <li>
          <b>Human decision</b>
          <span>{human ? human.message : "Pending"}</span>
        </li>
        <li>
          <b>Output digest</b>
          <span className="mono">{run.bundle_digest.slice(0, 16)}…</span>
        </li>
      </ol>
    </aside>
  );
}

export function InlineDiff({
  before,
  after,
  field,
}: {
  before: string;
  after: string;
  field: string;
}) {
  return (
    <div className="diff">
      <small>Before / after · {field}</small>
      <p>
        <del>{before}</del>
        <ins>{after}</ins>
      </p>
    </div>
  );
}

export function evidenceFor(run: Run, finding: Finding): EvidenceField[] {
  return run.evidence.filter((item) => finding.evidence_refs.includes(item.evidence_id));
}
