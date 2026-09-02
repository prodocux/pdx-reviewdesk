const API = (import.meta.env.VITE_API_URL as string | undefined) ?? "";
const ACTIVE_KEY = "reviewdesk.active_run_id";
const CLOSED_BOUNCE_KEY = "reviewdesk.bounce_closed_run";
export const RUN_CHANNEL = "reviewdesk-run";

type Capabilities = { human: string; agent: string };

let capabilities: Capabilities | null = null;
let sessionReady: Promise<void> | null = null;

export function invocationHeaders(channel: "ui" | "webmcp" | "backend"): Record<string, string> {
  const token =
    channel === "webmcp" ? capabilities?.agent : capabilities?.human;
  return {
    "X-ReviewDesk-Invocation": channel === "webmcp" ? "webmcp" : "ui",
    "X-ReviewDesk-Capability": token ?? "",
  };
}

export async function ensureSession(): Promise<void> {
  if (!sessionReady) {
    sessionReady = fetch(`${API}/v1/session`, { credentials: "include" })
      .then(async (response) => {
        if (!response.ok) {
          throw new Error("Could not open a ReviewDesk session.");
        }
        const body = (await response.json()) as {
          human_capability?: string;
          agent_capability?: string;
        };
        if (!body.human_capability || !body.agent_capability) {
          throw new Error("Could not open a ReviewDesk session.");
        }
        capabilities = { human: body.human_capability, agent: body.agent_capability };
      })
      .catch((error) => {
        sessionReady = null;
        throw error;
      });
  }
  return sessionReady;
}

export function pathRunId(): string | null {
  const match = window.location.pathname.match(/^\/runs\/([^/]+)/);
  return match?.[1] ?? null;
}

export function rememberedRunId(): string | null {
  try {
    return localStorage.getItem(ACTIVE_KEY);
  } catch {
    return null;
  }
}

export function rememberRun(runId: string | null): void {
  try {
    if (runId) localStorage.setItem(ACTIVE_KEY, runId);
    else localStorage.removeItem(ACTIVE_KEY);
  } catch {
    /* private mode */
  }
}

export function runPath(runId: string): string {
  return `/runs/${runId}`;
}

export function markClosedRun(runId: string): void {
  try {
    sessionStorage.setItem(CLOSED_BOUNCE_KEY, runId);
  } catch {
    /* private mode */
  }
}

export function clearClosedBounce(): void {
  try {
    sessionStorage.removeItem(CLOSED_BOUNCE_KEY);
  } catch {
    /* private mode */
  }
}

export function shouldBounceClosedRun(runId: string | null): boolean {
  if (!runId) return false;
  try {
    return sessionStorage.getItem(CLOSED_BOUNCE_KEY) === runId;
  } catch {
    return false;
  }
}

export function goHome(): void {
  if (window.location.pathname === "/") return;
  window.location.replace("/");
}
