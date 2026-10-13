# Bank (REO) and auction listings

## Request
Bank-owned and auction properties were missing from Spiti Radar (Thessaloniki and Athens).
`data/sources/auctions_servicers.csv` and `docs/TZ-v2.md` (4.2, 4.2.1) described them, but no collector existed.

## Changes
- `scripts/collect_servicers.py` (new): Altamira (doValue) and Intrum marketplaces. Both run the same
  platform with an open JSON API: `GET https://api.marketplace.<servicer>/v1/listings/search`
  `?filter_by=commercialization:=<sale|auction>&&coordinates: (<4 corners>)&page=N&per_page=100`.
  Limited to `city.BOX` (Thessaloniki default box) and `city.in_unit`. Full re-read each run;
  listings that left the list go to `data/listings/removed.csv`. If a servicer fails or returns
  < 50% of known listings, its known rows are kept. Dates are converted in Europe/Athens
  (auction dates are Athens midnight).
  Output: `data/listings/listings_servicers.csv` with extra columns `segment` (auction | bank),
  `auction_date`, `auction_round`.
- `scripts/daily_update.sh`: step `servicers` after Ktimatoemporiki.
- `scripts/normalize_listings.py`: reads the new file; carries `segment`, `auction_date`, `auction_round`.
- `scripts/build_search_page.py`: row keys `sg` (segment), `ad` (auction date), `rd` (round);
  Sources tab kind `servicer`.
- `web/search_template.html`: filter "Банки и аукционы" (all / bank+auction / auctions / bank / none);
  choosing a bank or auction view clears the default 90-day date filter (these lists are re-read in full).
  Phrases with "аукцион", "торги", "банк", "πλειστηριασμ", "auction", "bank" set the filter.
  Card badges "Аукцион · торги DD.MM.YYYY" / "Банковский", "старт" before an auction price,
  warning text and auction date/round in the detail sheet, Sources tab tile.
- `tests/test_collect_servicers.py`: row mapping, skipped rows, search URL.

## Verification
- `python3 -m unittest discover -s tests`: 5 tests pass.
- Live run 2026-10-13: Thessaloniki 489 listings (Altamira 173 auction + 30 bank, Intrum 286 bank);
  Athens 1148 (Altamira 578 auction + 58 bank, Intrum 512 bank). Intrum shows no auctions in either box.
- Built pages checked in headless Chromium: filter counts, badges, sheet text, phrase parsing; no console errors.

## Known limitations
- Only Altamira and Intrum. Cepal, Quant, iOwn and the auction platforms (eauction.gr, AADE e-auctions,
  etc.) from `auctions_servicers.csv` have no collector yet.
- Auction listings are mixed into the default list (marked with a badge, price labelled "старт");
  the "дешевле района" filter compares their starting price with the district average.
- First run adds ~500 / ~1100 new properties: the Telegram notification for saved filters is capped
  at 25 lines per message.

## Next action
Add the next servicer (Cepal or iOwn) or eauction.gr as a separate collector with the same output columns.
