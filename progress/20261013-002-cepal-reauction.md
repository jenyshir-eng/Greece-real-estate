# Cepal (reinvest.gr) and REauction (reauction.gr)

## Request
Add Cepal and eauction.gr to the bank / auction listings.

## Findings
- Cepal has no listings on cepal.gr; its REO properties are sold on reinvest.gr. reinvest.gr links
  reauction.gr, an e-auction listing site for all of Greece. Both run the e-agents platform and allow
  crawling in robots.txt.
- eauction.gr: robots.txt is `Disallow: /` for all agents. Not collected (project rule: robots.txt is respected).

## Changes
- `scripts/servicers_eagents.py` (new): for each site, `map-results?aim=N&<box>` (JSON id, lat, lon, price)
  plus `properties-list?aim=N&<box>&pageSize=50&page=P` (HTML cards: place, type, size, price, bedrooms,
  auction date, round, ownership share). aim 1 = sale (reinvest, segment bank), aim 3 = auction (reauction).
  Partial-ownership auctions get "(μερίδιο N%)" in the title. No listing dates on these sites.
- `scripts/collect_servicers.py`: runs the marketplace servicers and the two e-agents sites as one list of
  sources with the same failure / removal handling; `fetch_text` shared.
- `scripts/build_search_page.py`, `web/search_template.html`: source names and Sources tab texts.
- `data/sources/auctions_servicers.csv`: reinvest.gr and reauction.gr rows; eauction.gr marked as closed by robots.txt.
- `tests/test_servicers_eagents.py`: card parsing for both sites, skipped rows.

## Verification
- `python3 -m unittest discover -s tests`: 8 tests pass.
- Live run 2026-10-13: Thessaloniki reinvest 234, reauction 104 (total 827 with Altamira and Intrum);
  Athens reinvest 929, reauction 230 (total 2307).
- Pages built and checked in headless Chromium, no console errors. Apartments in the filter "Банки и аукционы":
  Thessaloniki 281 (96 auctions), Athens 1053 (353 auctions).

## Known limitations
- reinvest / reauction listings have no publication date: they show "найдено <first seen>".
- Same property on reauction and Altamira is merged only when price and area match (3 such groups in Athens).

## Next action
None required. Remaining servicers without a collector: Quant, iOwn; AADE e-auctions not checked.
