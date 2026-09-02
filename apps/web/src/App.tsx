import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ActionCenter, nextHumanAction } from "./components/ActionCenter";
import { ActivityLog } from "./components/ActivityLog";
import { AgentConsole } from "./components/AgentConsole";
import { BenchmarkPanel } from "./components/BenchmarkPanel";
import { DocumentPane } from "./components/DocumentPane";
import { DropSlots } from "./components/DropSlots";
import { EvidenceChain, InlineDiff } from "./components/EvidenceChain";
import {
  availableTools,
  assignFinding,
  commitCorrection,
  confirmObservedFact,
  exportAuditPackage,
  getRun,
  isClosed,
  listDossiers,
  openSourceDocument,
  proposeCorrection,
  recordApproval,
  rejectDraft,
  requestHumanApproval,
  requestHumanConfirmation,
  revealFindings,
  rewriteLockedReference,
  runBenchmark,
  selectFinding,
  snapshot,
  sourceFileUrl,
  startDemo,
  startFromUploads,
  subjectFileUrl,
  summarize,
  verifyPackage,
} from "./lib/api";
import type { ActivityEvent, Actor, BenchmarkResult, DocumentId, DossierInfo, Finding, Run, UiStage, VerifyResult } from "./lib/types";
import { ToolHost, getModelContext } from "./lib/webmcp";
import { pathRunId, rememberRun, rememberedRunId, runPath, RUN_CHANNEL } from "./lib/session";

const LABELS: Record<DocumentId, string> = {
  "product-spec": "Product specification",
  formula: "Approved formula",
  coa: "Certificate of analysis",
};

const ACTION_COPY: Record<Finding["action"], string> = {
  correct_subject_field: "Correct a field on the subject",
  confirm_ref_observation: "Confirm a reference observation",
  informational: "Context only · no file rewrite",
};

const STEPS: Array<{ id: UiStage; label: string }> = [
  { id: "documents", label: "Documents" },
  { id: "findings", label: "Findings" },
  { id: "corrections", label: "Corrections" },
  { id: "closed", label: "Close" },
];

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
  closed: ["request_human_approval", "verify_package", "export_audit_package"],
};

function visualStep(run: Run | null): number {
  if (!run) return -1;
  if (isClosed(run) || run.stage === "closed") return 3;
  if (run.stage === "documents") return 0;
  if (run.stage === "findings") return 1;
  if (run.findings.some((item) => item.status === "needs_review")) return 2;
  return 3;
}

function stageEvents(events: ActivityEvent[], stage: UiStage): ActivityEvent[] {
  const tools = new Set(STAGE_TOOLS[stage]);
  return events.filter((event) => event.tool && tools.has(event.tool));
}

async function downloadAudit(run: Run, actor: Actor = "human", channel: "ui" | "webmcp" = "ui") {
  const payload = await exportAuditPackage(run.run_id, actor, channel);
  const blob = new Blob([JSON.stringify(payload, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = `reviewdesk-${run.run_id}.json`;
  link.click();
  URL.revokeObjectURL(url);
  return payload;
}

export default function App() {
  const [run, setRun] = useState<Run | null>(null);
  const [webmcp, setWebmcp] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string>();
  const [correctionValue, setCorrectionValue] = useState("");
  const [correctionReason, setCorrectionReason] = useState("");
  const [showCorrection, setShowCorrection] = useState(false);
  const [dossiers, setDossiers] = useState<DossierInfo[]>([]);
  const [verify, setVerify] = useState<VerifyResult>();
  const [uploads, setUploads] = useState<Partial<Record<DocumentId, File>>>({});
  const [benchmark, setBenchmark] = useState<BenchmarkResult>();
  const [resumeHint, setResumeHint] = useState<Run>();
  const [flash, setFlash] = useState<"webmcp" | null>(null);
  const runRef = useRef(run);
  runRef.current = run;
  const toolsRef = useRef<string[]>([]);
  const hostRef = useRef(new ToolHost());
  const busRef = useRef<BroadcastChannel | null>(null);
  const actionRef = useRef<HTMLDivElement | null>(null);
  const stageRef = useRef<HTMLElement | null>(null);
  const closedRef = useRef<HTMLDivElement | null>(null);
  const seenFocusRef = useRef<{ runId?: string; stage?: string; updated?: string | null; primed?: boolean }>({});

  const commitRun = useCallback((next: Run | null, opts?: { syncUrl?: boolean }) => {
    setRun(next);
    if (next) {
      rememberRun(next.run_id);
      if (opts?.syncUrl !== false && pathRunId() !== next.run_id) {
        window.history.pushState({ runId: next.run_id }, "", runPath(next.run_id));
      }
      try {
        busRef.current?.postMessage({ type: "run", run: next });
      } catch {
        /* channel closed */
      }
    }
  }, []);
  const commitRunRef = useRef(commitRun);
  commitRunRef.current = commitRun;

  const tools = useMemo(() => availableTools(run), [run]);
  const summary = run ? summarize(run) : { passed: 0, confirmed: 0, unresolved: 0, review: 0, total: 0 };
  const humanAction = nextHumanAction(run);
  const finding = run?.findings.find((item) => item.finding_id === run.active_finding_id);
  const viewer = run?.documents.find((item) => item.document_id === run.viewer_document_id);
  const reviewOpen = run?.findings.filter((item) => item.status === "needs_review") ?? [];
  const current = visualStep(run);
  const stage: UiStage = run?.stage ?? "documents";
  const subject = run?.documents.find((item) => item.role === "subject" || item.document_id === "product-spec");
  const refs = run?.documents.filter((item) => item.document_id !== "product-spec") ?? [];
  const closed = isClosed(run);
  const focusKind = humanAction ? "action" : closed ? "closed" : "stage";

  useEffect(() => {
    if (!run) {
      seenFocusRef.current = {};
      setFlash(null);
      return;
    }
    const seen = seenFocusRef.current;
    const first = !seen.primed;
    const stageChanged = seen.runId === run.run_id && seen.stage !== run.stage;
    const updated = seen.runId === run.run_id && seen.updated !== run.updated_at;
    const newRun = Boolean(seen.runId) && seen.runId !== run.run_id;
    seenFocusRef.current = {
      runId: run.run_id,
      stage: run.stage,
      updated: run.updated_at,
      primed: true,
    };
    if (first) return;
    if (!stageChanged && !updated && !newRun) return;
    const fromWebmcp = run.activities[0]?.invocation_channel === "webmcp";
    const target =
      (humanAction ? actionRef.current : null) ??
      (closed ? closedRef.current : null) ??
      stageRef.current;
    if (stageChanged || newRun || fromWebmcp) {
      window.requestAnimationFrame(() => {
        target?.scrollIntoView({ behavior: "smooth", block: "start" });
      });
    }
    if (fromWebmcp) {
      setFlash("webmcp");
      const timer = window.setTimeout(() => setFlash(null), 1800);
      return () => window.clearTimeout(timer);
    }
  }, [run, humanAction, closed]);

  useEffect(() => {
    listDossiers().then(setDossiers).catch(() => undefined);
    const id = pathRunId() ?? rememberedRunId();
    if (!id) return;
    getRun(id)
      .then((loaded) => commitRun(loaded, { syncUrl: Boolean(pathRunId()) ? false : true }))
      .catch(() => {
        rememberRun(null);
        if (pathRunId()) window.history.replaceState({}, "", "/");
      });
  }, [commitRun]);

  useEffect(() => {
    if (run || pathRunId()) return;
    const id = rememberedRunId();
    if (!id) return;
    getRun(id).then(setResumeHint).catch(() => rememberRun(null));
  }, [run]);

  useEffect(() => {
    const bus = new BroadcastChannel(RUN_CHANNEL);
    busRef.current = bus;
    bus.onmessage = (event: MessageEvent<{ type?: string; run?: Run }>) => {
      const incoming = event.data?.run;
      if (event.data?.type === "run" && incoming && incoming.run_id === runRef.current?.run_id) {
        setRun(incoming);
      }
    };
    return () => {
      bus.close();
      busRef.current = null;
    };
  }, []);

  useEffect(() => {
    const onPop = () => {
      const id = pathRunId();
      if (!id) {
        setRun(null);
        return;
      }
      getRun(id)
        .then((loaded) => commitRun(loaded, { syncUrl: false }))
        .catch(() => setError("That run could not be restored."));
    };
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, [commitRun]);

  useEffect(() => {
    if (!run?.run_id) return;
    const timer = window.setInterval(() => {
      const current = runRef.current;
      if (!current) return;
      getRun(current.run_id)
        .then((loaded) => {
          if (loaded.updated_at && loaded.updated_at !== current.updated_at) {
            setRun(loaded);
          }
        })
        .catch(() => undefined);
    }, 2500);
    return () => window.clearInterval(timer);
  }, [run?.run_id]);

  async function withActor(work: (current: Run | null) => Promise<unknown> | unknown): Promise<void> {
    setBusy(true);
    setError(undefined);
    try {
      await work(runRef.current);
    } catch (reason) {
      const message = reason instanceof Error ? reason.message : "The action could not be completed.";
      setError(message);
      throw reason;
    } finally {
      setBusy(false);
    }
  }

  const handlers = useMemo(
    () => {
      const wrapSnap = (next: Run | Record<string, unknown>) => {
        const previous = toolsRef.current;
        if (next && typeof next === "object" && "run_id" in next) {
          const snap = snapshot(next as Run, Boolean(getModelContext()), previous);
          toolsRef.current = snap.available_tools;
          return snap;
        }
        return next;
      };
      return {
        get_workspace_state: async (_input: Record<string, unknown> = {}) =>
          snapshot(runRef.current, Boolean(getModelContext()), toolsRef.current),
        start_demo_audit: async (input: Record<string, unknown> = {}) => {
          const dossierId = input.dossier_id ? String(input.dossier_id) : undefined;
          const next = await startDemo("agent", dossierId, "webmcp");
          commitRunRef.current(next);
          setShowCorrection(false);
          setVerify(undefined);
          setUploads({});
          return wrapSnap(next);
        },
        run_benchmark: async (_input: Record<string, unknown> = {}) => {
          const result = await runBenchmark();
          setBenchmark(result);
          return result;
        },
        assign_finding: async (input: Record<string, unknown>) => {
          const currentRun = runRef.current;
          if (!currentRun) throw new Error("Start an audit first.");
          const next = await assignFinding(
            currentRun.run_id,
            String(input.finding_id ?? currentRun.active_finding_id ?? ""),
            "human",
            "agent",
            "webmcp",
          );
          commitRunRef.current(next);
          return wrapSnap(next);
        },
        run_checks: async (_input: Record<string, unknown> = {}) => {
          const currentRun = runRef.current;
          if (!currentRun) throw new Error("Start an audit first.");
          const next = await revealFindings(currentRun.run_id, "agent", "webmcp");
          commitRun(next);
          return wrapSnap(next);
        },
        select_finding: async (input: Record<string, unknown>) => {
          const currentRun = runRef.current;
          if (!currentRun) throw new Error("Start an audit first.");
          const findingId = String(input.finding_id ?? currentRun.active_finding_id ?? "");
          const next = await selectFinding(currentRun.run_id, findingId, "agent", "webmcp");
          commitRun(next);
          return wrapSnap(next);
        },
        open_source_document: async (input: Record<string, unknown>) => {
          const currentRun = runRef.current;
          if (!currentRun) throw new Error("Start an audit first.");
          const documentId = String(input.document_id ?? currentRun.viewer_document_id) as DocumentId;
          const page = input.page === undefined ? undefined : Number(input.page);
          const next = await openSourceDocument(currentRun.run_id, documentId, page, "agent", "webmcp");
          commitRun(next);
          return wrapSnap(next);
        },
        propose_correction: async (input: Record<string, unknown>) => {
          const currentRun = runRef.current;
          if (!currentRun) throw new Error("Start an audit first.");
          const value = String(input.proposed_value ?? input.corrected_value ?? "");
          const reason = String(input.reason ?? "");
          const next = await proposeCorrection(
            currentRun.run_id,
            {
              proposed_value: value,
              reason,
              finding_id: input.finding_id ? String(input.finding_id) : currentRun.active_finding_id ?? undefined,
              field: input.field ? String(input.field) : undefined,
              document_id: input.document_id ? (String(input.document_id) as DocumentId) : undefined,
              current_value: input.current_value ? String(input.current_value) : undefined,
            },
            "agent",
            "webmcp",
          );
          commitRun(next);
          setShowCorrection(true);
          setCorrectionValue(value);
          setCorrectionReason(reason);
          return wrapSnap(next);
        },
        commit_correction: async (_input: Record<string, unknown> = {}) => {
          const currentRun = runRef.current;
          if (!currentRun) throw new Error("Start an audit first.");
          const next = await commitCorrection(currentRun.run_id, "agent", "webmcp");
          commitRun(next);
          setShowCorrection(false);
          return wrapSnap(next);
        },
        reject_draft: async (input: Record<string, unknown> = {}) => {
          const currentRun = runRef.current;
          if (!currentRun) throw new Error("Start an audit first.");
          const next = await rejectDraft(
            currentRun.run_id,
            String(input.reason ?? "Human rejected the agent draft."),
            "agent",
            "webmcp",
          );
          commitRun(next);
          setShowCorrection(false);
          return wrapSnap(next);
        },
        confirm_observed_fact: async (_input: Record<string, unknown> = {}) => {
          const currentRun = runRef.current;
          if (!currentRun) throw new Error("Start an audit first.");
          const next = await confirmObservedFact(currentRun.run_id, "agent", "webmcp");
          commitRun(next);
          return wrapSnap(next);
        },
        request_human_confirmation: async (_input: Record<string, unknown> = {}) => {
          const currentRun = runRef.current;
          if (!currentRun) throw new Error("Start an audit first.");
          const next = await requestHumanConfirmation(currentRun.run_id, "agent", "webmcp");
          commitRun(next);
          return wrapSnap(next);
        },
        request_human_approval: async (_input: Record<string, unknown> = {}) => {
          const currentRun = runRef.current;
          if (!currentRun) throw new Error("Start an audit first.");
          const next = await requestHumanApproval(currentRun.run_id, "agent", "webmcp");
          commitRun(next);
          return wrapSnap(next);
        },
        rewrite_locked_reference: async (input: Record<string, unknown> = {}) => {
          const currentRun = runRef.current;
          if (!currentRun) throw new Error("Start an audit first.");
          const documentId = String(input.document_id ?? "formula") as DocumentId;
          try {
            const next = await rewriteLockedReference(currentRun.run_id, documentId, "agent", "webmcp");
            commitRun(next);
            return wrapSnap(next);
          } catch (reason) {
            const recovered =
              reason && typeof reason === "object" && "run" in reason
                ? (reason as { run?: Run }).run
                : undefined;
            if (recovered) commitRun(recovered);
            const message = reason instanceof Error ? reason.message : "Policy gate blocked the rewrite.";
            setError(message);
            throw reason;
          }
        },
        verify_package: async (_input: Record<string, unknown> = {}) => {
          const currentRun = runRef.current;
          if (!currentRun) throw new Error("Start an audit first.");
          const result = await verifyPackage(currentRun.run_id, "agent", "webmcp");
          setVerify(result);
          if (result.status) {
            const latest = await getRun(currentRun.run_id);
            commitRun(latest);
          }
          return result;
        },
        export_audit_package: async (_input: Record<string, unknown> = {}) => {
          const currentRun = runRef.current;
          if (!currentRun) throw new Error("Start an audit first.");
          return downloadAudit(currentRun, "agent", "webmcp");
        },
      };
    },
    [],
  );

  useEffect(() => {
    let cancelled = false;
    hostRef.current
      .sync(availableTools(run), handlers)
      .then((ok) => {
        if (!cancelled) setWebmcp(ok);
      })
      .catch(() => {
        if (!cancelled) setWebmcp(false);
      });
    toolsRef.current = availableTools(run)
      .filter((tool) => tool.enabled)
      .map((tool) => tool.name);
    return () => {
      cancelled = true;
    };
  }, [run, handlers]);

  async function humanStart(dossierId?: string) {
    if (
      run &&
      !window.confirm(
        `Judge mode reset starts a NEW run. The current run stays at ${runPath(run.run_id)}.`,
      )
    ) {
      return;
    }
    await withActor(async () => {
      const next = await startDemo("human", dossierId);
      commitRun(next);
      setShowCorrection(false);
      setVerify(undefined);
      setUploads({});
      const revision = next.evidence.find(
        (item) => item.document_id === "product-spec" && item.field_name === "formula_revision",
      );
      const expected = next.findings.find((item) => item.check_id === "formula-version")?.expected;
      setCorrectionValue(String(expected ?? revision?.normalized_value ?? ""));
      setCorrectionReason("");
    }).catch(() => undefined);
  }

  async function humanUpload() {
    const subject = uploads["product-spec"];
    const formula = uploads.formula;
    const coa = uploads.coa;
    if (!subject || !formula || !coa) {
      setError("Drop one subject PDF and two locked reference PDFs.");
      return;
    }
    await withActor(async () => {
      const next = await startFromUploads("human", { subject, formula, coa });
      commitRun(next);
      setShowCorrection(false);
      setVerify(undefined);
      setUploads({});
      const revision = next.evidence.find(
        (item) => item.document_id === "product-spec" && item.field_name === "formula_revision",
      );
      const expected = next.findings.find((item) => item.check_id === "formula-version")?.expected;
      setCorrectionValue(String(expected ?? revision?.normalized_value ?? ""));
      setCorrectionReason("");
    }).catch(() => undefined);
  }

  async function fallbackTool(name: string) {
    const currentRun = runRef.current;
    const args: Record<string, unknown> = {};
    if (name === "select_finding") {
      args.finding_id = currentRun?.active_finding_id ?? "find-revision";
    }
    if (name === "open_source_document") {
      args.document_id = currentRun?.viewer_document_id ?? "product-spec";
      args.page = currentRun?.viewer_page ?? 1;
    }
    if (name === "propose_correction") {
      args.finding_id = currentRun?.active_finding_id;
      args.proposed_value = correctionValue || String(finding?.expected ?? "3");
      args.reason = correctionReason || "Approved formula revision is authoritative.";
      args.field = "formula_revision";
      args.document_id = "product-spec";
    }
    if (name === "reject_draft") {
      args.reason = correctionReason || "Human rejected the agent draft.";
    }
    if (name === "rewrite_locked_reference") {
      args.document_id = "formula";
    }
    if (name === "assign_finding") {
      args.finding_id = currentRun?.active_finding_id ?? "find-ph";
      args.assignee = "human";
    }
    if (name === "start_demo_audit") {
      args.dossier_id = "harbor-calm-serum-2026";
    }
    await withActor(() => handlers[name as keyof typeof handlers](args)).catch(() => undefined);
  }

  const pointer =
    run?.viewer_document_id && run.viewer_page
      ? `Agent/human pointer: ${LABELS[run.viewer_document_id]} p.${run.viewer_page}${
          finding ? ` · ${finding.finding_id}` : ""
        }`
      : null;

  return (
    <main className="shell">
      <header className="topbar">
        <div className="brand">
          <b>RD</b>
          <div>
            <span>PDX ReviewDesk</span>
            <small>Evidence, human approval, verifiable outputs</small>
          </div>
        </div>
        <div className="tools">
          {run && (
            <span className="run-meta">
              {run.run_id}
              <small>
                updated {run.updated_at ? new Date(run.updated_at).toLocaleTimeString() : "just now"}
              </small>
            </span>
          )}
          <button
            className="run"
            onClick={() => humanStart("harbor-calm-serum-2026")}
            disabled={busy}
            title="Starts a new run. The current run remains available at its URL."
          >
            {busy ? "Working…" : "Judge mode reset"}
          </button>
          <span className={`status ${webmcp ? "live" : ""}`} title="Technical status">
            <i />
            {webmcp ? "WebMCP tools registered" : "WebMCP off · in-page tools"}
          </span>
        </div>
      </header>

      <section className="hero">
        <div>
          <p>{run ? `${run.product_name} · ${run.status.replaceAll("_", " ")} · ${run.run_id}` : "Review Desk"}</p>
          <h1>Review regulated documents with evidence, human approval, and verifiable outputs.</h1>
          <span>
            {pointer ??
              "WebMCP lets an agent enter this desk. PDX proves what it saw, changed, and delivered."}
          </span>
          {error && (
            <div className="error" role="alert">
              {error}
            </div>
          )}
        </div>
        <div className="score">
          <strong>{run && stage !== "documents" ? `${summary.review}` : "—"}</strong>
          <div>
            <b>{stage === "documents" ? "Sources locked" : `${summary.review} discrepancies`}</b>
            <small>
              {!run
                ? "Start a dossier to load evidence"
                : stage === "documents"
                  ? `Checks ran in ${run.verification_elapsed_ms ?? "—"} ms · hidden until you reveal them`
                  : `${summary.passed} passed · ${summary.confirmed} confirmed · ${summary.unresolved} unresolved`}
            </small>
          </div>
        </div>
      </section>

      <section className="flow four">
        {STEPS.map((step, index) => (
          <div className={index < current ? "done" : index === current ? "current" : ""} key={step.id}>
            <b>{index < current ? "✓" : index + 1}</b>
            <span>{step.label}</span>
          </div>
        ))}
      </section>

      {humanAction && run && (
        <div
          ref={actionRef}
          className={`stage-anchor ${flash === "webmcp" && focusKind === "action" ? "stage-flash" : ""}`}
        >
          {flash === "webmcp" && focusKind === "action" ? (
            <div className="webmcp-updated">Updated by WebMCP</div>
          ) : null}
          <ActionCenter
          action={humanAction}
          busy={busy}
          onPrimary={() => {
            if (humanAction.id === "confirm") {
              withActor(async () => commitRun(await confirmObservedFact(run.run_id, "human", "ui"))).catch(
                () => undefined,
              );
            } else {
              withActor(async () => commitRun(await recordApproval(run.run_id, "human", "ui"))).catch(
                () => undefined,
              );
            }
          }}
          onSecondary={() => {
            if (humanAction.id === "confirm") {
              const ph = run.findings.find((item) => item.check_id === "ph-range");
              if (!ph) return;
              withActor(async () => commitRun(await selectFinding(run.run_id, ph.finding_id, "human", "ui"))).catch(
                () => undefined,
              );
            } else {
              withActor(async () =>
                commitRun(await openSourceDocument(run.run_id, "product-spec", 1, "human", "ui")),
              ).catch(() => undefined);
            }
          }}
        />
        </div>
      )}

      {!run ? (
        <section className="empty panel">
          <small>Ready</small>
          <h2>Choose a dossier. Judge mode is Harbor Calm Serum.</h2>
          <p>
            Same ProDocuX checks, different planted discrepancies. Cedar Night Cream only fails formula
            revision, so the result cannot be a hardcoded Harbor story.
          </p>
          <div className="card-actions">
            {resumeHint && (
              <button
                className="primary"
                onClick={() =>
                  withActor(async () => commitRun(resumeHint, { syncUrl: true })).catch(() => undefined)
                }
              >
                Resume {resumeHint.product_name}
              </button>
            )}
            {(dossiers.length ? dossiers : [
              { dossier_id: "harbor-calm-serum-2026", product_name: "Harbor Calm Serum", judge_mode: true, blurb: "", planted: ["formula-version", "ph-range"] },
              { dossier_id: "cedar-night-cream-2026", product_name: "Cedar Night Cream", judge_mode: false, blurb: "", planted: ["formula-version"] },
            ]).map((item) => (
              <button
                key={item.dossier_id}
                className={item.judge_mode ? "primary" : ""}
                onClick={() => humanStart(item.dossier_id)}
                disabled={busy}
              >
                {item.judge_mode ? "Judge mode · " : ""}
                {item.product_name}
                {item.planted.length ? ` · ${item.planted.length} planted` : ""}
              </button>
            ))}
          </div>
          <DropSlots
            files={uploads}
            busy={busy}
            onFile={(slot, file) =>
              setUploads((current) => {
                const next = { ...current };
                if (file) next[slot] = file;
                else delete next[slot];
                return next;
              })
            }
            onStart={humanUpload}
          />
          <BenchmarkPanel
            result={benchmark}
            busy={busy}
            onRun={() =>
              withActor(async () => setBenchmark(await runBenchmark())).catch(() => undefined)
            }
          />
        </section>
      ) : (
        <div className="workspace stepper">
          <section
            ref={stageRef}
            className={`panel step-main stage-anchor ${flash === "webmcp" && focusKind === "stage" ? "stage-flash" : ""}`}
          >
            {flash === "webmcp" && focusKind === "stage" ? (
              <div className="webmcp-updated">Updated by WebMCP</div>
            ) : null}
            {stage === "documents" && (
              <>
                <div className="heading">
                  <div>
                    <small>Step 1 · {run.status.replaceAll("_", " ")}</small>
                    <h2>Subject versus references</h2>
                  </div>
                </div>
                {subject && (
                  <article className="subject-card">
                    <small>Subject · you are proofreading this</small>
                    <strong>{LABELS[subject.document_id]}</strong>
                    <span>{subject.filename}</span>
                    <div className="card-actions">
                      <a className="file" download href={sourceFileUrl(run.run_id, subject.document_id)}>
                        Download original
                      </a>
                      <button
                        onClick={() =>
                          withActor(async () =>
                            commitRun(await openSourceDocument(run.run_id, subject.document_id, 1, "human")),
                          ).catch(() => undefined)
                        }
                      >
                        Open facsimile
                      </button>
                    </div>
                    <small>SHA-256 {subject.source_sha256.slice(0, 16)}… · immutable</small>
                  </article>
                )}
                <div className="ref-grid">
                  {refs.map((doc) => (
                    <article key={doc.document_id} className="ref-card">
                      <small>Reference · do not rewrite</small>
                      <strong>{LABELS[doc.document_id]}</strong>
                      <span>{doc.filename}</span>
                      <div className="card-actions">
                        <a className="file" download href={sourceFileUrl(run.run_id, doc.document_id)}>
                          Download original
                        </a>
                        <button
                          onClick={() =>
                            withActor(async () =>
                              commitRun(await openSourceDocument(run.run_id, doc.document_id, 1, "human")),
                            ).catch(() => undefined)
                          }
                        >
                          Open
                        </button>
                      </div>
                    </article>
                  ))}
                </div>
                <DocumentPane
                  document={viewer}
                  page={run.viewer_page}
                  onOpen={async (documentId, page) =>
                    commitRun(await openSourceDocument(run.run_id, documentId, page, "human", "ui"))
                  }
                  compared={
                    closed && viewer?.document_id === "product-spec" && run.reviewed_pages?.length
                      ? { title: "Reviewed artifact", pages: run.reviewed_pages }
                      : undefined
                  }
                />
                <div className="actions">
                  <button
                    className="primary"
                    disabled={busy}
                    onClick={() =>
                      withActor(async () => commitRun(await revealFindings(run.run_id, "human", "ui"))).catch(
                        () => undefined,
                      )
                    }
                  >
                    Run ProDocuX checks
                  </button>
                </div>
              </>
            )}

            {stage === "findings" && (
              <>
                <div className="heading">
                  <div>
                    <small>Step 2 · {run.status.replaceAll("_", " ")}</small>
                    <h2>What ProDocuX reported</h2>
                  </div>
                  <b>{summary.review} need review</b>
                </div>
                <div className="findinglist">
                  {run.findings.map((item) => (
                    <article
                      key={item.finding_id}
                      className={finding?.finding_id === item.finding_id ? "selected" : ""}
                    >
                      <button
                        className="finding-pick"
                        onClick={async () => {
                          try {
                            commitRun(await selectFinding(run.run_id, item.finding_id, "human"));
                            setError(undefined);
                          } catch (reason) {
                            setError(reason instanceof Error ? reason.message : "Could not select finding.");
                          }
                        }}
                      >
                        <i>{item.severity}</i>
                        <span>
                          <strong>{item.title}</strong>
                          <small>
                            {item.finding_id} · {ACTION_COPY[item.action]} · assigned to {item.assignee ?? "human"}
                          </small>
                        </span>
                        <em className={item.status}>{item.status.replaceAll("_", " ")}</em>
                      </button>
                      <div className="assign">
                        <button
                          className={item.assignee === "human" ? "on" : ""}
                          onClick={() =>
                            withActor(async () =>
                              commitRun(await assignFinding(run.run_id, item.finding_id, "human", "human")),
                            ).catch(() => undefined)
                          }
                        >
                          Human
                        </button>
                        <button
                          className={item.assignee === "agent" ? "on" : ""}
                          onClick={() =>
                            withActor(async () =>
                              commitRun(await assignFinding(run.run_id, item.finding_id, "agent", "human")),
                            ).catch(() => undefined)
                          }
                        >
                          Agent
                        </button>
                      </div>
                    </article>
                  ))}
                </div>
                <EvidenceChain run={run} finding={finding} />
              </>
            )}

            {stage === "corrections" && finding && (
              <>
                <div className="heading">
                  <div>
                    <small>Step 3 · {run.status.replaceAll("_", " ")}</small>
                    <h2>{finding.title}</h2>
                  </div>
                  <b>{ACTION_COPY[finding.action]}</b>
                </div>
                <div className="queue">
                  {reviewOpen.map((item) => (
                    <button
                      key={item.finding_id}
                      className={item.finding_id === finding.finding_id ? "on" : ""}
                      onClick={async () =>
                        commitRun(await selectFinding(run.run_id, item.finding_id, "human"))
                      }
                    >
                      {item.finding_id}
                    </button>
                  ))}
                </div>
                <div className="assign">
                  <small>Assigned to {finding.assignee ?? "human"}</small>
                  <button
                    className={finding.assignee === "human" ? "on" : ""}
                    onClick={() =>
                      withActor(async () =>
                        commitRun(await assignFinding(run.run_id, finding.finding_id, "human", "human")),
                      ).catch(() => undefined)
                    }
                  >
                    Human
                  </button>
                  <button
                    className={finding.assignee === "agent" ? "on" : ""}
                    onClick={() =>
                      withActor(async () =>
                        commitRun(await assignFinding(run.run_id, finding.finding_id, "agent", "human")),
                      ).catch(() => undefined)
                    }
                  >
                    Agent
                  </button>
                </div>
                <p>{finding.message}</p>
                {run.draft_correction && finding.action === "correct_subject_field" && (
                  <InlineDiff
                    field={run.draft_correction.field ?? "formula_revision"}
                    before={String(run.draft_correction.current_value ?? finding.actual)}
                    after={run.draft_correction.value}
                  />
                )}
                {!run.draft_correction && finding.action === "correct_subject_field" && (
                  <InlineDiff
                    field="formula_revision"
                    before={String(finding.actual)}
                    after={String(finding.expected)}
                  />
                )}
                <EvidenceChain run={run} finding={finding} />
                <div className="evidence-compare">
                  {[finding.authority_document, finding.observed_document].map((documentId, index) => {
                    const doc = run.documents.find((item) => item.document_id === documentId);
                    const items = run.evidence.filter(
                      (item) =>
                        item.document_id === documentId && finding.evidence_refs.includes(item.evidence_id),
                    );
                    const isSubject = documentId === "product-spec";
                    return (
                      <article
                        key={`${documentId}-${index}`}
                        className={run.viewer_document_id === documentId ? "active-source" : ""}
                      >
                        <small>
                          {isSubject ? "Subject" : "Reference"} · {index === 0 ? "authority" : "compared"}
                        </small>
                        <strong>{LABELS[documentId]}</strong>
                        {items.map((item) => (
                          <div className="evidence-line" key={item.evidence_id}>
                            <b>{item.field_name.replaceAll("_", " ")}</b>
                            <span>{String(item.normalized_value)}</span>
                          </div>
                        ))}
                        <div className="card-actions">
                          <a className="file" download href={sourceFileUrl(run.run_id, documentId)}>
                            Download original
                          </a>
                          <button
                            onClick={async () => {
                              const page = items[0]?.source.page ?? 1;
                              commitRun(await openSourceDocument(run.run_id, documentId, page, "human"));
                            }}
                          >
                            Open {doc?.filename}
                          </button>
                        </div>
                      </article>
                    );
                  })}
                </div>
                <DocumentPane
                  document={viewer}
                  page={run.viewer_page}
                  onOpen={async (documentId, page) =>
                    commitRun(await openSourceDocument(run.run_id, documentId, page, "human", "ui"))
                  }
                  compared={
                    closed && viewer?.document_id === "product-spec" && run.reviewed_pages?.length
                      ? { title: "Reviewed artifact", pages: run.reviewed_pages }
                      : undefined
                  }
                />
                {showCorrection && finding.action === "correct_subject_field" && (
                  <div className="correction-form">
                    <label>
                      Proposed subject value
                      <input value={correctionValue} onChange={(event) => setCorrectionValue(event.target.value)} />
                    </label>
                    <label>
                      Audit reason
                      <textarea
                        value={correctionReason}
                        onChange={(event) => setCorrectionReason(event.target.value)}
                        placeholder="Human-readable reason before commit"
                      />
                    </label>
                    <div className="card-actions">
                      <button
                        disabled={busy}
                        onClick={() =>
                          withActor(async (currentRun) => {
                            if (!currentRun) return;
                            const next = await proposeCorrection(
                              currentRun.run_id,
                              {
                                proposed_value: correctionValue,
                                reason: correctionReason || "Human edited the correction draft.",
                                finding_id: finding.finding_id,
                                field: "formula_revision",
                                document_id: "product-spec",
                              },
                              "human",
                            );
                            commitRun(next);
                          }).catch(() => undefined)
                        }
                      >
                        Save human draft
                      </button>
                      <button
                        disabled={busy}
                        onClick={() =>
                          withActor(async (currentRun) => {
                            if (!currentRun) return;
                            await proposeCorrection(
                              currentRun.run_id,
                              {
                                proposed_value: correctionValue,
                                reason: correctionReason,
                                finding_id: finding.finding_id,
                                field: "formula_revision",
                                document_id: "product-spec",
                              },
                              "human",
                            );
                            const next = await commitCorrection(currentRun.run_id, "human");
                            commitRun(next);
                            setShowCorrection(false);
                          }).catch(() => undefined)
                        }
                      >
                        Approve draft, reverify & replace checkpoint
                      </button>
                      <button
                        disabled={busy}
                        onClick={() =>
                          withActor(async (currentRun) => {
                            if (!currentRun) return;
                            await proposeCorrection(
                              currentRun.run_id,
                              {
                                proposed_value: correctionValue,
                                reason: correctionReason || "Human edited the draft.",
                                finding_id: finding.finding_id,
                              },
                              "human",
                            );
                            const next = await rejectDraft(
                              currentRun.run_id,
                              correctionReason || "Human rejected the agent draft and will rewrite the reason.",
                              "human",
                            );
                            commitRun(next);
                          }).catch(() => undefined)
                        }
                      >
                        Reject agent draft
                      </button>
                    </div>
                  </div>
                )}
                <div className="actions">
                  {finding.action === "correct_subject_field" && finding.status === "needs_review" && (
                    <button onClick={() => setShowCorrection((value) => !value)}>
                      Correct specification reference
                    </button>
                  )}
                  {finding.action === "confirm_ref_observation" && finding.status === "needs_review" && (
                    <button
                      className="primary"
                      disabled={busy || reviewOpen.some((item) => item.action === "correct_subject_field")}
                      onClick={() =>
                        withActor(async (currentRun) => {
                          if (!currentRun) return;
                          commitRun(await confirmObservedFact(currentRun.run_id, "human", "ui"));
                        }).catch(() => undefined)
                      }
                    >
                      {reviewOpen.some((item) => item.action === "correct_subject_field")
                        ? "Resolve the subject correction first"
                        : "Confirm observed deviation"}
                    </button>
                  )}
                  <button
                    disabled={busy}
                    onClick={() =>
                      withActor(async (currentRun) => {
                        if (!currentRun) return;
                        try {
                          commitRun(await rewriteLockedReference(currentRun.run_id, "formula", "human"));
                        } catch (reason) {
                          const recovered =
                            reason && typeof reason === "object" && "run" in reason
                              ? (reason as { run?: Run }).run
                              : undefined;
                          if (recovered) commitRun(recovered);
                          setError(reason instanceof Error ? reason.message : "Policy gate blocked the rewrite.");
                        }
                      }).catch(() => undefined)
                    }
                  >
                    Try rewrite locked formula
                  </button>
                  {!reviewOpen.length && (
                    <button
                      className="primary"
                      disabled={busy}
                      onClick={() =>
                        withActor(async (currentRun) => {
                          if (!currentRun) return;
                          commitRun(await recordApproval(currentRun.run_id, "human"));
                        }).catch(() => undefined)
                      }
                    >
                      Approve checkpoint
                    </button>
                  )}
                </div>
              </>
            )}

            {closed && (
                <div
                  ref={closedRef}
                  className={`completion stage-anchor ${flash === "webmcp" && focusKind === "closed" ? "stage-flash" : ""}`}
                >
                  {flash === "webmcp" && focusKind === "closed" ? (
                    <div className="webmcp-updated">Updated by WebMCP</div>
                  ) : null}
                  <b>✓</b>
                  <h2>Audit closed</h2>
                  <p>
                    Original source files are unchanged. The reviewed subject PDF is a new artifact, not a
                    rewrite of the locked original.
                  </p>
                  {verify && (
                    <p>{verify.ok ? `Bundle verified · status ${verify.status}.` : "Verification failed."}</p>
                  )}
                  {run.reviewed_pages?.length && subject ? (
                    <DocumentPane
                      document={subject}
                      page={1}
                      onOpen={async (documentId, page) =>
                        commitRun(await openSourceDocument(run.run_id, documentId, page, "human", "ui"))
                      }
                      compared={{ title: "Reviewed artifact", pages: run.reviewed_pages }}
                    />
                  ) : null}
                  <div className="card-actions">
                    <a className="file primary-link" download href={subjectFileUrl(run.run_id)}>
                      Download reviewed copy
                    </a>
                    <button
                      onClick={() =>
                        withActor(async () => {
                          const result = await verifyPackage(run.run_id, "human", "ui");
                          setVerify(result);
                          commitRun(await getRun(run.run_id), { syncUrl: false });
                        }).catch(() => undefined)
                      }
                    >
                      Verify bundle
                    </button>
                    <button
                      onClick={() => {
                        const event = run.activities.find((item) => item.viewer_document_id && item.viewer_page);
                        if (!event?.viewer_document_id || !event.viewer_page) return;
                        withActor(async () =>
                          commitRun(
                            await openSourceDocument(
                              run.run_id,
                              event.viewer_document_id as DocumentId,
                              event.viewer_page ?? 1,
                              "human",
                            ),
                          ),
                        ).catch(() => undefined);
                      }}
                    >
                      Replay audit
                    </button>
                    <button className="primary" onClick={() => downloadAudit(run, "human", "ui")}>
                      Download audit JSON
                    </button>
                  </div>
                  {verify && (
                    <ol className="verify-list">
                      {verify.checks.map((item) => (
                        <li key={item.name}>
                          {item.ok ? "✓" : "✗"} {item.name}
                        </li>
                      ))}
                    </ol>
                  )}
                  <div className="ref-grid">
                    {run.documents.map((doc) => (
                      <article key={doc.document_id} className="ref-card">
                        <small>{doc.document_id === "product-spec" ? "Original subject" : "Original reference"}</small>
                        <strong>{LABELS[doc.document_id]}</strong>
                        <a className="file" download href={sourceFileUrl(run.run_id, doc.document_id)}>
                          Download original
                        </a>
                      </article>
                    ))}
                  </div>
                </div>
              )}
            <div className="download-bar">
              <small>Always available</small>
              {run.documents.map((doc) => (
                <a
                  key={doc.document_id}
                  className="file"
                  download
                  href={sourceFileUrl(run.run_id, doc.document_id)}
                >
                  Original {LABELS[doc.document_id]}
                </a>
              ))}
              {closed && run.status !== "rejected" && (
                <a className="file primary-link" download href={subjectFileUrl(run.run_id)}>
                  Reviewed specification
                </a>
              )}
            </div>
          </section>

          <ActivityLog
            caption="This step"
            title="Human vs agent"
            events={stageEvents(run.activities, closed ? "closed" : stage)}
            onReplay={(event) => {
              if (!event.viewer_document_id || !event.viewer_page) return;
              withActor(async () =>
                commitRun(
                  await openSourceDocument(run.run_id, event.viewer_document_id as DocumentId, event.viewer_page ?? 1, "human"),
                ),
              ).catch(() => undefined);
            }}
          />
        </div>
      )}

      <div className="bottom">
        <AgentConsole tools={tools} webmcp={webmcp} busy={busy} onRun={fallbackTool} />
        <ActivityLog
          events={run?.activities ?? []}
          onReplay={(event) => {
            if (!run || !event.viewer_document_id || !event.viewer_page) return;
            withActor(async () =>
              commitRun(
                await openSourceDocument(run.run_id, event.viewer_document_id as DocumentId, event.viewer_page ?? 1, "human"),
              ),
            ).catch(() => undefined);
          }}
        />
      </div>
    </main>
  );
}
