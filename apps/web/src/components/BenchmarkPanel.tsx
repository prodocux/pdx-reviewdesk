import type { BenchmarkResult } from "../lib/types";

export function BenchmarkPanel({
  result,
  busy,
  onRun,
}: {
  result?: BenchmarkResult;
  busy: boolean;
  onRun: () => void;
}) {
  return (
    <aside className="bench">
      <small>Pipeline proof</small>
      <h3>10 dossiers · planted discrepancies</h3>
      <p>
        Same ProDocuX checks as the open desk. Harbor and Cedar are included so the score is not a
        second hardcoded story.
      </p>
      <button disabled={busy} onClick={onRun}>
        {busy ? "Scoring…" : "Run benchmark"}
      </button>
      {result && (
        <>
          <div className="bench-score">
            <strong>{Math.round(result.hit_rate * 100)}%</strong>
            <span>
              {result.hits}/{result.planted} hits · {result.false_positives} false positives ·{" "}
              {result.misses} misses · {result.elapsed_ms} ms
            </span>
          </div>
          <ol>
            {result.rows.map((row) => (
              <li key={row.dossier_id}>
                <b>{row.product_name}</b>
                <small>
                  planted {row.planted.join(", ") || "none"} · flagged {row.flagged.join(", ") || "none"}
                  {row.false_positives.length ? ` · FP ${row.false_positives.join(", ")}` : ""}
                  {row.misses.length ? ` · miss ${row.misses.join(", ")}` : ""}
                </small>
              </li>
            ))}
          </ol>
        </>
      )}
    </aside>
  );
}
