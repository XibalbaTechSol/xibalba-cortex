# Storage architecture decision — controlled Cortex pilot

**Date:** 2026-09-04  
**Status:** Accepted for L1 controlled pilot; revisit before L2 production  
**Scope:** Cortex profile-bound tenant stores

## Decision

Retain SQLite with one database per tenant profile for the controlled pilot. Each
profile has its own `config.yaml`, `graph-memory.sqlite3`, credential store, and
quota boundary. The local API must load the configured profile identity and quotas;
it must never open a tenant database as the default profile.

Backups use SQLite's online-backup API, are written with mode `0600`, and are
verified with both `PRAGMA integrity_check` and domain-separated canonical Merkle
reconciliation across memories, entities, and relations. Restore verifies the
source before replacing the profile database. The operator must drill backup and
restore independently for every tenant profile; a whole-directory copy is not an
acceptable tenant backup.

## Why this decision

SQLite is already the tested canonical store, supports WAL and concurrent readers,
and gives the pilot a small, inspectable failure domain per tenant. A managed
Postgres (or compatible service) is the likely L2 direction for HA, PITR, shared
operations, and larger concurrent workloads, but choosing it now without real
pilot traffic would be an assumption rather than evidence.

## Explicit limits and triggers

This decision does **not** claim SaaS HA, PITR, multi-region durability, or an
availability SLA. Reconsider the backend before L2, or earlier if any of these
occur: sustained write contention beyond the documented SQLite ceiling, a need for
cross-instance failover, a tenant requiring PITR, or pilot load that cannot meet
the agreed latency/error budget on one instance.

## Per-tenant backup/restore drill

For each provisioned profile:

1. Write a tenant-unique sentinel memory.
2. Run `xibalba-cortex-operator backup` (or `GraphStore.backup`) to a profile-
   specific destination and require `integrity_check == "ok"` and reconciliation
   `equal == true` for all domains.
3. Write a second sentinel after the backup.
4. Restore that profile from its backup and verify the pre-backup sentinel remains
   while the post-backup sentinel is absent.
5. Run the profile's integrity/readiness check and record the result, profile id,
   backup path, schema version, and timestamps in append-only pilot evidence.

The drill proves recovery of that profile's canonical store only. It does not prove
cross-tenant backup isolation, external storage durability, or production HA; those
remain L2/Gate 7 work.

## Consequences

- Pilot operations remain simple and profile-local.
- Backup scheduling, encryption-at-rest, off-host retention, and restore automation
  are deployment responsibilities still to be implemented.
- A future backend adapter must preserve profile identity, append-only events,
  provenance, and the existing backup/reconciliation evidence contract.
