# Native hook installation and evidence

Verified locally on 2026-09-15 (America/Chicago). These integrations collect
telemetry; their presence does not certify tool enforcement, Oracle acceptance,
or on-chain registration.

## Agy

Source: `plugins/agy-cortex/`. Installed using:

```sh
agy-bin plugin validate plugins/agy-cortex
agy-bin plugin install /home/xibalba/Projects/xibalba-cortex/plugins/agy-cortex
agy-bin plugin list
```

Commands pin this workstation's Cortex virtualenv and canonical graph home.
They invoke `xibalba_cortex.agy_hook_bridge` for `PreInvocation`,
`PostInvocation`, `PostToolUse`, and `Stop`. The bridge translates the native
camelCase fields, hashes tool arguments, and omits raw error bodies. It sends
only the hook protocol response to stdout; delivery counts go to stderr.
No PreToolUse decision hook is installed by this plugin.

Stop ends an execution attempt, not a resumable conversation. Initially calling
session finalization here exceeded the hook timeout on the live store. The
bridge now records Stop without building session exchanges.

Live tool canary: `21e39463-92ec-4053-b836-f15051a4b93e` persisted a successful
`view_file` callback and pre/post-model events. After the Stop correction,
`fd19984e-94ec-46ae-aabb-30d2e7b7eec1` persisted PreInvocation,
PostInvocation, and Stop; Agy logged successful command delivery and returned
`AGY_STOP_CANARY_OK` without the earlier timeout.

Disable with `agy-bin plugin disable agy-cortex`. Reinstall the source bundle
after changing hook configuration. The referenced Python module is loaded from
the checkout on each invocation.

## Hermes

Hermes supports native Python `register(ctx)` / `ctx.register_hook(...)`
callbacks, config shell hooks, and separate gateway hooks. Observer callbacks
receive additive keyword payloads and correlation IDs. Pre-tool callbacks can
block or modify execution; approval observers cannot approve requests.

This host already has the enabled standalone plugin
`~/.hermes/plugins/xibalba_cortex/`, declaring 21 hook types. It forwards to
`xibalba_cortex.hermes_bridge` using the Cortex virtualenv and preserves its
existing memory-provider coordination. No duplicate telemetry plugin was added.

Implemented corrections:

- Outbox claims target the current event ID; a backlog cannot cause the bridge
  to lease an unrelated event and leave the actual delivery unacknowledged.
- `on_session_end` records `hermes.run_end`; final session cleanup remains owned
  by the existing finalization path. Hermes emits run-end for resumable turns.
- The installed plugin defaults to a 16 MiB outbox cap (explicit environment
  overrides still win). The live 16 MiB queue was full; existing records were
  preserved. Archive/retention and sustained-load testing remain open.

Live canary `20260915_204246_a9a96e` returned `HERMES_DELIVERY_CANARY_OK`.
The live graph contains API spans and successful `read_file` tool telemetry;
the outbox contains nine Cortex acknowledgements covering session start,
turn start, two API attempts, pre/post tool, and finalization.
These receipts establish Cortex delivery, not Integrity SDK/Oracle delivery.

The installed CLI lacks `plugins doctor`; its enabled-plugin listing, real
chat invocation, graph events, and outbox acknowledgements provide validation.
Already-running Hermes processes need a new session/process to load changed
plugin code. Cortex bridge modules load on each subprocess invocation.

## Primary references

- [Agy plugin installation](https://antigravity.google/docs/cli/plugins)
- [Agy hook schema and I/O](https://antigravity.google/docs/hooks/)
- [Hermes plugin architecture](https://hermes-agent.nousresearch.com/docs/developer-guide/plugins)
- [Hermes observer semantics](https://hermes-agent.nousresearch.com/docs/developer-guide/observer-hooks)

Local source was checked because the installed Hermes CLI does not implement
all commands shown in the current online documentation.
