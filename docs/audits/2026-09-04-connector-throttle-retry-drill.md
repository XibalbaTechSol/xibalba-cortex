# Connector throttle/retry real-transport drill

Date: 2026-09-04

Runs `docs/operations/connector-drill-runbook.md` §2's ingress-throttle check and
closes its own §3-adjacent gap: proving `retry_call`'s backoff logic recovers over a
real HTTP round trip, not a mocked exception. Both drills use a real socket; neither
mocks `urllib` or the exception types `retry_call` inspects.

## Drill 1: local API ingress throttle (real burst, real server)

Provisioned an isolated scratch profile (`connector-drill-20260904`), started a real
`xibalba_cortex.local_api` instance, and fired 100 real sequential `GET /readyz`
requests over `urllib.request` against it, timing each one.

Result:

```json
{
  "schema_version": "xibalba.connector_throttle_drill.v1",
  "total_requests": 100,
  "total_wall_seconds": 3.0271,
  "first_40_wall_seconds": 0.0983,
  "remaining_60_wall_seconds": 2.9288,
  "theoretical_min_for_60_requests_at_20rps": 3.0,
  "throttle_observed": true,
  "all_status_200": true
}
```

The first 40 requests (the token bucket's burst capacity) completed in 0.098s with
no delay; requests 41-100 each incurred a real ~0.05s wait, matching the documented
20 req/s replenishment rate almost exactly (2.93s observed vs. 3.00s theoretical
minimum for 60 throttled requests). Every request still returned 200 — this
confirms `ConnectorRateLimiter` throttles by delay, not by rejecting or dropping
requests, matching its own docstring's stated behavior. No requests were lost or
silently dropped, closing the runbook §2 requirement "the rate limiter prevents
unbounded request throughput without dropping valid events silently."

## Drill 2: retry/backoff against a real flaky HTTP server

`connector_policy.retry_call`'s only prior test coverage
(`tests/test_connector_policy.py`) raises Python exceptions directly — real
recovery behavior over an actual HTTP response sequence (429 then 500 then 200)
had never been exercised. Started a real `http.server.HTTPServer` on a random
loopback port programmed to return exactly that sequence, then called
`retry_call` against it through a real `urllib.request.urlopen` round trip.

Result:

```json
{
  "schema_version": "xibalba.connector_retry_drill.v1",
  "transport": "real local HTTP server (http.server), not a mocked exception",
  "sequence": "attempt 1 -> HTTP 429, attempt 2 -> HTTP 500, attempt 3 -> HTTP 200",
  "final_status": 200,
  "total_attempts_made": 3,
  "elapsed_seconds": 0.344,
  "passed": true
}
```

`retry_call` correctly classified both the 429 and the 500 as retryable (matching
`connector_policy.py`'s own status-code check), retried through both, and returned
the real 200 on the third attempt — proving the retry/backoff path works over a
real transport, not just against a hand-constructed exception object.

## What this does and does not close

Closes: real-transport evidence for the shared throttle primitive (used by
OTLP/webhook/local-API ingress) and the shared retry primitive (used by Drive
egress and any future outbound connector). Matches
`docs/operations/connector-drill-runbook.md` §2's own checklist.

Does not close: real Google Drive OAuth evidence (runbook §3) — that still
requires a real Google account and is an external gate, not something a local
drill can substitute for. Does not close per-connector isolation drills for the
four local-file connectors (runbook §1) — those were not run in this pass.

## Reproduction

Scratch scripts (not committed — throwaway, single-use):
`/tmp/claude-1000/.../scratchpad/cortex-connector-drill/throttle_drill.py` and
`retry_drill.py`, both self-contained, no external dependencies beyond the
standard library and this repo's own `connector_policy` module.
