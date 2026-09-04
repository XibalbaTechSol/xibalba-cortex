# Operations UI (Production Readiness panel) visual verification

Date: 2026-09-04

## What was verified

The last unverified item from the 2026-09-04 pilot-validation drill (`docs/PRODUCTION_READINESS_PLAN.md`
§1's local-batch checklist): whether the authenticated "Production readiness" panel in
the viewer (`viewer/src/App.tsx`'s Operations view) actually renders real backend data
in a real browser session, not just that the code exists.

## Method

- Provisioned an isolated tenant profile (`visual-verify-20260904`) via
  `xibalba_cortex.tenant_onboarding`, in a scratch home outside `~/.hermes/xibalba-cortex`
  so this did not touch or interfere with any other running session's real profile.
- Started a scratch `xibalba_cortex.local_api` instance on port 8421 (not the default
  8420, since another session already had a real instance live there — confirmed
  healthy and left untouched throughout).
- Started the viewer's Vite dev server pointed at the scratch backend via
  `VITE_LOCAL_API_URL`.
- Used a real Chromium browser session (Claude in Chrome) to load the viewer, enter the
  real bearer token issued by `tenant_onboarding` into the login form, and navigate to
  the Operations view.

## Result

The Production Readiness panel rendered live, matching `GET /api/operations`'s real
response exactly: profile `visual-verify-20260904`, `local_only`, 1 active credential,
token lifecycle `implemented`, tenant onboarding `implemented`, isolation model "one
profile home and SQLite store per tenant", and the five open production gates (external
pilot deployment, published integrity-sdk, HA/PITR, real-tenant evaluation, burn-in
SLA). No console errors observed. Screenshot evidence retained locally (not committed —
same reasoning as `docs/wiki/architecture/viewer-and-local-api.md`'s note that
screenshots from a live profile may carry operational history).

## Cleanup

The scratch `local_api` (port 8421) and viewer dev server (port 5180) were both
terminated after verification. The other session's real `local_api` instance on port
8420 was confirmed healthy before and after and was never stopped.

## Disclaimer

Local, authenticated, single-operator visual verification only. Not external
deployment, multi-user, or production evidence — same boundary as the pilot-validation
drill this closes out.
