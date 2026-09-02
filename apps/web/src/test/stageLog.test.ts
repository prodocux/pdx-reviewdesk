import { describe, expect, it } from "vitest";
import { stageEvents } from "../lib/stageLog";
import type { ActivityEvent } from "../lib/types";

function event(tool: string): ActivityEvent {
  return {
    event_id: tool,
    at: "2026-09-02T00:00:00Z",
    actor: "human",
    tool,
    message: tool,
  };
}

describe("stage activity filters", () => {
  it("shows confirmation and approval on the Close step", () => {
    const events = [
      event("select_finding"),
      event("confirm_observed_fact"),
      event("record_approval"),
      event("export_audit_package"),
    ];
    expect(stageEvents(events, "closed").map((item) => item.tool)).toEqual([
      "confirm_observed_fact",
      "record_approval",
      "export_audit_package",
    ]);
  });
});
