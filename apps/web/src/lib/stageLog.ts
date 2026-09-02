import type { ActivityEvent, UiStage } from "./types";

const STAGE_TOOLS: Record<UiStage, string[]> = {
  documents: ["start_demo_audit", "run_benchmark", "open_source_document"],
  findings: ["run_checks", "select_finding", "assign_finding", "open_source_document"],
  corrections: [
    "select_finding",
    "assign_finding",
    "propose_correction",
    "commit_correction",
    "reject_draft",
    "confirm_observed_fact",
    "request_human_confirmation",
    "rewrite_locked_reference",
    "open_source_document",
  ],
  closed: [
    "confirm_observed_fact",
    "request_human_confirmation",
    "request_human_approval",
    "record_approval",
    "verify_package",
    "export_audit_package",
  ],
};

export function stageEvents(events: ActivityEvent[], stage: UiStage): ActivityEvent[] {
  const tools = new Set(STAGE_TOOLS[stage]);
  return events.filter((event) => event.tool && tools.has(event.tool));
}
