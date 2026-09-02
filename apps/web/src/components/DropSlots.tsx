import type { DocumentId } from "../lib/types";

const SLOTS: Array<{
  id: DocumentId;
  role: "subject" | "ref";
  title: string;
  hint: string;
}> = [
  {
    id: "product-spec",
    role: "subject",
    title: "Product specification",
    hint: "This is the file under review. A later correction can produce a new subject copy.",
  },
  {
    id: "formula",
    role: "ref",
    title: "Approved formula",
    hint: "Locked reference. ReviewDesk will refuse to overwrite it.",
  },
  {
    id: "coa",
    role: "ref",
    title: "Certificate of analysis",
    hint: "Locked reference. Observed facts stay on this file.",
  },
];

export function DropSlots({
  files,
  busy,
  onFile,
  onStart,
}: {
  files: Partial<Record<DocumentId, File>>;
  busy: boolean;
  onFile: (slot: DocumentId, file: File | null) => void;
  onStart: () => void;
}) {
  const ready = Boolean(files["product-spec"] && files.formula && files.coa);
  return (
    <div className="drop-board">
      <small>Human classification</small>
      <h3>Drop PDFs into subject vs reference slots</h3>
      <p>
        Role is decided by the slot, not the filename. Putting a formula into the subject slot makes it
        the document under review; putting a specification into a reference slot locks it.
      </p>
      <p>
        Supported PDFs have selectable text. ProDocuX extracts that text, including
        ordinary compressed streams. ReviewDesk then looks for the labels{" "}
        <code>Product</code>, <code>Formula revision</code>, <code>Acceptable pH</code>, and{" "}
        <code>pH result</code>. Scanned or image-only files need OCR, which this demo
        does not enable.
      </p>
      <div className="drop-grid">
        {SLOTS.map((slot) => {
          const file = files[slot.id];
          return (
            <label
              key={slot.id}
              className={`drop-slot ${slot.role} ${file ? "filled" : ""}`}
              onDragOver={(event) => event.preventDefault()}
              onDrop={(event) => {
                event.preventDefault();
                const next = event.dataTransfer.files[0];
                if (next) onFile(slot.id, next);
              }}
            >
              <small>{slot.role === "subject" ? "Subject · you are proofreading this" : "Reference · do not rewrite"}</small>
              <strong>{slot.title}</strong>
              <span>{file ? file.name : "Drop a PDF or click to choose"}</span>
              <em>{slot.hint}</em>
              <input
                type="file"
                accept="application/pdf,.pdf"
                disabled={busy}
                onChange={(event) => onFile(slot.id, event.target.files?.[0] ?? null)}
              />
              {file && (
                <button
                  type="button"
                  disabled={busy}
                  onClick={(event) => {
                    event.preventDefault();
                    onFile(slot.id, null);
                  }}
                >
                  Clear
                </button>
              )}
            </label>
          );
        })}
      </div>
      <button className="primary" disabled={busy || !ready} onClick={onStart}>
        Open dropped dossier
      </button>
    </div>
  );
}
