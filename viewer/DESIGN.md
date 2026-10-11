# Design map

Generated from the table that builds the Claude Design canvas **“Cortex UI — Graph-First Redesign”**; do not edit by hand.
Every board is either **built** (a snapshot of the running console, taken with the dev fixture) or **planned**
(designed from the console’s own components, not built, with a banner in the board naming what it needs).

Round 1 (the original top-bar design: Main, Timeline, Recall, Review, Integrity, Inspector, Tokens, Mobile) is kept on the canvas as
the *Top bar* layout option.

## Built

| Board | Source | Notes |
|---|---|---|
| Graph lens, 3D — nothing selected: the inspector shows the workspace | `GraphLens.tsx, Graph3D.tsx, Inspector.tsx (WorkspaceSummary)` | Default view. 3D is the default; the lattice is faint; every cube owns one cell. |
| Graph lens, 3D — an edge selected | `Graph3D.tsx (pickEdge), Inspector.tsx (EdgeInspector)` | Click a line (within 6px). The edge lights, its two ends stay lit, the rest recede; the inspector says what kind of edge it is and links both ends. |
| Graph lens, 3D — a dragged cube is pinned | `Graph3D.tsx (drag, setPinned)` | Drag moves a cube on the plane facing the camera; it lands in the nearest free cell and stays pinned (outlined). Double-click unpins one; “Unpin n” in the bar unpins all. Pins are view-only; nothing is written. |
| Graph lens, 3D — Snap to grid off | `GraphLens.tsx, Graph3D.tsx (setSnap), settings.ts` | Nodes sit where the force layout leaves them; the faint grid stays as a frame of reference. |
| Graph lens, 3D — legend open | `GraphLens.tsx (LegendRow)` | The legend starts closed so it never covers the graph. Each row is also a switch for the same facet the rail has. |
| Graph lens — the selection is hidden by a filter | `model.ts (selectionHidden), GraphLens.tsx` | The inspector still shows the item; the lens says it is not drawn and offers Reset facets. |
| Graph lens, 3D — zoomed far out | `Graph3D.tsx (applyScreenFloor, latticeStride), gridSnap.ts` | Cubes keep a 5px floor, arrowheads and the selected edge keep a minimum size, labels that would overlap are dropped, the grid coarsens by powers of two, and pulling back stops at 2.5x the framing distance. |
| Graph lens, 3D — zoomed in close | `Graph3D.tsx` | Zoom goes toward the pointer and stops at 16 units, so the camera never enters the cloud. Keyboard: arrows orbit, shift+arrows pan, + and − zoom, F frames everything, Esc clears. |
| Graph lens, 2D — a toggle from 3D | `GraphLens.tsx` | Squares on a faint square grid, snapped to cells; same facets, selection and inspector. |
| Graph lens, 2D — Snap to grid off | `GraphLens.tsx (snapNodes)` |  |
| Facet rail — memory source, edge types and predicates | `FacetRail.tsx, model.ts` | Finer switches sit under the edge group they refine; the similarity cut-off runs 0.20–0.99. |
| Graph lens — no WebGL, so 2D, and it says so | `GraphLens.tsx (no3d)` | The 3D choice is kept; the notice explains why 2D is showing. |
| Phone — Graph in 2D | `Phone.tsx, GraphLens.tsx` |  |
| Graph lens — the whole profile (read-only) | `GraphLens.tsx, FacetRail.tsx, Inspector.tsx` | Scope: Primary profile. Writes are hidden and the footer says why. |
| Timeline lens — the same selection, placed in time | `TimelineLens.tsx, model.ts` | A memory is placed at its event time, else when the store recorded it; no-session memories are their own lane. |
| Timeline lens — windowed to 7 days | `ChainRail.tsx, state.tsx` | The window is shared with the Graph lens. |
| Graph lens — a writable agent workspace | `MemoryActions.tsx` | Write actions appear only in a verified, writable workspace. |
| Collapsed rail — Timeline lens | `Shell.tsx (Rail), settings.ts` | Rail collapses to icons; also automatic on narrow windows. |
| Top bar — Graph lens | `Shell.tsx (TopBar)` | Shield’s form of navigation, chosen in Settings → Layout. |
| Top bar — Timeline lens | `Shell.tsx (TopBar)` |  |
| Top bar — Sessions page | `pages/SessionsPage.tsx` |  |
| Sign in — matches Shield | `SignIn.tsx` |  |
| Sign in — create account | `SignIn.tsx` |  |
| Recall — Hybrid, with per-channel ranks | `Recall.tsx` |  |
| Recall — Context block | `Recall.tsx, contextBlock.ts` | POST /api/context/assemble |
| Review — what the workers proposed | `Review.tsx, reviewData.ts` |  |
| Review — accepting says what it will write first | `Review.tsx` |  |
| Inspector — server verifies a memory’s history | `Inspector.tsx, VerifyPanel.tsx, verify.ts` | GET /api/memory/{id}/verify-chain |
| Inspector — request extraction | `MemoryActions.tsx, actions.ts` | POST /api/inference/tasks, POST /api/memory/{id}/extract-structural |
| Inspector — supersede | `MemoryActions.tsx` |  |
| Inspector — forget (two steps) | `MemoryActions.tsx` |  |
| Inspector — files, with download | `Inspector.tsx (FilesTab), download.ts` |  |
| Integrity — server and browser verification | `Integrity.tsx, integrity.ts, merkleVerify.ts` | GET /api/session/{id}/verify-chain beside the browser-recomputed proofs. |
| Integrity — checkpoints | `Integrity.tsx` |  |
| Integrity — links | `Integrity.tsx` |  |
| Memories | `pages/MemoriesPage.tsx` |  |
| Memories — nothing matches | `pages/MemoriesPage.tsx` |  |
| Entities — lookup and path | `pages/EntitiesPage.tsx, entities.ts` |  |
| Sessions | `pages/SessionsPage.tsx, sessions.ts` |  |
| Agents — identity and devices | `pages/AgentsPage.tsx, agents.ts` |  |
| Operations | `pages/OperationsPage.tsx, ops.ts` |  |
| Settings — Layout (rail or top bar) | `pages/SettingsPage.tsx, settings.ts` |  |
| Settings — Inference policy | `pages/settings/InferenceSection.tsx, inferenceForm.ts` |  |
| Settings — Embeddings | `pages/settings/EmbeddingsSection.tsx` |  |
| Settings — Account (a token has no account) | `pages/settings/AccountSection.tsx, account.ts` |  |
| Settings — Developer (an honest self-test failure) | `pages/settings/DeveloperSection.tsx` |  |
| State — the API is unreachable | `state.tsx, Shell.tsx` |  |
| Phone — Graph | `Phone.tsx` |  |
| Phone — Timeline | `Phone.tsx, TimelineLens.tsx` |  |
| Phone — Filters sheet | `Phone.tsx, FacetRail.tsx` |  |
| Phone — Time sheet | `Phone.tsx, ChainRail.tsx` |  |
| Phone — More sheet | `Phone.tsx, nav.ts` |  |
| Phone — inspector sheet | `Phone.tsx, Inspector.tsx` |  |
| Phone — Memories as cards | `pages/MemoriesPage.tsx, console.css` |  |
| Phone — Sessions list, then detail | `pages/SessionsPage.tsx` | Choosing a session opens it; “All sessions” returns. |
| Phone — Entities | `pages/EntitiesPage.tsx` |  |
| Phone — Operations | `pages/OperationsPage.tsx` |  |
| Phone — Agents | `pages/AgentsPage.tsx` |  |
| Phone — Settings | `pages/SettingsPage.tsx` |  |
| Inspector — provenance: who said it, from where, and the export | `Inspector.tsx (ProvenanceTab), VerifyPanel.tsx` | GET /api/memory/{id}/provenance; the export is the server’s own document. |
| Inspector — neighbours in the graph | `Inspector.tsx (NeighborsTab)` |  |
| Inspector — contradictions, and the actions that resolve them | `Inspector.tsx, MemoryActions.tsx` |  |
| Inspector — telemetry attached to the memory | `Inspector.tsx (TelemetryTab)` |  |
| Memories — writing a memory (agent workspace only) | `pages/MemoriesPage.tsx (NewMemory)` | Only a verified writable workspace sees New memory; it says whose memory it will be. |
| Entities — a path between two entities | `pages/EntitiesPage.tsx, entities.ts` | Each hop names the relation that connects it. |
| Sessions — replay, with its completeness stated | `pages/SessionsPage.tsx` | Replay says what it cannot prove: it does not execute tools. |
| Sessions — telemetry summary | `pages/SessionsPage.tsx` |  |
| Sessions — invocation correlations | `pages/SessionsPage.tsx` |  |
| Settings — Top bar chosen (and Snap to grid) | `pages/SettingsPage.tsx, settings.ts` |  |
| Graph lens — a workspace with no memories yet | `GraphLens.tsx` | The inspector still shows the workspace; the lens says why it is empty. |
| Timeline lens — nothing to place | `TimelineLens.tsx` |  |
| Recall — no results | `Recall.tsx` | Says what was searched and what to try, without implying a failure. |
| Tablet (1024) — Graph | `console.css (max-width: 1180px)` | The facet rail becomes a strip above the lens; the rail shell collapses to icons. |
| Tablet (1024) — Timeline | `console.css (max-width: 1180px)` |  |
| Tablet (1024) — Memories | `pages/MemoriesPage.tsx` |  |
| Tablet (820) — Settings | `pages/SettingsPage.tsx` |  |
| Phone — Sign in | `SignIn.tsx` |  |
| Phone — Recall: query on its own row, modes beneath | `Recall.tsx, console.css` |  |
| Phone — Review | `Review.tsx` |  |
| Phone — Graph with the legend open | `GraphLens.tsx` |  |

## Planned — designed, not built

| Board | Lands in | What it needs |
|---|---|---|
| Forgot password | `SignIn.tsx (new mode)` | Needs UI only: POST /api/auth/password-reset/request exists. Unavailable delivery is the 503 state. |
| Choose a new password | `SignIn.tsx (new mode)` | Needs UI only: POST /api/auth/password-reset/confirm exists (400 on an invalid or expired code). |
| Accounts waiting for approval | `pages/settings/AccountSection.tsx` | Needs GET /api/auth/admin/pending (new). POST /api/auth/admin/approve exists. |
| Trust vault lookup | `pages/settings/DeveloperSection.tsx` | Needs GET /api/vault/leaf?leaf_hash= (new); the vault directory is server configuration. |
| Attach a file | `Inspector.tsx (FilesTab)` | Needs POST /api/memory/{id}/attachments (new, upload); 200 MB cap; content-addressed. |
| Verify an integrity link | `Integrity.tsx (Links tab)` | Needs POST /api/memory/{id}/verify-link (new); DAG location is server configuration. |
| Anchor a session root | `Integrity.tsx (Sessions tab)` | Needs POST /api/session/{id}/anchor (new). Outward-facing: confirmed, named, irreversible. |
| Backup and check | `pages/OperationsPage.tsx` | Needs POST /api/backup and /api/backup/reconcile (new); destination is server configuration. |

### Rules the planned designs follow

- **No path comes from the browser.** Backup destination, vault directory, DAG location and the anchor service are server configuration; the browser sends an id or a hash.
- **Outward actions are confirmed and named.** Anchoring says what is sent, to whom, and that it cannot be withdrawn; it is disabled, with the reason, when the profile has no anchor service.
- **Results are worded as what they are.** A backup check shows the copy is complete, not that it will restore elsewhere; a link check is byte lineage only; a vault lookup does not verify memories.
- **A failure is a different thing from “not found”.** Unavailable delivery, an unreadable vault and a missing node each say so.

### Decisions made while filling the gaps

- The scope picker offers **Primary profile · all memories · read only** explicitly. It is never chosen automatically, and it is the only way to see memories with no agent namespace.
- On a phone, Memories rows are cards and Sessions shows the list or the detail, not both.
- Timeline date labels thin themselves so neighbours stay at least 56px apart.


## Graph lens: the spec to implement from

| Behaviour | Rule |
|---|---|
| Default view | 3D. 2D is a toggle in the bar; the choice persists (`graphMode`). Without WebGL the lens shows 2D and says why. |
| Nodes | Cubes (3D) and squares (2D). One node per lattice cell; priority is degree, then id; a node near a boundary keeps its cell (hysteresis 0.62). |
| Snap to grid | A button in the bar and a Settings checkbox (`graphSnap`, default on). Off: nodes stay where the force layout leaves them; the grid stays. |
| Grid | Faint, in both views. 3D: a true lattice through the volume plus a brighter bounding box. 2D: a square grid. Both coarsen by powers of two so lines stay ≥ 14px (3D) or ≥ 16px (2D) apart. |
| Framing | 3D looks along the cloud’s thinnest axis (PCA), with a tilt, at the nearest distance that holds every cube in the real frustum (`framing.ts`). Layout changes re-frame until the person moves the camera; Fit re-arms it. 2D does the same with zoom-to-fit. |
| Resolution | A node is never smaller than 5px (3D) / 3.5px (2D). Arrowheads ≥ 10px, selected-edge bar ≥ 2px. Overlapping labels are dropped, selected and hovered first. Zoom is bounded: near stop 16 units, far stop 2.5× the framing distance. |
| Mouse | Click a node or a line (6px) to select; click empty space to clear; drag empty space to orbit, right-drag to pan, wheel to zoom toward the pointer. Drag a cube to pin it; double-click to unpin. |
| Keyboard | Focus the canvas (Tab): arrows orbit, shift+arrows pan, + and − zoom, F or 0 frame everything, Esc clears the selection. |
| Edges | Relation (accent, arrow subject→object), contradiction (dashed, review colour), similarity (dotted, anchored colour), structure (grey: contains, prompt, response, context, Merkle root). Each group, structure type and relation predicate has a switch. |
| Honesty | Counts say they are for the sample. A hidden selection is announced. Pins and positions are view state; nothing is written to the store. |

## Implementing from this design

The boards are snapshots of the running console in `viewer/`, so each “built” board names the files that produce it.
To work on one: `cd viewer && npm install && npm run dev`, seed with `python scripts/dev_seed_console.py`, and compare against the board.
Gates before a change is done: `npx tsc -b`, `npx oxlint src`, `npx vitest run` (pure logic: `model`, `gridSnap`, `framing`, `graphStyle`, `settings`).
Not covered by checked-in tests: the WebGL engine itself and the browser flows; both were verified by hand in Chromium (software WebGL).
