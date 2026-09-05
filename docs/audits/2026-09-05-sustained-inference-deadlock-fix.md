# Sustained-load worker deadlock: root-caused and fixed

Date: 2026-09-05

Closes the open finding recorded in `docs/PROJECT_STATE.md` on 2026-09-04:
`xibalba_cortex.tenant_inference_validation` hung reproducibly (three
separate runs) at 200 tasks/process while 50-150 completed cleanly and fast.

## Root cause

Not a task-processing bug, not a `busy_timeout` misconfiguration, and not
cumulative row growth from reusing test profiles across calibration attempts
(all three were suspected and ruled out in the earlier investigation).

`validate_process_inference()` used to join every worker process **before**
draining `result_queue`. `multiprocessing.Queue` writes through a background
`QueueFeederThread` into a bounded OS pipe; the Python standard library docs
explicitly warn that a child process which has `put()` enough data onto a
queue will not finish exiting until that data is flushed to the pipe — so
joining before draining can deadlock exactly this way if the reader (the
parent process) isn't concurrently consuming.

## How this was actually found, not guessed

Added lightweight heartbeat instrumentation directly to `_inference_worker`:
a small JSON file written after every sub-operation (`store_memory`,
`request_inference_task`, `claim_inference_task`, `complete_inference_task`,
the queue `put`, and `store.close()`), readable from outside the process
while it's still running. Re-ran the exact failing case (200 tasks/process,
fresh tenant profiles to rule out cumulative-size as a factor) and inspected
the heartbeats of the still-alive processes mid-hang:

- Every one of 8 workers' heartbeats showed `store_close:done` — every piece
  of real application work, including the queue `put()` and the store close,
  had already completed successfully.
- `ps -eLo` showed 2-3 of the underlying OS processes still alive, actively
  consuming CPU (not blocked/idle), well past when their own heartbeats
  proved they were done.
- Added one more targeted probe (`threading.enumerate()` right before the
  worker function returns): one process was caught with a live
  `QueueFeederThread` still running — `multiprocessing.Queue`'s own internal
  feeder thread, not anything this codebase wrote.

This pinned the hang to Python's own subprocess/interpreter-exit machinery,
specifically the queue's feeder thread, not to any application-level lock,
query, or the previously-fixed `busy_timeout` path.

## The fix

`validate_process_inference()` now drains `result_queue` (up to
`len(processes)` items, bounded by the shared timeout deadline) **before**
joining any process object. Draining does not require the producer to have
exited, so this unblocks a stuck feeder thread; the subsequent join then
completes quickly for any process that had actually finished its work. A
second, independently real bug from the same investigation was fixed in the
same change: the join loop previously gave each process its own full
`timeout_seconds` budget sequentially rather than sharing one deadline,
which would have hidden completion the same way even with correct queue
draining.

## Verification (real, not synthetic)

- 200 tasks/process (1,600 total tasks, 8 processes, 2 fresh profiles):
  previously hung for the full timeout on three separate attempts; now
  completes in ~16 seconds, `passed: true`, all 8 exit codes clean, zero
  timeouts.
- 1,000 tasks/process (8,000 total tasks — 40x the original 25-task burst
  this whole investigation started from): completes in ~75 seconds,
  `passed: true`, all checks pass, zero timeouts.
- `tests/test_tenant_inference_validation.py` gained an opt-in regression
  test (`XIBALBA_RUN_SUSTAINED_INFERENCE_DRILL=1`, ~18s) at the exact scale
  that reliably reproduced the deadlock before the fix.
- Full `uv run pytest -q` passes clean.

## What this closes

Closes the "Open finding" in `docs/PROJECT_STATE.md` and genuinely closes the
original checklist item ("sustained inference workload, not only short
validation bursts") that this whole investigation traces back to — the
earlier 200-task attempts never actually got a passing result at that scale
until this fix. Workstream A/G "sustained workload" verification may now be
considered locally passed.
