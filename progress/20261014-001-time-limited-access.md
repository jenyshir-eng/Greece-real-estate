# Time-limited access links

## Request
Give someone access to Spiti Radar for a day without having to revoke it by hand.

## Changes
- `functions/_middleware.js` (new): Cloudflare Pages Functions middleware, applies to both city projects
  (both build from the repository root). Key `?key=<expires>.<label>.<HMAC-SHA256 base64url>` with
  `ACCESS_SECRET`; valid key -> HttpOnly cookie until expiry and redirect to the clean URL; cookie checked on
  later visits; otherwise 403 page in Russian. No `ACCESS_SECRET` -> site open as before.
- `scripts/make_access_link.py` (new): makes the links (default 24 h, optional label); `--telegram` sends them
  to the owner chat instead of printing.
- `.github/workflows/access-link.yml` (new): manual workflow (hours, label) that sends the links to Telegram;
  needs repository secrets `ACCESS_SECRET` and `TELEGRAM_BOT_TOKEN`. Links never go to the public log.
- `docs/README_RU.md`: section 10 (how to switch on and use).
- `tests/test_access_link.py`: Python-made keys checked by the JS middleware in Node (valid, expired, forged,
  missing, secret unset).

## Verification
- `python3 -m unittest discover -s tests`: 12 tests pass.

## Known limitations
- Anyone holding the link can use it until it expires; the number of searches is not limited
  (search runs in the browser on the full data set).
- Data CSVs stay public in the GitHub repository.
- Not active until `ACCESS_SECRET` is set in both Pages projects and in GitHub secrets.

## Next action
Owner sets `ACCESS_SECRET` (Cloudflare, both projects + GitHub), redeploys, then runs Access link for a
long-lived personal link.
