import { afterEach, describe, expect, it, vi } from "vitest";
import { getModelContext, registerTools, ToolHost, wrapExecute } from "../lib/webmcp";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("webmcp helper", () => {
  it("prefers document.modelContext", () => {
    const registerTool = vi.fn();
    vi.stubGlobal("document", { modelContext: { registerTool } });
    expect(getModelContext()?.registerTool).toBe(registerTool);
  });

  it("wraps tool failures as structured content", async () => {
    const execute = wrapExecute("record_approval", () => {
      throw new Error("Approval is blocked while findings still need review.");
    });
    const result = (await execute({})) as { content: Array<{ text: string }> };
    expect(result.content[0].text).toContain("still need review");
  });

  it("registers only enabled tools and aborts with the provided signal", async () => {
    const registerTool = vi.fn().mockResolvedValue(undefined);
    vi.stubGlobal("document", { modelContext: { registerTool } });
    const controller = new AbortController();
    const ok = await registerTools(
      [
        {
          name: "get_workspace_state",
          description: "state",
          inputSchema: { type: "object", properties: {} },
          enabled: true,
        },
        {
          name: "record_approval",
          description: "approve",
          inputSchema: { type: "object", properties: {} },
          enabled: false,
        },
      ],
      {
        get_workspace_state: () => ({ ok: true }),
        record_approval: () => ({ ok: true }),
      },
      controller.signal,
    );
    expect(ok).toBe(true);
    expect(registerTool).toHaveBeenCalledTimes(1);
    expect(registerTool.mock.calls[0][0].name).toBe("get_workspace_state");
    expect(registerTool.mock.calls[0][1].signal).toBe(controller.signal);
  });

  it("keeps stable tools registered across catalog updates", async () => {
    const registerTool = vi.fn().mockResolvedValue(undefined);
    vi.stubGlobal("document", { modelContext: { registerTool } });
    const host = new ToolHost();
    const handlers = {
      get_workspace_state: () => ({ ok: true }),
      start_demo_audit: () => ({ ok: true }),
      run_checks: () => ({ ok: true }),
      open_source_document: () => ({ ok: true }),
    };
    const catalog = (enabled: string[]) => [
      {
        name: "get_workspace_state",
        description: "state",
        inputSchema: { type: "object", properties: {} },
        enabled: true,
        stable: true,
      },
      {
        name: "open_source_document",
        description: "open",
        inputSchema: { type: "object", properties: {} },
        enabled: true,
        stable: true,
      },
      {
        name: "run_checks",
        description: "checks",
        inputSchema: { type: "object", properties: {} },
        enabled: enabled.includes("run_checks"),
      },
    ];
    await host.sync(catalog(["run_checks", "open_source_document", "get_workspace_state"]), handlers);
    await host.sync(catalog(["open_source_document", "get_workspace_state"]), handlers);
    const names = registerTool.mock.calls.map((item: Array<{ name: string }>) => item[0].name);
    expect(names.filter((name: string) => name === "open_source_document")).toHaveLength(1);
    expect(names.filter((name: string) => name === "run_checks")).toHaveLength(1);

    const staleExecute = wrapExecute("run_checks", () => ({ ok: true }), () => false);
    const stale = (await staleExecute({})) as { content: Array<{ text: string }> };
    expect(stale.content[0].text).toContain("Workspace changed; refresh available tools and retry");
  });

  it("lets a naive agent keep calling run_checks after open_source_document", async () => {
    const registerTool = vi.fn().mockResolvedValue(undefined);
    vi.stubGlobal("document", { modelContext: { registerTool } });
    const host = new ToolHost();
    let calls = 0;
    const handlers = {
      get_workspace_state: () => ({ ok: true, tools_changed: false }),
      open_source_document: () => ({ ok: true, viewer_page: 2, tools_changed: false }),
      run_checks: () => {
        calls += 1;
        return { ok: true, status: "findings_ready", tools_changed: true };
      },
    };
    const documentsCatalog = [
      {
        name: "get_workspace_state",
        description: "state",
        inputSchema: { type: "object", properties: {} },
        enabled: true,
        stable: true,
      },
      {
        name: "open_source_document",
        description: "open",
        inputSchema: { type: "object", properties: {} },
        enabled: true,
        stable: true,
      },
      {
        name: "run_checks",
        description: "checks",
        inputSchema: { type: "object", properties: {} },
        enabled: true,
      },
    ];
    await host.sync(documentsCatalog, handlers);
    await host.sync(documentsCatalog, handlers);
    const openSource = registerTool.mock.calls.find((item: Array<{ name: string }>) => item[0].name === "open_source_document");
    const runChecks = registerTool.mock.calls.find((item: Array<{ name: string }>) => item[0].name === "run_checks");
    expect(openSource).toBeDefined();
    expect(runChecks).toBeDefined();
    const opened = (await openSource![0].execute({ document_id: "coa", page: 1 })) as {
      content: Array<{ text: string }>;
    };
    await host.sync(documentsCatalog, handlers);
    const checked = (await runChecks![0].execute({})) as { content: Array<{ text: string }> };
    expect(calls).toBe(1);
    expect(opened.content[0].text).toContain("tools_changed");
    expect(opened.content[0].text).toContain("false");
    expect(checked.content[0].text).toContain("findings_ready");
    expect(checked.content[0].text).not.toContain("Workspace changed");
    expect(registerTool.mock.calls.filter((item: Array<{ name: string }>) => item[0].name === "run_checks")).toHaveLength(1);
    expect(registerTool.mock.calls.filter((item: Array<{ name: string }>) => item[0].name === "open_source_document")).toHaveLength(1);
  });
});
