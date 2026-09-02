import type { ToolSpec } from "../lib/types";

export function AgentConsole({
  tools,
  webmcp,
  busy,
  onRun,
}: {
  tools: ToolSpec[];
  webmcp: boolean;
  busy: boolean;
  onRun: (name: string) => void;
}) {
  const enabled = tools.filter((tool) => tool.enabled);
  return (
    <aside className="panel console">
      <div className="heading">
        <div>
          <small>WebMCP surface</small>
          <h2>Agent tools</h2>
        </div>
        <b className={webmcp ? "live" : ""}>{webmcp ? "registered" : "page fallback"}</b>
      </div>
      <p>
        {webmcp
          ? "This tab registered tools on document.modelContext. ChatGPT’s in-app browser or Chrome with WebMCP can call them while you watch."
          : "WebMCP is not enabled in this browser. The same tools still run in-page so a human and an agent share one desk."}
      </p>
      <ul>
        {enabled.map((tool) => (
          <li key={tool.name}>
            <button disabled={busy} onClick={() => onRun(tool.name)}>
              {tool.name}
            </button>
            <span>{tool.description}</span>
          </li>
        ))}
      </ul>
    </aside>
  );
}
