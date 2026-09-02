import type { DocumentId, DocumentPage, DossierDocument } from "../lib/types";

function facsimileText(line: string): string {
  return line.replace(/\s\?\sMaster Formula/g, " — Master Formula").replace(/\?\sMaster Formula/g, "— Master Formula");
}

export function DocumentPane({
  document,
  page,
  onOpen,
  compared,
}: {
  document?: DossierDocument;
  page: number | null;
  onOpen: (documentId: DocumentId, page: number) => void;
  compared?: { title: string; pages: DocumentPage[] };
}) {
  if (!document || !page) {
    return (
      <div className="preview">
        <small>No source open</small>
        <div className="viewer-placeholder">
          <b>The original is not on screen yet</b>
          <span>Open a source document from a finding. Agents should call open_source_document instead of guessing the layout.</span>
        </div>
      </div>
    );
  }
  const leaf = document.pages.find((item) => item.page === page) ?? document.pages[0];
  const comparedLeaf = compared?.pages.find((item) => item.page === leaf.page) ?? compared?.pages[0];
  return (
    <div className="preview viewer-open">
      <small>
        Source facsimile · {document.filename} · page {leaf.page} · digest{" "}
        {document.source_sha256.slice(0, 12)}…
      </small>
      <div className={comparedLeaf ? "artifact-split" : undefined}>
        <article className="paper">
          <p>{comparedLeaf ? "Original locked PDF" : leaf.title}</p>
          {leaf.lines.map((line) =>
            line === leaf.highlight ? <mark key={line}>{facsimileText(line)}</mark> : <span key={line}>{facsimileText(line)}</span>,
          )}
        </article>
        {comparedLeaf ? (
          <article className="paper reviewed">
            <p>{compared?.title}</p>
            {comparedLeaf.lines.map((line) =>
              line === comparedLeaf.highlight ? <mark key={line}>{facsimileText(line)}</mark> : <span key={line}>{facsimileText(line)}</span>,
            )}
          </article>
        ) : null}
      </div>
      <div className="page-nav">
        {document.pages.map((item) => (
          <button
            key={item.page}
            className={item.page === leaf.page ? "on" : ""}
            onClick={() => onOpen(document.document_id, item.page)}
          >
            p.{item.page}
          </button>
        ))}
      </div>
    </div>
  );
}
