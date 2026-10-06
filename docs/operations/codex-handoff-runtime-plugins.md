# Codex handoff: Cortex runtime and plugins

Continue on `feat/cortex-runtime-and-plugins` in `XibalbaTechSol/xibalba-cortex`.
The branch starts from main commit `e85e23bcb0b2c61964458d9fa424807ecbac2031`,
which includes hosted memory connector PR #42 and observer foundation PR #39.
No provider account call, cloud deployment, official directory submission or merge
of this implementation branch has been performed.

Continuation evidence and remaining release gates are recorded in
[`runtime-plugin-canaries.md`](runtime-plugin-canaries.md). The 2026-10-06 pass
verified native manifest/install checks and a scoped local MCP invocation, fixed
recorder review findings and the documented identity prerequisite, and passed
603 tests with 2 opt-in skips. Live model-host callbacks, Perplexity billing/API
and consumer OAuth/HTTPS dispatch remain outstanding.

## Implemented

- `PerplexityAdapter.recorder()` and `xibalba-cortex-perplexity`: launch background
  SSE sessions, record incrementally, scope memory injection, persist restart cursors,
  resume via GET, request cancellation, obtain snapshots and replay/watch local JSONL.
- Profile-local journal atomically commits events/cursors, then mirrors idempotent
  runtime events into existing GraphStore OTel sessions. Explicit capture-gap events
  cover rejected resume/snapshot fallback and sequence gaps. No automatic POST retry.
- Default metadata-only recording; opted-in complete supported text is bounded and
  redacted. Text deltas and reasoning bodies do not retain text. Custom functions
  are recorded, not executed. No new live viewer player/launch panel.
- Claude Code and Codex native plugin packages with MCP wiring, observation-only
  hook launchers, connection-check skills, and host-specific catalogs.
- Gemini CLI extension with MCP memory access and declared profile setting. It does
  not add a full native Gemini observer. Root manifest permits monorepo Git install.
- Spark/Perplexity hosted setup templates, explicit OAuth/HTTPS prerequisites,
  deterministic plugin ZIP builder/checksums and CI artifact packaging.

## Validation completed here

Full backend suite: **593 passed, 2 opt-in skips, 2 warnings** (36.51 seconds).
Bundled skills passed frontmatter validation. Deterministic archive build passed.
Focused recorder/plugin/provider tests passed; Git diff whitespace checks passed.
Native host installation and billed provider/OAuth canaries remain unverified.

## Validate and continue

Use the existing sibling `integrity-core/integrity-sdk` layout and pinned CI SDK
commit `4ddaae1965635224958e147f6eaaead06e3cdc41`. Run `uv sync --extra otel`,
then `uv run pytest -q -o addopts=''`. Focused tests:

```bash
uv run pytest -q tests/test_perplexity_runtime.py tests/test_plugin_distribution.py tests/test_provider_adapters.py
python scripts/build_cortex_plugins.py --archives /tmp/cortex-plugins
```

Check GitHub CI and package artifacts after opening the implementation PR. Review
this branch's recorder before conducting a billed provider canary. Supply a real
Perplexity API key privately, explicitly consent in config, use a session-bound
Integrity DID, and follow `perplexity-runtime-recorder.md`. Verify real event shapes,
background resume/cancellation, tool output and provider account limits. No live
API validation should be inferred from HTTP fixtures.

Native Claude/Codex/Gemini binaries were unavailable here. Run native manifest
validation and actual installation/trust/callback/menu checks on a pilot machine.
Follow `cortex-plugin-distribution.md`; ensure the Cortex bin directory is available
to the host and the intended profile is explicit. Do not install duplicate observer
routes. Verify an actual MCP invocation and recorder receipt.

For consumer Spark/Perplexity, complete external OAuth issuer/DCR/consent setup,
public HTTPS hosting and actual account dispatch canaries described in
`hosted-memory-connectors.md`. The existing hosted resource server does not
implement an authorization server. Templates are not app-store manifests.

Official directory submission remains a separate action. Repository publication
and custom catalogs make packages discoverable only to users adding those sources;
they do not prove official approval/listing. Hosted ChatGPT cannot execute the local
stdio package; it needs a deployed/registerable remote MCP plugin.

Retain the journal limitation: existing provider telemetry deletion/export only
covers GraphStore, not the recorder's local journal. Manage that copy separately.
Do not upload or modify `docs/PROJECT_STATE.md`: the earlier approval review rejected
uploading the existing ledger because it contains private account/operational data.
All task documentation lives under operations instead.
