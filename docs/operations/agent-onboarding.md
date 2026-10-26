# Agent onboarding: one identity, two memory transports

Users should not have to choose between MCP identity and SDK identity. Both
transports use the same local `did:integrity:…` identity and the same managed
workspace key. The recommended onboarding path is:

1. **Provision one DID per agent runtime.** The CLI/SDK creates or imports the
   Ed25519 key under the user’s Integrity DID home and writes only the public
   `agent.did.json` into the selected Cortex profile. Never generate a new DID
   for every session or memory.
2. **Create one workspace key bound to that DID.** In the managed workspace,
   use **Connect an agent**, enter the DID, and create a 30-day key. The raw key
   is shown once. A key may be used by either MCP or the SDK, but its writes are
   attributed to the bound DID.
3. **Choose a transport.**
   - **MCP:** configure the host with the Cortex `/mcp` endpoint and the bearer
     key. Run `cortex_connection_status`, then write and recall one synthetic
     canary with a stable idempotency key.
   - **SDK:** initialize the Cortex client with the same endpoint, bearer key,
     and DID. Wrap `remember`/`recall` calls in the SDK helper so idempotency,
     redaction, and provenance are consistent with MCP.
4. **Verify the connection.** A successful setup must show the DID in the
   connection status and in the memory source metadata. A settings card or a
   generated config file alone does not prove a working connection.
5. **Revoke and rotate.** Revoke a lost key from the workspace, issue a new key
   for the same DID, and keep the DID stable. Rotate the DID only when the
   agent’s signing key is intentionally replaced or the runtime is permanently
   retired.

## What the CLI should automate

The planned `cortex connect` wizard should perform steps 1–3 and emit two small
artifacts: an MCP host snippet and an SDK `.env`/code snippet. It should default
to local DID provisioning and require an explicit `--register` confirmation for
any Oracle or on-chain registration. Creating a DID is local key management;
registering an agent with a network is a separate, potentially irreversible
operation and should never happen as a hidden side effect of connecting memory.

## What the SDK should automate

The SDK helper should accept an existing DID document and key, expose
`remember(content, idempotency_key=...)` and `recall(query)`, and return the
server’s provenance/status fields unchanged. It should not mint a second DID,
silently fall back to an anonymous identity, or capture an agent’s full
conversation without an explicit recorder/observer opt-in.

This separation gives users one mental model: **one agent, one DID, one
workspace key, MCP or SDK as the transport**.
