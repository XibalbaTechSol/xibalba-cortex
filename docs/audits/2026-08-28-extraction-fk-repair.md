# Extraction proposal FK repair

Date: 2026-08-28

## Defect

The v8 task-table migration caused SQLite to rewrite the `extraction_proposals.task_id`
foreign key to the temporary table `memory_inference_tasks_v8`. The temporary table was then
dropped, while the live task table remained `memory_inference_tasks`.

## Repair

Schema version 12 adds an idempotent migration check. When the proposal FK targets anything
other than `memory_inference_tasks`, it rebuilds `extraction_proposals`, preserves all rows,
and recreates its indexes. The repair is also detected on every store open so a database that
already recorded the previous schema version is repaired.

## Evidence

- Pre-repair SQLite online backup: `/home/xibalba/.hermes/xibalba-cortex/backups/cortex-pre-fk-repair-20260828.sqlite3`
- Backup integrity: `ok`
- Live schema version after repair: `12`
- Live `extraction_proposals.task_id` FK: `memory_inference_tasks`
- Live store integrity: `ok`
- Live foreign keys: enabled
- Fresh bounded rerun task: `226473ae-5064-478a-a38e-d07046034455`
- Historical task: `a693b75f-01d9-497b-864f-ffafffc3b06a`
- Accepted proposal: `226473ae-5064-478a-a38e-d07046034455:0`
- Accepted relation: `dashboard-demo telemetry exercise --HAS_UNAVAILABLE_CAPABILITY--> kernel-bridge self-test`
- Source evidence quote: `Kernel-bridge self-test cases were not run because no such exposed tool was discoverable.`

The relation was created only through validated extraction completion and explicit proposal
acceptance; no manual relation insert was used.
