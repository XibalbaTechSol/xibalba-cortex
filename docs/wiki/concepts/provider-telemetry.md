---
title: Provider Telemetry Adapters
type: concept
tags: [telemetry, privacy, perplexity, mcp, cloud]
confidence: high
source_files:
  - src/xibalba_cortex/provider_adapters.py
  - src/xibalba_cortex/config.py
---

# Provider telemetry adapters

Cortex exposes three provider-facing adapters over the shared `RuntimeEvent` schema:

- `PerplexityAdapter` calls the Perplexity Agent API through an injectable transport, recording
  request/response lifecycle, usage, citations, request IDs, and failures.
- `MCPAdapter` records tool-start/tool-finish boundaries, invocation IDs, status, duration, and
  hashed arguments/results.
- `CloudRunAdapter` accepts provider-neutral webhook or SDK lifecycle events, recording model,
  request ID, usage, retries, latency, citations, final output, and outcome.

## Privacy and authorization

`ProviderTelemetryPolicy` is fail-closed:

- `consent_granted` must be true for the named provider;
- the event must have a non-empty session ID;
- the event must be attributed to a `did:integrity:*` identity;
- retention is limited to `digest`, `synopsis`, or `verbatim`;
- raw payloads are hashed and represented by character counts by default;
- raw provider content is only retained when `allow_raw_payloads` is explicitly enabled.

Persisted configuration is disabled by default:

```yaml
telemetry:
  enabled: true
  consented_providers: [perplexity]
  retention_tier: digest
  allow_raw_payloads: false
```

Use `policy_from_config(load_config(...), "perplexity")` to construct the policy instead of
creating an implicit consent grant in application code. Provider API keys are transport inputs
and are never included in normalized event metadata.
