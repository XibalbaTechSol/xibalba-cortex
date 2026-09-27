# Agent memory, sessions, and inference workspace

**Status:** implementation proposal grounded in the current Cortex code and a local rendered QA journey. This note describes the observed system first; it does not claim that every proposed backend capability already exists.

## Findings and evidence class

| Finding | Evidence class | Source |
| --- | --- | --- |
| A profile has its own configured storage home and profile ID. SQLite stores persist a profile identity; reopening a database under a different profile is rejected. | Confirmed by source and exercised when the temporary QA profile was first opened with the wrong profile ID. | `src/xibalba_cortex/config.py:149-180`; `src/xibalba_cortex/store.py:768-775,1060-1074` |
| Optional profile homes are opened as separate read-only `GraphStore` instances. The API selects one store for each agent-scoped read; an ambiguous agent present in more than one mounted store requires `store_id`. | Confirmed by source; store-pinning and ambiguity behavior covered by `tests/test_local_api.py::test_workspace_store_scope_pins_memory_session_and_inference_reads`. | `src/xibalba_cortex/local_api.py:429-475,1537-1554` |
| A memory points to a source record and carries content hash, lifecycle status, validity interval, supersession link, derivation family, and creation time. FTS5 indexes content. | Confirmed by schema. | `src/xibalba_cortex/store.py:242-269`; lifecycle methods at `5874-5918,6036-6087` |
| Sessions belong to an optional agent ID and have retention tier/start/end/summary fields. Exchanges sequence within sessions and reference memories through a many-to-many role join; tool-call and context-memory joins are separate. | Confirmed by schema. | `src/xibalba_cortex/store.py:346-355,3991-4068,415-457` |
| Generic agent-turn ingestion stores prompt and response as source-linked memories, starts the session, and can attach tool-call OTel events to the exchange. | Confirmed by source; rendered in the QA replay journey with prompt, response, and tool call. | `src/xibalba_cortex/store.py:4677-4800` |
| Inference tasks persist typed subject/input/output, status, lease/owner/token, attempts, retry time, failure class, dead-letter reason, error, and timestamps. Context-bundle tasks have no durable agent ownership join and are omitted from agent-scoped task lists. | Confirmed by schema and query implementation. | `src/xibalba_cortex/store.py:459-490,4959-5006` |
| Current list endpoints return bounded pages, not full-store totals. `sessions/page` reports `count_status: page_loaded`; unpaired workspace entries report memory/session counts as uncounted. | Confirmed by source and observed in browser QA. | `src/xibalba_cortex/local_api.py:723-780,841-859`; `src/xibalba_cortex/store.py:2300-2334` |
| Inference polling returns one status-filtered page. It includes tasks with future `retry_after`, so a scheduled retry remains visible. Queue writes are rejected for read-only stores and when inference is disabled by policy. | Confirmed by source and tests. | `src/xibalba_cortex/local_api.py:910-932,1198-1245`; `src/xibalba_cortex/store.py:4855-4892,4959-5006` |
| Browser QA against an isolated local API rendered memory search/detail, a prompt-response-tool replay, and inference filters with no browser console errors or failing requests on the replay journey. | Runtime evidence from local Chromium on 2026-09-18; fixture-only, not production data or proof of every profile mode. | QA screenshots under `/tmp/cortex-viewer-qa.hCfSEU/`; reproducible steps in the verification plan below. |

## Current architecture and data flow

```text
Harness / importer
  ├─ MCP memory tools, session sync, transcript/Codex backfill, OTel, generic API ingestion
  └─ source + memory + session + exchange + telemetry rows
        └─ profile SQLite database (profile_id is persisted; profile home selects the store)
              ├─ memories → FTS5 / graph / retrieval / lifecycle event chain
              ├─ sessions → exchanges → prompt/response memories + tool calls + context joins
              └─ memory_inference_tasks → claim/lease → evidence bundle → validated output
                                      → extraction proposals / explicit review / derived writes

Viewer → authenticated local API → primary profile store OR exact mounted read-only store
```

The API mounts stores; it does not merge their rows. Agent and store identity must travel together through list, detail, replay, graph, memory, and task reads. The browser journey observed that an operator token issued for another `profile_id` receives 403 until issued for the API’s profile. The UI should therefore treat `{store_id, agent_id}` as the selected workspace key, not the agent string alone.

### Important entities and contracts

| Entity | Important fields / relationship | Current API or UI path |
| --- | --- | --- |
| Profile/store | `profile_id`, configured storage home; API workspace exposes opaque `store_id`, access mode and `writable`. | `GET /api/agents`; profile config and store selection in `local_api.py:429-475,723-780` |
| Agent workspace | Agent ID, optional device/pair status, profile/store scope, access mode, count values plus `memories_counted` / `sessions_counted`. Paired per-device counts do not imply a profile-wide total. | `GET /api/agents`; `AgentWorkspacesTab` in `viewer/src/App.tsx:2123-2200` |
| Memory | `id`, `source_id`, `content`, `content_hash`, lifecycle `status`, `valid_from/to`, `supersedes_id`, derivation family, created time. Provenance resides in the linked source and event tables, not all on the memory row. | `GET /api/memories?agent_id&store_id&status&q&limit&offset`; detail endpoints in `local_api.py:865-909,940-1010` |
| Session | External session ID, retention tier, start/end, summary memory, agent ID. `session_replay` assembles memory and tool evidence; replayability/Merkle lineage is reported separately. | `GET /api/sessions/page`; `GET /api/session/{id}/replay?agent_id&store_id`; `TimelineTab` in `App.tsx:3015-3200` |
| Inference task | Type + subject, JSON input/output, state, claim lease, attempts, retry/failure/dead-letter details, timestamps. Tasks attach to memory/session/exchange/context bundle; only first three have supported agent-scope joins today. | `GET /api/inference/tasks?status&task_type&agent_id&store_id`; queue/claim/complete routes in `local_api.py:910-932,1198-1245,1346-1402` |
| Proposal / lifecycle | Extraction proposals are reviewable state transitions; memory transitions preserve evidence history rather than rewriting the source. | Proposal routes `local_api.py:945-1010`; `store.py:5874-5918,6036-6087` |

`viewer/src/api.ts:215-222,607-654` carries selected scope to most relevant reads and task actions. The UI chooses an agent and store together (`App.tsx:2204-2300,2790-2815`), loads a session page and graph for that scope, and then loads replay detail for the selected session (`App.tsx:2350-2445`).

## UX problems observed

1. **Agent identity and data scope are easy to miss.** The workspace selection is a compact global header control; memory and session content can appear before a user has seen which profile store supplied it. Runtime QA also exposed two entries in one temporary profile (an authorized DID and a persisted pseudonym). They are presented as separate exact namespaces today; no source-backed alias contract proves they should be merged. Keep them separate until an explicit identity mapping is supplied, but label the identity kind and explain why both appear. Source: `local_api.py:723-780`; rendered workspace image `workspace-loaded.png`.
2. **Counts can look authoritative when they are only page counts or device partitions.** Session pagination exposes `page_loaded`, and workspace counts may be uncounted. A badge such as “2 memories” can be mistaken for a store-wide total. Show scope plus the count basis next to every number; never turn absent/unloaded into zero. Source: `local_api.py:841-859`, `store.py:2300-2334`, `App.tsx:2173-2177,2809-2811`.
3. **Memory provenance requires opening a secondary inspector.** The explorer list emphasizes snippets/status, while source kind, observed time, locator, session, hash, and event chain are found only after selecting a memory. The inspector is useful, but its visible footprint competes with the timeline and can remain selected across tabs. Source/runtime: `App.tsx` inspector and `MemoryExplorerTab` around `4007-4145`; observed screenshot `memory-explorer.png`.
4. **Sessions are a replay surface, but the selector initially hides the list’s scope and completeness.** The existing page has a replay-ready prompt/response/tool display and a filter over loaded sessions. It needs a visible “loaded N / more available / unavailable” indicator and a session list with retention, activity, and evidence summary before opening the transcript. Source: `local_api.py:841-859`; `TimelineTab` at `3015-3200`; runtime `session-replay.png`.
5. **Inference queue presents controls and task records in one dense view.** Each task already has valuable state and retry/error/output data, but current summary “N pending tasks in this loaded page” is easy to read as a total. Disabled policy and read-only scope need a persistent explanation alongside disabled write controls. Source: `App.tsx:4340-4590`, `local_api.py:910-932`, `store.py:4855-4892`.
6. **An empty result can be confused with a failed or incomplete query.** The code now distinguishes first-load failure and task stale data, but session totals and task totals remain uncounted without a count endpoint. Empty means “no matching rows in this query/page,” not “nothing exists anywhere.” The UI should state that directly.
7. **Some capabilities are profile-wide rather than selected-agent scoped.** Context-bundle inference tasks cannot be assigned to a durable agent owner with the current schema. Pair association writes the primary profile; cross-profile write controls must stay disabled. Source: `store.py:4959-5006`, `App.tsx:2148-2168`, API write guards in `local_api.py:1198-1245`.

## Proposed information architecture

Use five primary destinations, with task-specific views inside Memory, Activity, and Settings. Keep the selected workspace in the persistent scope bar and preserve `{store_id, agent_id}` for every scoped route.

```text
┌ Cortex ────────────────────────────────────────────────────────────────────────┐
│ Agent [canonical identity ▾] · Profile/store · writable/read only · Refresh     │
├ Home | Memory | Sessions | Activity | Settings ────────────────────────────────┤
│ Memory: [Browse] [Search] [Graph]     Activity: [Inference] [Integrity & review] │
│ Settings: [Manage agents] [Operations] [Preferences]                            │
├───────────────────────────────────────────────────────────────────────────────┤
│ Search/filters and explicit count basis       Results / session / task list     │
│ Selection opens a contextual detail panel: source, replay, task payload, proof  │
└────────────────────────────────────────────────────────────────────────────────┘
```

- **Home** contains the existing overview and recent scoped activity.
- **Memory** groups the explorer, retrieval search, and graph views. Provenance for a selected memory belongs in its inspector. Lifecycle and evidence counts should live with the relevant Memory filters rather than occupy persistent sidebar space.
- **Sessions** remains a dedicated list-to-replay journey.
- **Activity** groups Inference and Integrity & review. The latter has inner views for store lineage and proposals/retrieval proofs; task, audit, and proposal records/count bases remain separate.
- **Settings** contains agent management, Operations, and Preferences. Agent selection remains global in the scope bar; Manage agents is for pair administration and availability, not a second selector.

### Agent selection and availability

- Agent picker options show readable canonical label, raw identity type (DID, local/pseudonym, unassigned), profile ID, and `writable` / `read only`. Preserve `{store_id, agent_id}` in the picker value and browser session state.
- On selection, show a scope summary before content: profile/store, identity, permissions, and measured/loaded/unavailable counts. Use `count_status` (`exact`, `page_loaded`, `not_loaded`, `unavailable`) separately from numeric values. Existing API can support page-loaded values and access labels. Exact totals require backend work.
- If there are no workspaces: say “No agent workspace is available to this credential.” If a registered agent has no records: keep the identity selectable and report “No memories/sessions recorded in this profile” only after a scoped query succeeds. If API authorization fails: show profile access denied, not empty.
- For raw and pseudonymous identifiers, display both as distinct namespaces until the identity service returns a verified alias relationship. Do not merge their records across stores or by string similarity.

### Memories

- Main page: search input, lifecycle chips (candidate, active, confirmed, disputed, quarantined, superseded, forgotten), source type, time range, and “include forgotten” toggle. Result rows show content excerpt, current state, evidence class, source kind, observed/created time, session, and a small lineage indicator.
- Details open in a right-side panel with stable width and a close action: full content/hash, source locator and observed time, lifecycle history, supersedes/superseded-by, linked session/exchange, entity/contradiction links, OTel/attachments, and available proof actions. Mark missing provenance fields “not recorded”; do not hide them or manufacture values.
- Search empty: “No memories match these filters in profile X for agent Y.” Search failure: keep the last page visibly stale and offer retry. Initial load uses a skeleton/status; unavailable profile uses an error with retry. Zero selected statuses is a local filter state and should not issue a misleading API query.
- Supported today: scoped memory list/search and detail, lifecycle, source/relationship/OTel/attachment/proof APIs. Date/source-kind filtering and a complete provenance timeline need new query/API work.

### Sessions

- Two-pane page: left list with search over loaded sessions, retention tier, start/end/active state, and evidence count; right detail with replay timeline, prompts/responses, tool calls, contributing memories and integrity/replay status.
- Session header says “Showing 50 loaded; more available” or “All sessions loaded” only when the API can establish that. Until then show “50 loaded; total not counted.” Selecting a session loads replay and exchange details independently; render partial successes with per-section errors.
- Empty session list after a successful query: “No sessions recorded in this selected profile.” No selected agent: ask the user to select one. Session replay missing: distinguish “no exchanges recorded” from “replay unavailable” and retain the session metadata.
- Supported today: paginated session rows, filtering current loaded page, replay, exchanges, OTel, Merkle root/proof, and session recording. Total count and a server-side search cursor are backend gaps. Avoid the current reload after “Build DAG Exchanges”; refresh the selected detail in place (small frontend follow-up).

### Inference

- Summary strip: selected profile/agent, inference feature state, task status, time refreshed, and query scope (`status-filtered page`, never a global total unless counted).
- Left column: queue actions, task type/provider manifest and write capability. Right column: task list with subject, state, created/updated timestamps, attempt count, requested/executing provider, retry-after, error/failure class, dead-letter reason, and expandable input/output JSON. Link memory/session subject into its scoped detail page.
- Pending/claimed/completed/failed/cancelled are filters. Failed state can be retried only when an API transition supports it; do not imply retry is available because `retry_after` exists. Read-only store disables all task mutations. Feature disabled says “Inference is disabled by this profile’s feature policy”; still allow reads if API permits them.
- Empty results say “No failed tasks in this selected page/query.” If refresh fails with cached rows, show the cached rows with a stale banner. If refresh fails before any rows, show unavailable rather than empty. Do not count context-bundle tasks as agent-owned until schema adds a durable owner.
- Supported today: list per status and selected scope, queue/claim/complete, task payload and error fields, read-only gating, feature flag from Operations. Cursor pagination, total-by-status counts, durable context-bundle ownership, explicit retry endpoint, and worker heartbeat history are backend gaps.

## UI-to-data capability mapping

| Proposed UI | Existing support | Backend gap / constraint |
| --- | --- | --- |
| Persistent agent + profile/store selector | `GET /api/agents` gives profile/store/access; `{store_id, agent_id}` reads reject ambiguous store scope. | Verified alias mapping for raw DID ↔ pseudonymous namespace; do not combine without it. |
| Honest workspace count states | `memories_counted`, `sessions_counted`; `/api/sessions/page` provides `has_more` and `page_loaded`. | Exact profile/agent totals and count status in the same response. |
| Search and lifecycle filters | `/api/memories` supports agent/store/status/q/offset/limit; FTS query in `GraphStore.list_memories`. | Server date/source filters and consistent page metadata for total/estimated counts. |
| Provenance inspector | Memory detail/events/neighbors/contradictions/similar/OTel/attachments and session replay APIs, all scope-aware in the current changes. | Unified provenance bundle endpoint would reduce fan-out; not required for first UI pass. |
| Session list and replay | `/api/sessions/page`, replay, exchanges, OTel, Merkle root/proof; browser verified actual prompt/response/tool display. | Exact session totals, server search/filtering, and per-session evidence summary in list rows. |
| Inference queue and task detail | Status filtered `/api/inference/tasks`; task schema includes output and failure/retry fields; operations response has feature flags. | Count-by-status/cursor, explicit retry transition, context-bundle agent owner, worker health timeline. |
| Honest loading/error/empty states | Current viewer has distinct loading, query error, no-result, read-only, uncounted, and stale-task cases. | API must consistently distinguish permission-denied, unavailable store, partial page and no data. |

## Implementation already applied in this checkout

- Added opaque `store_id` to profile-scoped agent workspaces and enforced store selection for ambiguous reads; threaded scope through memory, graph, session, replay, inspector and inference task APIs. Added session page metadata and scoped search/task filters.
- Added `memories_counted` / `sessions_counted` markers for records whose full totals are not known; displayed selected profile/store and source; added memory query/status controls and task lifecycle/error/retry/output details.
- Added read-only action gating, including the profile-pair form; made inference feature-disabled state explicit; fixed the cached-task/no-filter-match wording; added loading/error/partial replay treatment.
- Hardened the viewer against legacy `/api/agents` payloads that omit profile/store/access: rows remain visible as unavailable, cannot be selected or mutated, and do not silently default to writable. Workspace memory/session totals now render as exact only when the API explicitly marks them counted.
- Simplified the viewer into five primary destinations (Home, Memory, Sessions, Activity, Settings), with secondary views inside Memory, Activity, and Settings. Removed duplicate provenance navigation and the always-visible lifecycle/evidence rails; retained their supported graph filters on the Graph view.
- Added regression coverage for same agent/session IDs in separate profile stores and store selection. The dirty runtime/session edits present before this work were preserved.

## Prioritized implementation and acceptance

1. **Scope and contract hardening (implemented; verify before merge).** All agent data reads/actions carry both store and agent scope; duplicate IDs across stores never bleed; ambiguous unscoped request fails closed; read-only store mutations fail closed. **Accept:** API regression test with same agent and session IDs in two DBs; no cross-store memory, replay, or task rows; write endpoints return permission error for read-only scope.
2. **Workspace clarity (implemented; polish next).** Show profile/access and count basis at the selected-workspace level; retain registration-only identities without claiming their data count is zero. **Accept:** uncounted is never rendered as “0”; selected profile survives refresh; workspace identity and store scope are visible on memories/sessions/inference.
3. **Memory browsing and inspection (implemented baseline).** Search/status/paging and source/lifecycle details. **Accept:** text query and all seven lifecycle statuses; detail provenance calls use selected store; empty/filter/error/loading states differ; forgotten data is explicitly included only when selected.
4. **Session library and replay (implemented baseline).** Session pagination, list filtering, scoped replay, tool and memory lineage. **Accept:** loaded/has-more label; selecting a session shows its own transcript; API failures do not become “no exchanges”; no whole-page reload after rebuilding exchanges.
5. **Inference activity (implemented baseline).** Status filters, retry/failure/provider/output details and policy-aware actions. **Accept:** future retry tasks remain visible; failed/empty/loading/unavailable/stale are distinct; disabled inference and read-only store are explained; actions include scope and subject.
6. **Counts and search completeness (backend follow-up).** Add `count_status`, exact totals or explicit estimates, cursor pagination, and server-side session search. **Accept:** every displayed number declares exact/page/estimated/not-loaded/unavailable; store-level totals are never inferred by summing stores.
7. **Visual/accessibility polish.** Test narrow viewport, keyboard focus, dropdown label readability, inspector sizing and session/detail layout. **Accept:** no horizontal overflow at 390px; scope selector remains readable; detail panel does not cover the primary action; all filters announce result/loading/error changes.

## Verification plan and current evidence

- **Source/API tests:** `uv run --project . pytest -q tests/test_local_api.py tests/test_store.py tests/test_inference_loop.py` — passed, 126 tests, including `test_workspace_store_scope_pins_memory_session_and_inference_reads`.
- **Frontend:** `npm run build` — passed; vendor bundle warning remains (4.38 MB minified). `npm run lint` — passed with no diagnostics after dependency fix. `git diff --check` — passed.
- **Rendered browser:** Browser plugin was not available, so used regular Playwright Chromium for the isolated profile journey. API and Vite ran on `127.0.0.1:18420` and `127.0.0.1:15190`; data was seeded only in `/tmp/cortex-viewer-qa.hCfSEU` using a profile-bound temporary operator token. Verified workspace selection, a text-filtered memory and provenance inspector, session replay (prompt, response, tool call), and inference status filtering. At 390px, overview, memories, sessions, and inference had no horizontal document overflow; mobile navigation closed after page selection. Screenshots: `/tmp/cortex-viewer-qa.hCfSEU/session-replay.png`, `memory-explorer.png`, `inference-empty-state.png`, `mobile-inference-final.png`.
- **Live root contract observation:** Before the targeted API reload, the authenticated live root viewer showed agent cards with `Profile store: · writable` and a selector without profile IDs; screenshot `/tmp/cortex-viewer-qa.hCfSEU/live-agents-tab.png`. The corresponding old `/api/agents` response omitted `profile_id`, `store_id`, and `store_access`. Only `xibalba-cortex-local-api.service` was reloaded; its `/healthz` returned 200 with profile `default`. A later authenticated browser session rendered the corrected contract: the picker listed `xibalba`, `xibalba-quant`, and `xibalba-shield` with `default` / `xibalba-cortex-quant` / `xibalba-cortex-shield` and writable / read-only labels. Selecting Quant and Shield changed the persistent scope bar, displayed their profile-local counts (30 and 26 memories respectively; session totals explicitly not counted), and rendered their session and inference rows. Quant replay opened a transcript; Shield inference task input/output detail expanded. Read-only queue and pair mutations were disabled. Quant/Shield services and profile data were not touched.
- **Browser validation limits:** The live browser controls exposed accessibility/rendered state and screenshots; they did not expose browser console or network-log inspection, so no claim is made that the console/network were error-free. Desktop viewport rendered at 1544×686. The prior isolated-profile Playwright journey checked 390px overflow and memory/replay/inference interactions. Multi-profile API regression covers same-ID store isolation, but there is not yet a dedicated rendered 390px two-store journey. The external identity oracle may be unavailable, represented by `identity_verified`, and is not evidence of profile scope.
- **Navigation redesign browser check:** On the live viewer at `http://127.0.0.1:5190/`, confirmed the five primary destinations and workspace scope bar in the rendered accessibility tree and screenshot. Opened Activity → Inference and Activity → Integrity & review → Store lineage / Proposals & retrieval; the prior duplicate Review proposals destination is gone. Root scope remained `xibalba · default · writable`; observed inference empty-state copy is explicitly scoped to “pending” tasks in the loaded page. No records were mutated. This pass did not recheck mobile layout or browser console/network logs.
