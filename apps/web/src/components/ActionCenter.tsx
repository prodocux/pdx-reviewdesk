import { isClosed } from "../lib/api";
import type { Run } from "../lib/types";

export interface HumanAction {
  id: "confirm" | "approve";
  index: number;
  total: number;
  title: string;
  primary: string;
  secondary: string;
}

export function nextHumanAction(run: Run | null): HumanAction | null {
  if (!run || isClosed(run)) return null;
  const revision = run.findings.find((item) => item.check_id === "formula-version");
  const ph = run.findings.find((item) => item.check_id === "ph-range");
  const steps: Array<{ id: "confirm" | "approve"; done: boolean; title: string; primary: string; secondary: string }> =
    [];
  if (ph && ph.assignee === "human" && ph.status !== "pass") {
    steps.push({
      id: "confirm",
      done: ph.status !== "needs_review",
      title: `Confirm that CoA pH ${String(ph.actual)} is an observed fact`,
      primary: "Confirm observation",
      secondary: "Review evidence",
    });
  }
  const checkpoint = run.checkpoint_id ?? "";
  const shortCheckpoint = checkpoint.length > 16 ? `${checkpoint.slice(0, 12)}…` : checkpoint;
  steps.push({
    id: "approve",
    done: run.status !== "awaiting_human_approval",
    title: shortCheckpoint ? `Approve checkpoint ${shortCheckpoint}` : "Approve checkpoint",
    primary: "Approve",
    secondary: "Review",
  });
  if (revision?.status === "needs_review") {
    return null;
  }
  const currentIndex = steps.findIndex((item) => !item.done);
  if (currentIndex < 0) return null;
  const current = steps[currentIndex];
  return {
    id: current.id,
    index: currentIndex + 1,
    total: steps.length,
    title: current.title,
    primary: current.primary,
    secondary: current.secondary,
  };
}

export function ActionCenter({
  action,
  busy,
  onPrimary,
  onSecondary,
}: {
  action: HumanAction;
  busy: boolean;
  onPrimary: () => void;
  onSecondary: () => void;
}) {
  return (
    <aside className="action-center">
      <div className="action-center-copy">
        <small>
          Human action required · {action.index} of {action.total}
          {action.id === "approve" ? " · WebMCP tools cannot approve" : ""}
        </small>
        <strong title={action.title}>{action.title}</strong>
      </div>
      <div>
        <button type="button" disabled={busy} onClick={onSecondary}>
          {action.secondary}
        </button>
        <button type="button" className="primary" disabled={busy} onClick={onPrimary}>
          {action.primary}
        </button>
      </div>
    </aside>
  );
}
