import { waitMessage, type HostStatus, type WaitPhase } from "../lib/waitCopy";

export function WaitNotice({
  busy,
  elapsedSec,
  phase = "generic",
  host = "unknown",
}: {
  busy: boolean;
  elapsedSec: number;
  phase?: WaitPhase;
  host?: HostStatus;
}) {
  if (busy) {
    return (
      <div className="wait-notice busy" role="status" aria-live="polite">
        {waitMessage(elapsedSec, phase)}
      </div>
    );
  }
  if (host === "waking") {
    return (
      <div className="wait-notice" role="status" aria-live="polite">
        Waking the hosted API (Render Free, often 30–60s when idle). Drop PDFs now; Open will wait until it is up.
      </div>
    );
  }
  if (host === "down") {
    return (
      <div className="wait-notice warn" role="status">
        Hosted API did not respond. Retry in a moment, or open /health in another tab to wake it.
      </div>
    );
  }
  return null;
}
