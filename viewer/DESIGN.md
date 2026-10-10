# Design map

Generated from the table that builds the Claude Design canvas **“Cortex UI — Graph-First Redesign”**; do not edit by hand.
Every board is either **built** (a snapshot of the running console, taken with the dev fixture) or **planned**
(designed from the console’s own components, not built, with a banner in the board naming what it needs).

Round 1 (the original top-bar design: Main, Timeline, Recall, Review, Integrity, Inspector, Tokens, Mobile) is kept on the canvas as
the *Top bar* layout option.

## Built

| Board | Source | Notes |
|---|---|---|
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
