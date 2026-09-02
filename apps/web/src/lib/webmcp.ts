import { STALE_TOOL_MESSAGE, availableTools, snapshot } from "./api";
import type { Run, ToolSpec, WorkspaceSnapshot } from "./types";

type ExecuteFn = (input: Record<string, unknown>) => Promise<unknown> | unknown;

export interface ModelContextLike {
  registerTool: (
    tool: {
      name: string;
      description: string;
      inputSchema?: Record<string, unknown>;
      execute: (input: Record<string, unknown>) => Promise<unknown> | unknown;
    },
    options?: { signal?: AbortSignal },
  ) => Promise<void> | void;
}

export function getModelContext(): ModelContextLike | null {
  const fromDocument =
    typeof document !== "undefined"
      ? (document as Document & { modelContext?: ModelContextLike }).modelContext
      : undefined;
  const fromNavigator =
    typeof navigator !== "undefined"
      ? (navigator as Navigator & { modelContext?: ModelContextLike }).modelContext
      : undefined;
  return fromDocument ?? fromNavigator ?? null;
}

function toolResult(payload: unknown) {
  const text =
    typeof payload === "string" ? payload : JSON.stringify(payload, null, 2);
  return {
    content: [{ type: "text", text }],
  };
}

export function wrapExecute(
  name: string,
  execute: ExecuteFn,
  isEnabled?: () => boolean,
): (input: Record<string, unknown>) => Promise<unknown> {
  return async (input) => {
    try {
      if (isEnabled && !isEnabled()) {
        return toolResult({
          ok: false,
          tool: name,
          error: STALE_TOOL_MESSAGE,
          tools_changed: true,
        });
      }
      const result = await execute(input ?? {});
      return toolResult(result);
    } catch (error) {
      const message = error instanceof Error ? error.message : "Tool failed.";
      const stale = message.includes("Policy gate") ? false : message.toLowerCase().includes("refresh");
      return toolResult({
        ok: false,
        tool: name,
        error: message,
        tools_changed: stale,
        refresh_hint: stale ? STALE_TOOL_MESSAGE : undefined,
      });
    }
  };
}

function signature(tool: ToolSpec): string {
  return JSON.stringify({
    name: tool.name,
    description: tool.description,
    inputSchema: tool.inputSchema,
  });
}

export class ToolHost {
  private signatures = new Map<string, string>();
  private controllers = new Map<string, AbortController>();
  private enabled = new Set<string>();

  enabledNames(): string[] {
    return [...this.enabled];
  }

  async sync(
    tools: ToolSpec[],
    handlers: Record<string, ExecuteFn>,
  ): Promise<boolean> {
    const context = getModelContext();
    const enabledTools = tools.filter((item) => item.enabled);
    this.enabled = new Set(enabledTools.map((item) => item.name));
    if (!context) {
      return false;
    }
    const enabledNames = new Set(enabledTools.map((item) => item.name));
    for (const [name, controller] of this.controllers) {
      if (!enabledNames.has(name)) {
        controller.abort();
        this.controllers.delete(name);
        this.signatures.delete(name);
      }
    }
    for (const tool of enabledTools) {
      const next = signature(tool);
      if (this.signatures.get(tool.name) === next) {
        continue;
      }
      this.controllers.get(tool.name)?.abort();
      const controller = new AbortController();
      this.controllers.set(tool.name, controller);
      this.signatures.set(tool.name, next);
      const handler = handlers[tool.name];
      if (!handler) {
        continue;
      }
      await context.registerTool(
        {
          name: tool.name,
          description: tool.description,
          inputSchema: tool.inputSchema,
          execute: wrapExecute(tool.name, handler, () => this.enabled.has(tool.name)),
        },
        { signal: controller.signal },
      );
    }
    return true;
  }
}

export async function registerTools(
  tools: ToolSpec[],
  handlers: Record<string, ExecuteFn>,
  signal: AbortSignal,
  host?: ToolHost,
): Promise<boolean> {
  if (host) {
    return host.sync(tools, handlers);
  }
  const context = getModelContext();
  if (!context) {
    return false;
  }
  for (const tool of tools.filter((item) => item.enabled)) {
    const handler = handlers[tool.name];
    if (!handler) {
      continue;
    }
    await context.registerTool(
      {
        name: tool.name,
        description: tool.description,
        inputSchema: tool.inputSchema,
        execute: wrapExecute(tool.name, handler),
      },
      { signal },
    );
  }
  return true;
}

export function describeCatalog(run: Run | null, webmcp: boolean): WorkspaceSnapshot {
  return snapshot(run, webmcp);
}

export { availableTools, STALE_TOOL_MESSAGE };
