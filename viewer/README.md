# xibalba-cortex viewer

Standalone graph visualization and local operator surface for `xibalba-cortex`. The viewer opens on an authenticated operations overview and exposes graph, timeline, lexical Recall, inference task, provenance, PARA review, Integrity, and connector views. It is a local prototype and is not a production deployment.

The local API includes both read routes and bounded mutating `POST` routes for recording exchanges, creating propositions, linking entities, lifecycle changes, inference claims/completions, and PARA decisions. Bind it to loopback and set an explicit allowed origin when running the viewer. Every route except `/healthz`, `/readyz`, and `/metrics` requires the same bearer-token auth as the streamable-HTTP MCP transport -- there is no unauthenticated fallback.

## Run

For local development, `npm run dev` now creates a dedicated `viewer-local-dev` operator token
on first boot, stores its raw value at `<CORTEX_HOME>/.viewer-dev.token` with mode `0600`, and
uses a loopback-only Vite proxy to inject it into API requests. The browser receives only a
non-secret local-development marker. Delete the token file and revoke its token record to rotate
it. This automation is never included in a production build.

For a production build or an explicitly authenticated operator flow:

1. Issue a token for the viewer (once per profile home):
   ```bash
   uv run xibalba-cortex-ingest-tokens --home ~/.hermes/xibalba-cortex issue --label viewer --role reader
   ```
   Use `--role writer` instead if you'll use the viewer's write actions (e.g. "Build Exchanges").
   Save the printed token -- it's shown once.
2. Start the local operator API from the `xibalba-cortex` project root:
   ```bash
   uv run python -m xibalba_cortex.local_api \
     --home ~/.hermes/xibalba-cortex \
     --host 127.0.0.1 \
     --allowed-origin http://localhost:5190
   ```
3. In this directory, start the viewer:
   ```bash
   npm install
   npm run dev
   ```
4. Open the production viewer, enter the local API endpoint and token from step 1, and connect. The viewer
   validates both against `/api/status` before opening the workspace. The endpoint and token
   stay in the current browser tab via `sessionStorage`; neither is embedded in the bundle.
   The viewer opens on `http://localhost:5190` (a fixed, non-default port that avoids the
   Dockerized `integrity-dashboard` instances on 5173/5174).

`VITE_LOCAL_API_URL` sets the initial production endpoint value. For local development,
`CORTEX_HOME`, `CORTEX_DEV_TOKEN_FILE`, and `CORTEX_LOCAL_API_URL` configure the profile,
protected token file, and Vite proxy target respectively.

## Try it on a fixture

`scripts/dev_seed_console.py` (repo root) builds a scratch profile through the real store API, so
every screen has something genuine to show: backdated sessions, entities and relations, a
supersession, a contradiction, a forgotten memory, a writable agent workspace with a review queue,
and a proposal belonging to a different workspace that the console must hide. It refuses to touch
an existing or default profile.

```bash
uv run python scripts/dev_seed_console.py --home /tmp/cortex-dev
uv run python -m xibalba_cortex.local_api --home /tmp/cortex-dev
cd viewer && CORTEX_HOME=/tmp/cortex-dev npm run dev     # then "Connect to local Cortex"
```

## Console (default UI)

The default screen is the redesigned **Cortex console** (`src/console/`): two lenses, Graph and
Timeline, over one shared state (selection, facets and time window survive a lens switch), a
facet rail, a single inspector, a chain rail that windows both lenses, and Recall (`Ctrl/Cmd+K`).
It is dark-only and shares the Xibalba Console design language with Shield (graphite surface,
registration crosses on every window, Barlow / Barlow Condensed / JetBrains Mono) with Cortex's
lavender accent.

Honesty rules the console follows:

- A node is placed in time only from a timestamp the API really returns; everything else is
  counted as "untimed" and never hidden by the time window.
- Session Merkle root validity is shown as *server-reported*. Retrieval inclusion proofs are the
  one thing verified in the browser (`merkleVerify.ts`).
- Writes (supersede, link entities, mark contradiction, forget) live in the memory inspector's
  footer and are offered only in a verified, writable `{store, agent}` workspace; anywhere else
  the footer says the workspace is read-only. Nothing is optimistic: the UI changes after the
  server confirms and the graph is reloaded. Forget is a two-step confirm, and contradictions
  are recorded, never resolved. The Review drawer lists extraction proposals, PARA classifications
  and inference tasks: accepting a proposal is a two-step action that first says what it will
  write, the task tab is read-only, and items whose source memory is not in the selected
  workspace are hidden and counted (the queue endpoints take no agent scope, so the console
  matches them against the workspace's own memory listing). The Integrity drawer verifies in the browser what the browser can:
  every exchange's inclusion proof for a session (and the batch root recomputed from all leaves),
  and each projection checkpoint's root recomputed from its own leaf hashes (`merkleVerify.ts`,
  pinned to Python-built vectors). It labels anything the server computed as "server reports",
  states what a Merkle check does not prove, and gates checkpoint, reconcile and rebuild on a
  writable workspace and labels them store-wide.

Navigation is a left rail by default; Settings (in the rail) switches it to a top bar and can collapse
the rail to icons. Both layouts, and the phone tab bar, render one destination registry (`nav.ts`), so
a surface added there appears everywhere. A destination is listed only once its surface exists.

On a phone (<= 760px) the same components are laid out differently: the lens fills the screen,
a tab bar switches Graph / Timeline / Recall / Review, and More lists every other destination, Filters and Time open as bottom
sheets (their buttons show how many switches are off their defaults), and the inspector rises as a
sheet when something is selected. Selection and filters survive crossing the breakpoint.

The previous viewer is still available at `?ui=legacy` (link in the console status bar).

```bash
npm test      # vitest: pure model logic (time resolution, facets, histogram, lanes)
```

## Graph rendering behavior

The 3D Graph view is an interactive overview, not a full-store renderer. To keep session selection and navigation responsive, the canvas requests one sampled memory page and renders the 20 newest sessions, always including the selected session. Recall, memory inspection, session Timeline, Replay, and Integrity views continue to query the complete API projections.

When a session changes, the viewer loads exchanges, replay, and the Merkle root together before replacing the graph's session overlay. This avoids rebuilding the large Three.js scene against partially loaded state.

For a quick local verification:

```bash
npm run build
npm run lint
```

The build must pass and lint must report zero errors. The repository may still report non-blocking bundle-size or pre-existing warning diagnostics.

### Browser auth smoke test

With Cortex and Shield Vite servers running, execute `CORTEX_UI_URL=http://127.0.0.1:4180 SHIELD_UI_URL=http://127.0.0.1:4176 npm run test:ui` to validate landing-to-auth navigation, mobile layout, unavailable-backend UX, and (when credentials are supplied) refresh, Settings, avatar, sign-out, and session recovery for both products. The script uses Playwright and does not create accounts by default. To validate real account login, provide `CORTEX_API_URL`, `CORTEX_EMAIL`, `CORTEX_PASSWORD` and/or the corresponding `SHIELD_*` variables. Opt into sign-up coverage with `CORTEX_SIGNUP_EMAIL`, `CORTEX_SIGNUP_PASSWORD` (and `SHIELD_SIGNUP_TENANT` for Shield).
