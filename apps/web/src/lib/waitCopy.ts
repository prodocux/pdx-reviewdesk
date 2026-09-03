export type WaitPhase = "wake" | "upload" | "start" | "generic";
export type HostStatus = "unknown" | "waking" | "ready" | "down";

export function waitMessage(elapsedSec: number, phase: WaitPhase = "generic"): string {
  const seconds = elapsedSec > 0 ? ` ${elapsedSec}s.` : "";
  if (phase === "wake") {
    return elapsedSec < 4
      ? "Checking the hosted API…"
      : `Waking Render Free${seconds} ProDocuX is not running yet — this wait is the host, not the checks.`;
  }
  if (phase === "upload") {
    return elapsedSec < 4
      ? "Uploading PDFs and extracting selectable text…"
      : `Still opening the dropped dossier${seconds} Extraction and ProDocuX checks are usually a few hundred milliseconds after the host is up.`;
  }
  if (phase === "start") {
    return elapsedSec < 4
      ? "Opening the canned dossier…"
      : `Still starting the demo${seconds} The host may still be waking.`;
  }
  return elapsedSec < 4 ? "Working…" : `Still working${seconds}`;
}

export function hostLabel(status: HostStatus): string {
  if (status === "waking") return "Hosted API waking";
  if (status === "ready") return "Ready · API warm";
  if (status === "down") return "Hosted API unreachable";
  return "Ready";
}
