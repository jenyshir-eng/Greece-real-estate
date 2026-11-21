# Telegram messages: all new Thessaloniki flats, no basements, Athens off

## Request
More Thessaloniki listings in Telegram ("send everything new"), basements still arrived despite the
"no basements" filter, Athens messages not needed for now.

## Findings
- The only Thessaloniki filter (sale flats, 20-100k EUR, 28-130 m2, floor_min 0) sent 2-19 listings per run.
- Basements passed as "floor unknown" (`keep_unknown_floor: true`): ~460 of 1166 matching properties had no
  floor, ~270 of them from Spitogatos alert e-mails, which carry no floor; spitogatos.gr is behind bot
  protection, so the page cannot be read. The Telegram script read only the floor field, while the search
  page also read the title.

## Changes
- `scripts/floors.py` (new): `floor_code` moved out of `build_search_page.py`, now used by both the page and
  `notify_telegram.py` (floor field first, then the listings' titles).
- `scripts/notify_telegram.py`: per-filter `max_items` (default 25); unknown floor of a flat shown as
  "этаж не указан"; top-level `"enabled": false` in notify_filters.json switches a city off and marks what
  appears meanwhile as sent.
- `data/sources/notify_filters.json`: new filter "all new flats / studios / maisonettes for sale, floor_min 0",
  `max_items` 300; the old budget filter kept with `enabled: false`.
- `cities/athens/data/sources/notify_filters.json`: `"enabled": false`.
- `docs/README_RU.md`: step 5 describes the current setup.
- `tests/test_notify_floors.py`: floor parsing, title fallback, basement exclusion, label.

## Verification
- `python3 -m unittest discover -s tests`: 18 tests pass. Search page builds.
- Dry run with the last day's listings marked unsent: 171 flats in 9 messages, no basement or semi-basement
  lines, 42 marked "этаж не указан". Athens dry run: switched off.

## Known limitations
- Flats with unknown floor (mostly Spitogatos alerts) can still be basements. Fix at the source: add a floor
  filter "from ground floor" to the saved Spitogatos searches that send the alert e-mails.
- First run after the change also sends the price drops of the last 3 days for all flats (51 in the dry run).
