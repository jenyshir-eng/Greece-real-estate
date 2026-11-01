# eauction.gr and AADE e-auctions check

## Request
Connect eauction.gr after confirming that its generic robots.txt ban does not apply under the
project rule (TZ section 2, item 4: only a ban for `User-agent: SpitiRadar` excludes a site).

## Findings (2026-10-16)
- eauction.gr: home page opens, but the auction search (`/Home/HlektronikoiPleistiriasmoi`) returns
  an Imperva / Incapsula block page (HTTP 403, incident ID). Project rule: sites behind Imperva,
  Cloudflare or other bot checks are not collected directly. Not connected.
  The earlier note (progress/20261013-002-cepal-reauction.md) gave robots.txt as the reason; that was
  wrong under the project rule, the real blocker is Imperva.
- eauctions.gsis.gr (AADE): auctions for concessions of beach / seashore use, not property sales. Not relevant.
- Auctions stay covered through Altamira (doValue) and reauction.gr.

## Changes
- `data/sources/auctions_servicers.csv`: notes for eauction.gr and eauctions.gsis.gr corrected.

## Next action
None.
