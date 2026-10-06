# Runtime and plugin canary evidence

Checked 2026-10-06 on `feat/cortex-runtime-and-plugins`, PR #43. Release remains
blocked on the live account checks below. Native package validation, backend
connectivity and provider fixtures establish different kinds of evidence.

## Checks completed

| Check | Result and boundary |
| --- | --- |
| PR #43 original backend CI | Passed at `3a6a316660629b071ec9279d1bf84966b7191e27`, Actions run `37464013432` |
| PR #43 original package CI | Passed at the same head, run `37464013472`; non-expired `cortex-plugins-0.1.0` artifact present |
| Local Python regression after review fixes | 603 passed, 2 opt-in skips, 2 existing warnings; CI-pinned SDK `4ddaae1965635224958e147f6eaaead06e3cdc41` |
| Archive reproducibility | Two independent builds had identical SHA256SUMS; no generated manifest drift |
| Claude Code 2.1.291 | Native plugin and marketplace validation passed with advisory naming/description warnings; isolated catalog add, install and list succeeded |
| Codex CLI 0.159.0-alpha.3 | Local catalog add, available listing, install, enabled listing, uninstall and catalog removal succeeded; user catalog configuration restored |
| Gemini CLI 0.62.0 | Root and packaged manifests validated; native Git installation from the pilot branch succeeded; Cortex home configured through the native setting prompt |
| Installed Cortex stdio backend | Initialized, discovered 81 tools, and invoked `memory_status` successfully in the temporary profile with a validated public DID binding |

Native CLI installation/listing does not establish interactive UI menu visibility,
hook trust, actual host callbacks or model-triggered MCP dispatch. The stdio check
was a direct MCP client invocation. No model was launched or billed for these checks.

The review fixed oversized unterminated SSE buffers, JSON string secret-key
redaction, structured metadata ingestion, stale-state regression, and returning an
unrelated newest journal row during concurrent appends. Plugin doctor/setup now
identify the required agent identity source; the backend validates the DID file.
Frozen GraphStore/receipt/memory schemas are unchanged.

## Temporary pilot

This workspace has `/workspace/scratch/cortex-pilot/profile` with metadata-only
Perplexity telemetry consent, a temporary public DID binding and a minimal request
file. This identity is for local connectivity, not an on-chain registration or a
replacement for a customer's operational identity. Scratch files, credentials,
identity bindings, installed native caches and databases are not release artifacts.

The temporary activation script selects the profile, installed backend and isolated
Claude/Gemini configuration roots:

```bash
source /workspace/scratch/cortex-pilot/activate.sh
```

Codex's catalog/install check was cleaned up afterward; reinstall the plugin on the
chosen interactive pilot client before checking trust and callbacks. Claude and
Gemini scratch installs remain available. Use the native Git installation path for
Gemini: local directory installation from a development checkout also copies
untracked environments and build files. Its home setting was configured explicitly.

## Remaining release gates

| Gate | Required access and acceptance evidence |
| --- | --- |
| Perplexity Agent API | Privately configured API credential and billing access; real background event shapes, durable reconnect after restart, provider sequence variants, asynchronous cancellation, tool output and usage/account limits |
| Claude/Codex hosts | Authenticated interactive pilot client; explicit Codex `/hooks` trust; real memory invocation, benign prompt/tool callbacks and corresponding persisted observer receipts; no duplicate observer installation routes |
| Gemini host | Authenticated client with Cortex home configured; real `memory_status` dispatch and namespace isolation; no full native observer claim |
| Perplexity/Spark consumer connectors | Operator HTTPS MCP endpoint, principal-scoped credentials and actual account dispatch; Spark also needs external issuer/DCR/consent; synthetic cross-conversation memory, read-only denial, revocation and cross-profile denial |
| Official marketplace/directory listings | Separate submission, review and listing evidence; source catalogs and successful installation do not imply official approval |

The environment reported no configured Perplexity credential, OAuth issuer/account
binding or deployed consumer endpoint. No paid provider request or public deployment
was attempted. Configure credentials through the environment's private secret
workflow; do not paste them in chat, command arguments, payloads or evidence files.

Once API access is provisioned, resolve the public DID from the selected profile
and use `perplexity-runtime-recorder.md` for `start`, `status`, `resume`, `cancel`,
`snapshot` and `replay`. Start with the minimal scratch request (no remote tools,
32 output tokens). Record sanitized event type/sequence coverage and account limits.
Then test one explicitly reviewed harmless provider tool; remote MCP actions may
execute automatically. Stop if creation outcome is uncertain; never retry POST
creation blindly. Capture synthetic identifiers and fixed pass/fail classifications,
not raw provider/user content. Use a fresh run ID for each distinct canary.

For consumer account checks follow `hosted-memory-connectors.md`. An HTTPS URL,
OAuth discovery result or connection card alone is insufficient: verify the actual
authenticated Cortex tool invocation and stored attribution independently.
