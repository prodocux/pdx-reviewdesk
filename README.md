# PDX ReviewDesk

Live demo: [pdx-reviewdesk.onrender.com](https://pdx-reviewdesk.onrender.com/)
Public repository: [github.com/prodocux/pdx-reviewdesk](https://github.com/prodocux/pdx-reviewdesk)

A WebMCP desk where humans and agents share a regulated dossier. This
submission is the **review** slice: ProDocuX verifies evidence, PDX Artifact
Engine binds checkpoints and approvals to digests, and the page never
re-implements those checks. Next, the same desk becomes **co-authoring**—
agents fill documents from named files or search results, the human reviews
in the tab, then the packet exports in the formats you ask for.

Consumes published
[`prodocux==0.3.0rc4`](https://pypi.org/project/prodocux/0.3.0rc4/) and
[`pdx-artifact-engine==0.3.0a4`](https://pypi.org/project/pdx-artifact-engine/0.3.0a4/).

This is not PDX EvidenceGate. EvidenceGate is a Nutrient DWS product on the
same upstream packages. ReviewDesk is the WebMCP consumer of those packages.

License: **Apache License 2.0**. See [LICENSE](LICENSE).

## What people and agents do today

The page walks **Documents → Findings → Corrections → Close**.

1. Start the Harbor Calm Serum demo (product specification as subject; formula
   and CoA as references).
2. ProDocuX flags mismatches (formula revision, pH range).
3. The agent focuses a finding, opens the governing PDF, and proposes a
   correction to **normalized evidence** only.
4. Commit re-verifies with ProDocuX and replaces the PDX checkpoint. Source
   PDF bytes and digests never change.
5. The human confirms an observed fact or uses the UI **Approve** action.
   The WebMCP tool surface cannot invoke human-only approval.

## Why WebMCP

Useful actions are state-dependent: open a source, propose a correction,
commit it, confirm an observed fact. The agent should call those tools
instead of scraping the UI. `execute()` hits the same FastAPI routes the
page uses, so the workspace updates in place.

Registration lives in [`apps/web/src/lib/webmcp.ts`](apps/web/src/lib/webmcp.ts):

```ts
await context.registerTool(
  {
    name: tool.name,
    description: tool.description,
    inputSchema: tool.inputSchema,
    execute: wrapExecute(tool.name, handler),
  },
  { signal },
);
```

Enabled tools include `start_demo_audit`, `get_workspace_state`,
`select_finding`, `open_source_document`, `propose_correction`,
`commit_correction`, and `confirm_observed_fact`. Human-only approval is
not registered.

## Judge / WebMCP test

No login. Open [the hosted app](https://pdx-reviewdesk.onrender.com/)
(or `http://localhost:5173` locally).

1. ChatGPT desktop in-app browser, or Chrome 149+ with
   `chrome://flags/#enable-webmcp-testing` enabled, then restart Chrome.
2. Ask: “Start the Harbor Calm Serum demo and tell me what ProDocuX flagged.”
3. Ask: “Open the formula-version finding and show the approved formula.”
4. Ask: “Propose revision 3, then commit.” Confirm the source PDF digest
   does not change.
5. Ask: “Continue.” The agent should request human confirmation itself.
   The human uses **Confirm observation**, then **Approve**. There is no
   WebMCP tool that confirms a human-assigned observation or records
   approval.

A timed walkthrough is in [docs/DEMO_SCRIPT.md](docs/DEMO_SCRIPT.md).

`GET /health` must report `prodocux: 0.3.0rc4` and
`pdx_artifact_engine: 0.3.0a4`. Free Render may take about a minute to
wake if the service has spun down.

## What's next

Review of existing PDFs is not the end state. The desk should be where
humans and agents **write the packet together**:

1. The human names files or allows search.
2. The agent fills the important documents on the same page.
3. The human reviews, corrects, and accepts in the tab.
4. ReviewDesk exports the agreed dossier in the requested formats.

Today’s WebMCP review tools remain as the acceptance pass. Verification and
digest-bound artifacts stay on published ProDocuX and PDX Artifact Engine.

## Quick start

Python 3.12+ and Node.js 22+. Install wheels from PyPI, not from local
ProDocuX source trees.

### Windows (PowerShell)

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m pytest -q
.\scripts\run_api.ps1
```

Second terminal:

```powershell
cd apps\web
npm ci
npm test
npm run dev
```

### macOS / Linux

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e ".[dev]"
.venv/bin/python -m pytest -q
.venv/bin/python -m uvicorn reviewdesk_api.main:app --reload --host 127.0.0.1 --port 8000
```

Second terminal:

```bash
cd apps/web
npm ci
npm test
npm run dev
```

Open `http://localhost:5173`. Vite proxies `/v1` and `/health` to the API.

## Environment

| Variable | Default | Role |
|---|---|---|
| `REVIEWDESK_RUNS_DIR` | `./runs` | Session-scoped run files |
| `REVIEWDESK_ALLOWED_ORIGINS` | Vite localhost origins | CORS allow-list (credentials) |
| `PRODOCUX_V1_BASE_URL` | unset | Optional Kernel HTTP verifier; package still comes from PyPI |
| `VITE_API_URL` | empty (same origin / Vite proxy) | Frontend API prefix |
| `PORT` | `8000` locally; set by the host in production | Uvicorn bind port |

Copy [`apps/web/.env.example`](apps/web/.env.example) only if the SPA is
hosted on a different origin than the API.

## Tests

```bash
.venv/bin/python -m pytest -q          # Windows: .\.venv\Scripts\python.exe -m pytest -q
cd apps/web && npm ci && npm test && npm run build
```

GitHub Actions [`.github/workflows/ci.yml`](.github/workflows/ci.yml)
installs the PyPI pins and asserts `site-packages` origins.

## Deploy

Live: [https://pdx-reviewdesk.onrender.com/](https://pdx-reviewdesk.onrender.com/)

One Python process serves `/v1`, `/health`, and the built SPA. Do not ship
a static-only Vercel site: the products being promoted are Python packages.

This repo includes a Render Blueprint ([render.yaml](render.yaml)) that
builds the Docker image ([Dockerfile](Dockerfile)) on the **Free** compute
plan. No payment method is required. Free web services cannot attach a
disk, so run files live on the ephemeral filesystem and are lost on
spin-down (about 15 minutes idle). That is enough for judging.

In the [Render Dashboard](https://dashboard.render.com): **New → Blueprint**
→ connect `prodocux/pdx-reviewdesk`. Or **New → Web Service**, select the
same repo, Docker runtime, and the Free instance type (do not add a disk).

Same-origin SPA + API, so CORS usually does not need a public origin list.

### Local production-like serve

```bash
cd apps/web && npm ci && npm run build
python -m pip install -e .
python -m uvicorn reviewdesk_api.main:app --host 0.0.0.0 --port 8000
```

`pypdf` and FastAPI/Starlette versions are inherited from
`prodocux==0.3.0rc4`. ReviewDesk pins `python-multipart==0.0.22` itself.

## Layout

```
apps/api/                 FastAPI (`reviewdesk_api`)
apps/web/                 Vite + React + WebMCP registration
packages/reviewdesk_*     Domain, ProDocuX adapter, PDX adapter
tests/                    Pytest
Dockerfile / render.yaml  Hosted image + Render Blueprint
LICENSE                   Apache-2.0
```

## Boundary

- `pyproject.toml` pins `prodocux==0.3.0rc4` and `pdx-artifact-engine==0.3.0a4`.
- CI installs those pins from PyPI and asserts `site-packages` origins.
- Mutating API calls require the page session cookie plus a capability
  header. JSON `actor` / `channel` are ignored for authorization.
- The frontend does not evaluate formula revision or pH itself.
- The WebMCP tool surface cannot invoke human-only approval. That is a
  channel boundary, not cryptographic proof that a person pressed the button.

See [PRIOR_ART.md](PRIOR_ART.md) and [docs/WEB_MCP.md](docs/WEB_MCP.md).
