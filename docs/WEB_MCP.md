# WebMCP implementation

ReviewDesk treats the page as an in-tab MCP server. Tool `execute()` calls
the ReviewDesk API. The API calls published `prodocux` and
`pdx-artifact-engine`. The page never re-implements those checks.

## Discovery

On every run-state change the app aborts the previous registration and
registers the currently enabled tools on `document.modelContext`.

If native WebMCP is missing, the same handlers remain on the in-page Agent
tools list.

## State

`get_workspace_state` returns the current run from the last API payload:
findings (ProDocuX), checkpoint id (PDX), open document, and enabled tools.

## Human in the loop

- `propose_correction` stores a visible draft.
- `commit_correction` is disabled until that draft exists, then ProDocuX
  re-verifies and PDX replaces the checkpoint.
- `confirm_observed_fact` is disabled until the formula revision is resolved.
- The WebMCP tool surface cannot invoke human-only approval. The human uses
  the UI Approve action. This is not cryptographically unforgeable human
  presence.
- Source document digests never change.
