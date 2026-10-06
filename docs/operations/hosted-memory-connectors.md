# Perplexity and Gemini Spark memory connector

This is an implemented MCP **resource server**, not a complete managed hosting product.
It exposes `cortex_remember`, `cortex_recall`, and `cortex_connection_status` over
stateless Streamable HTTP. Each credential is bound to exactly one profile and agent.
Writes require `memory:write`; all requests require `memory:read`. Administrative,
review, deletion, and arbitrary runtime-ingestion tools are absent.

## Deploy

Install the package with `uv sync`. Put TLS and deployment request-rate controls in
front of the loopback service. Forward Authorization, Host, and the complete `/mcp`
and `/.well-known/oauth-protected-resource/mcp` routes. Configure the proxy's Host
forwarding consistently with the MCP SDK transport-security policy; validate it
before onboarding a remote client. Keep the bindings file operator-writable only.

For OAuth, supply an existing authorization server with OAuth discovery,
authorization code + PKCE, consent, refresh/revocation, and dynamic client
registration (DCR), or Google's documented advanced client configuration.
Cortex does not implement these authorization-server endpoints. Configure RS256
access tokens with the **exact public MCP URL** as their audience/resource and
`memory:read` / `memory:write` scopes. Opaque tokens and other algorithms are not
supported by this first slice. An issuer-wide scope alone does not grant access:
an operator must bind the verified subject locally.

Example operator binding (`subjects.json`; use your issuer's actual subject):

```json
{
  "issuer-subject": {
    "enabled": true,
    "profile_id": "default",
    "agent_id": "personal-assistant",
    "scopes": ["memory:read", "memory:write"]
  }
}
```

```bash
uv run xibalba-cortex-hosted-connector \
  --home /srv/cortex --surface spark --profile default \
  --resource https://memory.example.com/mcp \
  --issuer https://auth.example.com \
  --jwks-url https://auth.example.com/jwks \
  --bindings /srv/cortex/subjects.json
```

Run separate deployments/resources with `--surface perplexity` and `--surface spark`
when provenance must distinguish the assistants. Surface is configured by the
operator; it does not prove which client sent a request. Removing/disabling a
subject binding takes effect on the next request. Issuer-side JWT revocation takes
effect at token expiry unless the local binding is also disabled. JWKS rotation
uses PyJWT's maintained key client. Do not use identity mode `omit`: scoped tools
refuse operations if identities cannot be stored.

Perplexity also supports a bearer-only deployment: omit issuer/JWKS/bindings and
issue an existing Cortex ingest token with one bound agent, matching profile,
explicit read/write scopes and a short expiry. The token must reach Cortex as
`Authorization: Bearer …`. Unbound and multi-agent tokens are rejected. This mode
advertises no OAuth authorization server. The consumer UI's exact API-key header
behavior still needs a live canary; choose OAuth if it cannot send that header.
Spark requires OAuth, and the CLI rejects bearer-only Spark configuration.

## Connect and prove a real call

- Perplexity: Account settings → Connectors → Custom connector → Remote; enter
  the HTTPS `/mcp` URL, Streamable HTTP and the configured OAuth or API-key method.
- Spark: Gemini web Settings → Connected Apps → Custom Apps; enter the MCP URL,
  then complete the OAuth prompts. Use advanced credentials only if your issuer
  lacks DCR and the account offers that documented option.
- Explicitly select the connector (use `@` where offered) and ask it to invoke
  `cortex_connection_status`. A successful result includes a call ID and recorder
  session ID. A connected settings card or successful tools/list is insufficient.
- Ask it to remember a unique synthetic sentence with a unique idempotency key,
  then recall that sentence in a new conversation. Confirm the actual tool result,
  candidate status and matching Cortex recorder events. Reuse the retry key for
  the same write; a different agent's key does not collide.
- Confirm a read-only credential cannot remember, another agent cannot recall the
  synthetic sentence, and local revocation/binding removal prevents the next call.

Memory writes are redacted and remain candidates. Recall explicitly includes
candidates alongside active/confirmed memory and returns status/provenance; a
candidate is not reviewed knowledge. Retrieval uses available lexical/graph/
temporal channels without downloading an embedding model. Results report channel
availability; scores are retrieval ranks, not truth probabilities.

## Recorder boundary and validation

Each authorized tool execution records a start and end event in Cortex's existing
OTel store, with call ID, tool, outcome and operator-configured provider. Recorder
sessions are bound to the same agent identity as memory. Arguments, memory text,
query text, credential contents and exception messages are excluded from these
events. Explicit saved memories and retrieval traces still contain their respective
redacted content/query as part of the existing store contracts.

These events can be read by the existing session telemetry API/viewer. This slice
adds durable local events, **not a new live replay UI or streaming transport**.
A process crash may leave a start event without an end event. Recorder failures
fail the call; if a write already committed, retry with the same key. Invalid
credentials and authorization failures are not captured as agent execution events.
Session grouping is per bound agent/provider, not a provider conversation ID.

No hosted internal planning, browser actions, other connectors, hidden reasoning,
or complete Perplexity/Spark conversation stream is captured. Optional API-owned
recorders and Perplexity enterprise audit ingestion remain separate planned work.

Local tests use a real HTTP server, signed JWT verification with fixture public keys,
OAuth protected-resource discovery, bearer revocation, binding removal, retry
behavior, reader restrictions and cross-agent isolation. Live issuer DCR, consent,
Google/Perplexity callbacks, reverse-proxy hosting and account dispatch are still
required deployment canaries; no live account success is claimed.

Official onboarding references:
- https://www.perplexity.ai/help-center/en/articles/13915507-adding-custom-remote-connectors
- https://support.google.com/gemini/answer/17209137
- https://github.com/modelcontextprotocol/python-sdk
