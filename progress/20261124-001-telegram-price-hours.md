# Telegram: flats up to 130 000 EUR, three messages a day

## Request
Thessaloniki Telegram messages only for flats up to 130 000 EUR, and only three times a day
(morning 9-10, lunch, evening) instead of after every update.

## Changes
- `data/sources/notify_filters.json`: the Thessaloniki filter now has `price_max` 130000 (flats, studios,
  maisonettes for sale, no basements); new top-level `send_hours` [9, 10, 11, 13, 14, 15, 17, 18, 19].
- `scripts/notify_telegram.py`: `sending_now()`: a run outside `send_hours` (Athens time) sends and records
  nothing, so the next sending run carries its news. Dry runs ignore the hours.
- `docs/README_RU.md`: step 5 updated.
- `tests/test_notify_floors.py`: send hours, price limit (dearer and unpriced flats dropped).

## Decisions
- Updates still run 4 times a day from cron-job.org (about 09:30, 13:30, 17:30, 21:30 when they finish), so
  the site stays fresh; only the 21:30 run is silent. cron-job.org is outside the repository.

## Verification
- `python3 -m unittest discover -s tests`: all tests pass.
- Dry run for 2026-11-24: 21 flats up to 130 000 EUR in 2 messages.
