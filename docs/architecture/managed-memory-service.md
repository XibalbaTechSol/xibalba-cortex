# Managed Cortex: subscription and tenant foundation

Decision date: 2026-10-25. One repository, two service entry points. The local edition
continues to run its existing API and BYO inference. The managed edition runs
`python -m xibalba_cortex.managed.api` with a separate identity database,
subscription/usage database, and memory store per tenant.

The user selected a free hosted tier plus two paid tiers, priced in USD at
$0 / $29 / $149 per month, and explicitly requested dummy Stripe credentials for
this development phase. No real Stripe resources, charges, or cloud deployments
are created by this implementation. Licensing is unchanged.

## Initial catalog

| Plan | Monthly USD | Stored memories | Write requests per UTC month | Retrieval requests per UTC month |
|---|---:|---:|---:|---:|
| Free | $0 | 1,000 | 250 | 1,000 |
| Pro | $29 | 25,000 | 5,000 | 25,000 |
| Team | $149 | 250,000 | 50,000 | 250,000 |

Prices were selected by the user. The initial limits are conservative engineering
allowances, configurable in `managed/plans.py`, pending measured storage and compute
costs. All plans support tenant-isolated storage, hash-chained memory events, lexical
retrieval, scoped API keys and data export. Each memory is capped at 16 KiB of UTF-8
content; the entire request is capped at 64 KiB. Limits count requests/attempts,
including failed backend operations after quota reservation. Repeating a write with
the same idempotency key and identical input does not consume another request.

Team currently means higher capacity in one owner-controlled workspace. Shared user
seats and invitation/RBAC workflows are not implemented and are not advertised.
Hosted inference, embeddings, and their workers are disabled. Managed customer
requests never inherit the operator's Hermes worker profile or paid inference keys.

## Boundaries

```
Browser or scoped agent key
  -> managed API (cookie/CSRF or bearer auth)
  -> verified account -> server-owned tenant ID
  -> subscription entitlement + transactional usage reservation
  -> tenants/t-<UUID>/graph-memory.sqlite3

Stripe Checkout / Portal
  -> signed webhook -> retrieve current Stripe subscription
  -> validate known customer and approved price -> entitlement projection
```

The control plane is outside the frozen canonical memory schema. Tenant IDs are
server generated, not accepted from request parameters or Stripe metadata. Account
sessions and API keys are centrally authenticated; a machine key cannot perform
billing, mint keys, or administer accounts. Verification links and password-reset
tokens are hashed and expire. Password reset revokes account sessions. API keys
expire after 30 days and can be revoked immediately.

Quota counters are updated under `BEGIN IMMEDIATE`, preventing concurrent quota
bypass. Usage is reserved before storage work, so a crash may consume an attempted
request but cannot create unaccounted unlimited writes. A per-tenant write lock also
serializes the stored-memory capacity check and insert across request connections
in the single worker. Memory writes also use the store's existing idempotency key. Reservations and canonical memory writes span two
SQLite databases; this is not a distributed transaction. A request already authorized
may complete while billing state changes.

Checkout creation has a persisted attempt ID and Stripe idempotency key. An open
checkout is reused rather than creating another subscription. Existing subscribers
change plans through the Stripe customer portal. Customer IDs and Price IDs are
server-owned; the browser submits only `pro` or `team`. Catalog amounts, interval,
and currency are validated before creating Checkout and before granting access.

Webhook signatures cover the raw body, expire after five minutes, and must match
test/live mode. Event IDs are deduplicated. Current subscription state is retrieved
from Stripe instead of trusting event arrival order. Events for unrelated customers
or products never grant access. Known nonpaying subscription states and expired paid
periods are read-only. Cancellation scheduled for the end of a paid period preserves
access through that period. Cancellation does not delete or silently downgrade data.

Paged and streamed memory exports remain available to read-only subscribers.
Streaming bounds server/browser memory; exports currently page the live store, so
pause ingestion when a point-in-time-consistent export is required. These exports
contain memory records; use the local provenance-bundle surface for full evidence
bundles. Bulk export is not yet a managed backup/restore service.

## Deployment model

This first version is a single service replica with one worker and a persistent
volume. Use a VM/container host with durable storage and TLS termination. Do not deploy
SQLite to ephemeral Cloud Run/serverless storage or run multiple replicas over one
volume. A GCP project is configured locally, but no public managed domain or deployment
target was selected; no billable infrastructure has been provisioned.

The container build uses a repository-scoped context and a separate SDK context,
excludes local credentials/data, prunes the worker-specific ML stack, runs as a
non-root user, drops Linux capabilities, and mounts only managed data writable.
Docker Compose is a local deployment template, not proof of cloud availability or HA.

## Phases and boundary challenges

1. **Foundation (this change):** isolated account/memory service, the three-tier
   catalog, strict quotas, billing lifecycle code, account recovery, and a managed
   web workspace. Evidence: Python integration tests, browser tests, and a local
   service smoke test. Dummy keys deliberately leave paid checkout unavailable.
2. **Private hosted pilot:** select domain/region/host; configure SMTP and actual
   Stripe sandbox keys/products/portal/webhook; exercise the real Checkout flow and
   backup/recovery; measure cost per retained memory and request before launch.
3. **Metered inference and retrieval:** add a separately configured hosted provider,
   token/cost reservations, isolated workers, embeddings, and managed MCP access.
   Do not turn on unlimited model calls behind the free tier.
4. **Team collaboration and scale:** implement membership/invites/roles before
   offering seats; establish durable control-plane storage, a tested migration path,
   disaster recovery and availability targets before multi-replica/HA claims.

Devil's Advocate checks driving this sequence:

- Can a customer name another tenant/profile or forge a billing identity? Membership
  and a server-generated path are checked; request profile selectors grant no access.
- Can concurrent writes or retries bypass limits? SQL reservation and content-bound
  idempotency are tested independently of the UI.
- Can a browser redirect, replay, or old event unlock paid capacity? Redirects grant
  no access; only verified events plus current provider state update entitlements.
- Can a cheap/foreign Stripe price buy a more expensive tier? Server price mapping,
  USD/monthly amount checks, and customer binding are tested before access changes.
- Can cancellation destroy or strand the customer's data? New writes stop; read and
  export continue. A production retention policy still needs a separate decision.
- Can a free account trigger paid inference or consume arbitrary storage? Inference
  is off; monthly writes, stored memories, body size, signup capacity and rate limits
  are bounded. Volume monitoring and a measured operating budget remain pilot gates.

## Primary integration references

- [Stripe Checkout Sessions](https://docs.stripe.com/api/checkout/sessions/create)
- [Stripe webhook verification and delivery](https://docs.stripe.com/webhooks)
- [Stripe subscription lifecycle](https://docs.stripe.com/billing/subscriptions/overview)
- [Stripe customer portal](https://docs.stripe.com/customer-management/integrate-customer-portal)
- [Docker named build contexts](https://docs.docker.com/reference/compose-file/build/#additional_contexts)
