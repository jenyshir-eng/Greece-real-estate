# Agency sites that refuse GitHub runners: daily collection from a Claude cloud session

## Request
Many sites "did not answer" in the update report. Find out why; owner chose to collect them from a
Claude cloud session once a day.

## Findings (2026-11-21, Thessaloniki)
- 31 of 254 agency sites failed in CI (URLError / RemoteDisconnected / HTTPError, no detail in the report).
- From this network 29 of them open normally (reCAPTCHA on contact forms only, no bot check):
  20 on the e-agents platform (failing in every run since at least 2026-10-22), 9 on the Spitogatos site
  builder (failing since about 2026-11-15), anastasiouproperties.gr (since 2026-11-18).
- vogkoli-realestate.gr (self-signed certificate) and ai-golden.com (down) fail everywhere: left in CI.
- 16 of the agencies had no listings through XE or portals; 795 stale listings of the Spitogatos-builder
  sites stayed in the base unchecked.

## Changes
- `scripts/collect_listings.py`: `--skip-domains FILE` (not collected, and dropped from the outputs) and
  `--out-dir DIR` (listings.csv, collect_report.csv, not_listings.txt, removed.csv in DIR); domain files allow
  `#` comments; a missing report file no longer breaks a `--domains` run.
- `data/sources/cloud_sites.txt` (new): the 29 sites.
- `scripts/daily_update.sh`: agencies step skips them.
- `scripts/cloud_collect.sh` (new): run on main, collect the list into `data/cloud/`, commit, push to main
  (rebase on a race; only `data/cloud/` is touched).
- `scripts/normalize_listings.py`: reads `data/cloud/listings.csv`; `scripts/build_search_page.py`: Sources
  tab also reads `data/cloud/collect_report.csv`.
- `data/cloud/listings.csv`: seeded with the 836 known listings of these sites, then collected from here.
- `docs/README_RU.md`: section 11.
- `tests/test_collect_cloud_split.py`: GitHub run drops cloud sites; cloud run writes only its folder.

## Verification
- `python3 -m unittest discover -s tests`: all tests pass.
- First collection run from this session: see the commit "Cloud collection ..." on main.

## Next action
Daily Routine (fresh cloud session) runs `scripts/cloud_collect.sh` before the morning GitHub update.
