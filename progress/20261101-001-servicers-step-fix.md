# Thessaloniki search check; servicers step failing in CI

## Request
Check the Thessaloniki search (radar.jenyshir.com).

## Findings (2026-11-01, live site, headless Chromium)
- Page loads (12 MB, ~6 s), updated 01.11.2026, 47 789 listings; no console errors; no horizontal scroll at 390 px.
- Phrase search, filters, sort orders, bank / auction filter and detail sheet work.
- The `servicers` step has failed in every CI update since 2026-10-14 10:34Z (Thessaloniki and Athens):
  reinvest.gr closes the connection to GitHub Actions runners (`http.client.RemoteDisconnected`), which
  `collect_servicers.py` did not catch, so the whole step crashed and Altamira / Intrum data stayed as of
  2026-10-14; Cepal / REauction never reached the site. Locally (other network) all four sources work.
- "Частные владельцы" filter is always empty: no current source marks private owners
  (`private_owner` comes only from `collect_xe_listings.py`, which is not in the daily pipeline). Pre-existing.
- Area outliers: 2 apartments / maisonettes over 1 000 m2 (thehacienda.gr 18 000 m2, grekodom.gr 8 000 m2)
  lead the "area" sort. Pre-existing.

## Changes
- `scripts/collect_servicers.py`: a source failing with any `OSError` / `http.client.HTTPException`
  keeps its known rows and the other sources are still saved.
- `tests/test_collect_servicers.py`: regression test (fails before the fix).

## Verification
- `python3 -m unittest discover -s tests`: 13 tests pass; the new test fails with the old except clause.

## Known limitations
- reinvest.gr / reauction.gr still refuse GitHub Actions runners: Cepal listings stay missing from CI runs.
  Not worked around (project rule: no bypassing of site protection).

## Next action
Merge to main; after the next update confirm Altamira / Intrum refresh (`failed_steps` empty or only Cepal warnings).
