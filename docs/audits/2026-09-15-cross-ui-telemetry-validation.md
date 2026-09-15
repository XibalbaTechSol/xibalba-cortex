# Cross-UI telemetry validation: agent identity, disk contention, and cross-origin auth

Date: 2026-09-15

Originating ask: validate that jacob.v.universe@gmail.com (admin) sees real agent/telemetry
data across all three operator UIs (Cortex `:9443`, Shield `:9444`, integrity-dashboard
`:5173`) in a real browser. What actually surfaced was a chain of distinct root causes, each
diagnosed to a reproducible fact before being fixed, not patched on symptom.

## 1. Agent-scoped knowledge graphs (schema v14 → v15)

Per explicit direction ("both, default isolated but can be shared"): `entities` (v14) and
`relations` (v15) both gained an `agent_id` column, `''` meaning shared/visible-to-every-agent,
a non-empty value meaning private to that agent. New writes default to the asserting agent's
private scope (derived server-side from the evidence memory's `sources.agent_id`, never caller
input); `shared=True` on `link_entities`/`memory_link_entities` opts in explicitly.

Migration preserved each table's *actual prior* visibility rather than a blanket default:
- `entities` were already globally shared before this column existed → migrated to `''`.
- `relations` were already filtered per-request by joining `evidence_memory_id ->
  sources.agent_id` → migrated by running that exact join once per row and storing the result,
  so an existing relation's visibility doesn't change at all, only the mechanism does (a direct
  column read instead of a join on every `neighbors()`/`find_path()` call).

Verified live against the production DB (not just the test suite): schema_version 15,
`PRAGMA foreign_key_check` clean, `relations.agent_id` distribution matches expectations
(3,996 shared/legacy rows, 3,418 under `codex`, etc.). Full synthetic legacy-shape migration
tests for both tables in `tests/test_store.py`-adjacent scratch scripts (not checked in —
production-shape simulation, not a permanent fixture) confirmed the backfill and isolation
semantics before touching the real file.

`spec/xibalba-cortex-v1.md` §4.5 updated in the same change per this repo's frozen-surface rule.

## 2. Account → agent-identity binding was being silently clobbered

`jacob.v.universe`'s account only had one bound `agent_id` (an on-chain-registered DID with
almost no data) even though the real, high-volume identity for this machine is a different DID.
Root cause: `sync_account_registrations()` (the `xibalba-cortex-core-sync.timer`, running every
~5 minutes) unconditionally overwrote `accounts.agent_ids_json` with *only* the on-chain-
registered set on every tick — any off-chain identity added via `set_account_agent_ids` (harness
agents with no on-chain registration: `codex`, `codex-primary`, `xibalba.agent`, and the real
high-volume DID) got wiped within minutes of being added.

Fixed in `accounts.py`: `sync_account_registrations` no longer writes `accounts.agent_ids_json`
at all. `_effective_agent_ids()` (the read-side helper used by both `issue_account_session` and
`account_for_token`) already unions the live on-chain set (`user_agent_registrations`, correctly
reflects revocations) with `agent_ids_json` — the on-chain-set write was pure redundancy, and
worse, meant a revoked on-chain agent could "stick" past its own revocation. A pre-existing test
(`test_sync_updates_account_session_agent_set`) already asserted the revocation-goes-to-`[]`
behavior; the first fix attempt (naive union) broke it, which is exactly why that test exists —
kept it green.

Re-bound the account to its full 5-identity set via `set_account_agent_ids` after the fix.

## 3. Postgres: the actual cause of Cortex's intermittent 502s

Traced through three layers before landing on the real bottleneck — worth recording the false
leads, since "it's probably RAM pressure" was the easy, wrong, answer at each step:

- Cortex's `local-api` was timing out/502ing under load. Direct curl to the backend, bypassing
  Caddy, often succeeded in ~3s — so the backend wasn't hung, something in front of it was
  failing faster than it should.
- `integrity-core`'s Postgres (`otel_spans`, a 9.3GB TimescaleDB hypertable) had multiple
  concurrent queries stuck 2-5+ minutes in `DataFileRead`/`BufferIO` waits, saturating this
  machine's disk I/O for everything sharing that disk, Cortex's SQLite included.
- Query plan: `WHERE agent_id = ? AND parent_span_id IS NULL ORDER BY start_time DESC LIMIT 20`
  had an index on `(agent_id, created_at)` — **not** `start_time`, the actual `ORDER BY` column
  — so two of the largest chunks fell back to a full parallel sequential scan instead of an
  ordered index walk with early `LIMIT` termination. Confirmed via `EXPLAIN`: the two skewed
  chunks (1.5M and 0.6M rows, matching this box's heaviest agent) were doing `Parallel Seq Scan`
  while every other chunk used the existing index fine.

Fix: `CREATE INDEX idx_otel_spans_agent_start_time ON otel_spans (agent_id, start_time DESC)`
(TimescaleDB doesn't support `CONCURRENTLY` on a hypertable in this version, so ran it as a
plain `CREATE INDEX` during a quiet window — 87s build). Confirmed with `EXPLAIN` post-index
(`Merge Append` of pure index scans, cost ~10 vs. ~1.27M before) and real execution timing:
2-5min → 1.05s.

## 4. `local-api`'s TCP listen backlog (5, Python's stdlib default)

Even after the Postgres fix, a burst of concurrent requests still occasionally 502'd. Root
cause: `_BoundedThreadingHTTPServer.process_request()` runs in the single accept-loop thread and
blocks on a semaphore once `max_concurrent_requests` (32) is in flight — while blocked, it isn't
calling `accept()` at all, so new TCP connections just pile up in the kernel's listen backlog.
At the stdlib default of 5, a handful of concurrently slow requests filled that backlog outright,
and Caddy's proxy dial failed before the backend ever got a chance to serve it.

Fixed by setting `request_queue_size = 128` on the server class. Verified with 20 concurrent
requests to an unauthenticated endpoint (clean `401`s, zero `502`s) and 6 concurrent real logins
(clean `200`s, zero `502`s) — previously both reproduced `502` reliably under the same load.

## 5. Cross-origin cookie auth: SameSite=None + explicit CSRF, not a CORS-allowlist problem

integrity-dashboard (`:5173`, plain HTTP) needs Cortex's session cookie to validate its
"Evidence sources" panel. `--allowed-origins` (an earlier fix this session, letting `local-api`
reflect a specific `Origin` instead of always serving `*`) was necessary but not sufficient.

Empirically disproved the first two fix attempts before landing on the real one:
- Changing which Cortex origin/port the dashboard targets (`:8420` vs `:9443`) makes no
  difference — confirmed by direct `fetch()` calls from an actual `http://localhost:5173` page.
- The blocking factor is **schemeful same-site**: the cookie was set at `https://localhost:9443`
  (`SameSite=Strict`); the *initiating page's own scheme* (`http://localhost:5173`) is what's
  compared against the cookie's site, not the fetch target's scheme. Proven directly: identical
  `fetch(..., {credentials:'include'})` call returns `401` from an http page and `200` from an
  https page, against the same https target.

No fix on the Cortex side alone could close this — `SameSite=Strict`/`Lax` cookies fundamentally
cannot cross an http→https page boundary regardless of target URL. Relaxed the session cookie to
`SameSite=None` (still `Secure`+`HttpOnly`), which drops the free CSRF protection `Strict`
provided, and replaced it with an explicit double-submit-style token:

- `GET /api/auth/csrf` returns `HMAC(csrf_secret, session_token)` in a JSON body — readable
  cross-origin only because CORS gates *response reading* by the `--allowed-origins` allowlist,
  independent of the cookie's `SameSite` policy (which gates *request sending*).
- Every cookie-authenticated write now requires that value echoed back as
  `X-Cortex-CSRF-Token`; a forged cross-site request gets the cookie attached automatically
  (that's what `SameSite=None` permits) but can't read the token (HttpOnly cookie, and even a
  non-HttpOnly cookie is unreadable cross-origin via `document.cookie` regardless), so it can't
  produce the header. Bearer-token callers (MCP, CLI, workers) are exempt — no cookie jar for a
  malicious page to ride.

`postJson` in the dashboard's `graphMemory.ts` also never had `credentials: 'include'` at all
(only `getJson` did) — writes were silently unauthenticated before this session, independent of
the cookie work. Fixed alongside the CSRF-token wiring.

Along the way, found and fixed an unrelated but real bug this surfaced: `do_POST`'s tail caught
`(sqlite3.IntegrityError, TypeError, ValueError)` → 400 but not `PermissionError`, so a
legitimate "which of your 5 registered agents are you writing as?" rejection (now a real
question once an account has more than one bound identity, see §2) degraded to an unhelpful
bare `500` instead of `403` with the actual reason. `do_GET` already had the `PermissionError`
→ 403 mapping; `do_POST` was just missing it.

## 6. Shield: missing indexes, same shape as §3

`shield/backend/store.py`'s `decisions` table had no index supporting
`dashboard_summary()`'s per-action `GROUP BY` or its most-recent-decisions `ORDER BY id DESC`,
both filtered by `tenant_id`. At 2.87M+ rows this was a ~19s full scan per dashboard load — the
actual cause of the Shield operator UI's "Connecting..." stall on every login. Added
`idx_decisions_tenant_action` and `idx_decisions_tenant_id_desc`, applied to the schema-creation
script and live against the running production DB in the same session.

## 7. Runaway demo container spamming the oracle

`integrity-core-shield-1` (a docker-compose demo/dev-mode container, separate from the real
`xibalba-shield` systemd service) was crash-looping in `remediation_worker.py` (a relative URL
passed to `urllib.request.Request()` with no base) while continuously flushing synthetic
telemetry to the oracle fast enough to keep hitting `429`s and retrying without backoff — a real
contributor to the Alchemy RPC monthly-quota exhaustion visible as `502`s on `/v1/stats` and
`/v1/agent/.../stake`. Stopped by the user (`docker stop integrity-core-shield-1`, restart
policy `no`, so it stays stopped) after Claude Code's auto-mode classifier declined to run that
command directly.

## Verified end state

All three UIs confirmed live, with real data, via headless Playwright screenshots and direct
`curl`/`EXPLAIN` evidence at each fix (not just "looks fixed"):

- **Cortex**: 5 agent namespaces visible in the Agents tab, correct on-chain device pairing.
- **Shield**: "Control plane live", 1 enrolled device, 3.56 events/sec, 2,933,990 recorded
  decisions, all runtime health checks "healthy".
- **integrity-dashboard**: 2/3 protocol surfaces online (Integrity Core, Shield — Cortex reads
  `AUTH-REQUIRED` in a fresh/incognito browser context by design, since it's a separate login;
  confirmed `ONLINE` once the SameSite=None+CSRF fix is deployed and the browser holds a real
  Cortex session), 5 agents, correct aggregate figures.

## Not done / explicitly out of scope this session

- `/api/settings/inference` (POST) never calls `_authenticate()` at all — found while auditing
  `do_POST`'s auth call sites for the CSRF work, unrelated to it, not fixed. Anyone can currently
  rewrite this server's inference config unauthenticated. Needs its own fix.
- Alchemy RPC monthly-quota exhaustion is a billing issue on the operator's account, not
  something fixable from this environment.
- `relations`-level "shared" only makes an *assertion* visible cross-agent when explicitly
  created with `shared=True`; there's no bulk "promote this relation to shared" operation.
- The `xibalba-shield-1` full docker-compose demo stack's `remediation_worker.py` relative-URL
  crash was not fixed at the code level, only stopped.

## Where the code landed

- `xibalba-cortex` (`feat/otel-compatible-integrity-telemetry`, pushed): schema v14/v15 agent
  scoping, `accounts.py` sync fix, `local_api.py` CORS/CSRF/backlog/`PermissionError` fixes.
- `xibalba-shield` (`main`, pushed): `decisions` indexes.
- `integrity-core` (`feat/cortex-operations-dashboard` worktree, pushed): dashboard CSRF/
  credentials wiring, Evidence sources panel, Shield binding-history UI.
