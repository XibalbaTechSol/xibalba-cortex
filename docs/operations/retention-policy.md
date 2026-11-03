# Cortex retention policy

This policy defines the bounded local retention behavior for Cortex profiles. It is
an operator policy and implementation contract, not legal or regulatory advice.

## Defaults

New sessions use the `digest` tier unless the profile or recorder explicitly selects
another supported tier. The tiers describe the amount of session content retained at
capture time:

| Tier | Local pilot baseline | Intended use |
| --- | ---: | --- |
| `digest` | 30 days after session end | Default capture with bounded content |
| `synopsis` | 90 days after session end | Longer-lived summaries and evidence |
| `verbatim` | 7 days after session end | Short-lived debugging or replay |

These are conservative pilot baselines, not customer-specific retention commitments.
An operator must review them against the tenant's contract, data classification,
backup policy, and deletion obligations before applying them to a real tenant.

## Applying the policy

Retention is never applied implicitly by the server. First run a dry-run report:

```bash
uv run xibalba-cortex-operator retention-sweep \
  --max-age-days '{"digest":30,"synopsis":90,"verbatim":7}'
```

Review the candidate memory IDs, session IDs, tiers, and end timestamps. Preserve the
JSON output with the operator audit record. Apply only after an authorized operator
approves that report:

```bash
uv run xibalba-cortex-operator retention-sweep \
  --max-age-days '{"digest":30,"synopsis":90,"verbatim":7}' \
  --apply
```

The sweep is bounded (`--limit` defaults to 500 and is capped at 5,000), affects only
memories from ended sessions, and records a deletion receipt for each applied forget
operation. Re-run the dry-run after application and retain both reports. The operation
marks memories forgotten through the canonical event path; it does not claim complete
erasure from every backup, exported artifact, connector journal, or provider system.

## Operational requirements

- Keep the profile's retention tier explicit and review changes as configuration
  changes; do not treat provider-side retention as Cortex retention.
- Run the dry-run before every apply operation. Do not schedule `--apply` until the
  deployment has an approved tenant-specific policy and restore/deletion procedure.
- Backups and exports require their own retention and access controls. Deleting a
  memory from the live profile does not automatically remove existing backup or export
  copies.
- Record the command, profile/tenant, policy JSON, candidate count, deletion receipts,
  operator identity, and timestamp in the local audit trail.
- This policy does not establish encryption at rest, hard purge from all replicas, a
  legal hold workflow, or compliance certification. Those remain separate production
  gates.

## Verification

The implementation contract is `xibalba.retention_sweep.v1`. The sweep validates tier
names and non-negative integer ages, includes only ended sessions, supports dry-run
planning, and preserves deletion receipts when applied. Use the profile's normal audit
and backup verification commands after a sweep; do not infer external or hosted
production evidence from a local run.
