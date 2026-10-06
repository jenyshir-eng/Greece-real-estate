# Spiti Radar: scheduled runs were skipped as too late

## Requested
Check the GitHub run of Spiti Radar; widen the lateness tolerance.

## Finding
Scheduled runs on 2026-10-05/06 (22:11, 22:36, 01:29 UTC) started far later than their cron time.
The plan step allowed only 55 minutes of delay, so the run job was skipped every time.
The only real scan so far was a manual workflow_dispatch (Thessaloniki, 2026-10-05).

## Change
.github/workflows/spiti-radar.yml, plan step:
- tolerance 55 -> 180 minutes
- each cron fires at two UTC hours one hour apart; with a wider tolerance both would run, so the
  first firing now claims a tag slot-YYYYMMDD-HHMM-<job> (created once through the API) and the
  second firing is skipped. If the tag cannot be created for another reason, the run proceeds.
- GH_TOKEN added to the step env for the API call.
- workflow_dispatch runs never claim a slot.

## Verification
YAML and bash syntax checked; plan logic simulated for 2h late, duplicate firing, 4h late.
Not yet observed on real scheduled runs.

## Next
After the 10:13 and 10:43 (Athens) runs on 2026-10-06, check that the run job executed once per slot
and that slot-* tags exist.
