# Demo script (under 3 minutes)

## 0:00–0:20 — Problem

A specification, an approved formula, and a certificate can disagree.
ReviewDesk does not guess the UI. It registers WebMCP tools that call
published ProDocuX and PDX Artifact Engine.

Show `/health`: `prodocux 0.3.0rc4` and `pdx-artifact-engine 0.3.0a4`.

## 0:20–0:45 — Start

Ask the agent: “Start the Harbor Calm Serum demo and tell me what ProDocuX flagged.”

`start_demo_audit` then `get_workspace_state`. Two review items. PDX checkpoint
id is visible. Source digests are locked.

## 0:45–1:20 — Authority

Ask: “Open the formula-version finding and show the approved formula.”

`select_finding` and `open_source_document`. Revision 3 beside specification 2.

## 1:20–1:50 — Correction

Ask: “Propose revision 3, then commit.”

`propose_correction` fills the draft. `commit_correction` reruns ProDocuX and
replaces the PDX checkpoint. Source PDF digest unchanged.

## 1:50–2:20 — Observed fact

Ask: “Continue.”

The agent should call `request_human_confirmation` on its own. Do not tell
it to ask the human. The human then uses Confirm observation. ProDocuX
still reports the range failure. ReviewDesk records that confirmation.
Then the human Approves.

## 2:20–2:45 — Close

The human uses the UI Approve action. The WebMCP tool surface cannot invoke
human-only approval. Export the audit JSON (no source bytes).

To start another pass, the agent should call `new_review` or
`start_demo_audit`. Reloading the closed run URL restores the same audit.
