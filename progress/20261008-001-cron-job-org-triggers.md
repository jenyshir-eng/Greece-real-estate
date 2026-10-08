# Spiti Radar: updates triggered from cron-job.org

## Requested
Scheduled GitHub runs started hours late or not at all (the 10:13 and 10:43 runs on 2026-10-08 never
appeared by 12:55). Use an external scheduler instead and drop the GitHub schedule for updates.

## Changed
- .github/workflows/spiti-radar.yml: removed the schedule entries for the updates (10:13, 10:43,
  14:13) and for both watchdog runs (15:43, 23:43). Only the weekly agency search
  (Sunday 03:13, cron "13 0,1 * * 0") stays on the GitHub schedule.
- Outside the repo: two cron-job.org jobs POST to
  /repos/jenyshir-eng/Greece-real-estate/actions/workflows/spiti-radar.yml/dispatches with
  {"ref":"main","inputs":{"job":"update","city":"thessaloniki"|"athens"}}.
  Schedule 13 8,12,16,20 (Thessaloniki) and 43 8,12,16,20 (Athens), Asia/Jerusalem.
  Auth: fine-grained GitHub token, Actions read and write on this repository only,
  expires 2027-10-07 (renew before then).

## Decisions
- workflow_dispatch runs never claim a slot tag, so the plan step needs no change; the slot logic
  for schedule events stays for the weekly run.
- The watchdog is no longer scheduled. It can be re-added as a third cron-job.org job
  (43 23 * * *, inputs job=watchdog, city=both) or run manually.

## Verification
- cron-job.org test runs returned 204 and created runs 20 (Thessaloniki) and 21 (Athens).
- Scheduled firings at 16:13 and 16:43 (Athens) created runs 22 and 23 on time.
- YAML parsed; schedule contains only the weekly entry.

## Next
After the 20:13 and 20:43 runs, confirm both appear in Actions and commit new data.
Optionally add the watchdog job in cron-job.org.
