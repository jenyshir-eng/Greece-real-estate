#!/usr/bin/env bash
# Daily Spiti Radar update:
#   1. new portal listings from the alert emails sheet (PORTAL_ALERTS_CSV_URL)
#   1b. listing posts from public Telegram channels (data/sources/telegram_channels.csv)
#   1c. agency networks with their own collectors: RE/MAX (all offices; map points for new listings), Ktimatoemporiki
#   1d. XE.gr listings of Thessaloniki agencies from their public agency pages
#   2. new / changed listings on agency sites (incremental, polite: >= 3 s per site),
#      plus a re-check of known listings on rotation (price, still online)
#   3. district check for listings without one (each page once, max 1500 a day)
#   4. normalize, group listings of the same property, update report and price history,
#      rebuild the search page -> build/spiti-radar-search.html
#   5. Telegram: new properties and price drops for the saved filters, plus the update report
# Commit, push and publishing the page are done by whoever runs this.
set -uo pipefail
cd "$(dirname "$0")/.."
mkdir -p build
# the base before this run: update_report.py compares against it
cp data/listings/listings_normalized.csv build/prev_normalized.csv 2>/dev/null || true
: > build/run_steps.tsv

# step NAME COMMAND...: runs the command, records name, start, seconds and exit code
step() {
  local name=$1; shift
  local t0 start code
  t0=$(date +%s); start=$(date -u +%H:%M)
  "$@"
  code=$?
  printf '%s\t%s\t%s\t%s\n' "$name" "$start" "$(( $(date +%s) - t0 ))" "$code" >> build/run_steps.tsv
  return $code
}

if [ -n "${PORTAL_ALERTS_CSV_URL:-}" ]; then
  step alerts python3 scripts/ingest_portal_alerts.py || echo "WARNING: portal alerts not updated" >&2
else
  echo "WARNING: PORTAL_ALERTS_CSV_URL not set, portal alerts skipped" >&2
  printf 'alerts\t-\t0\t1\n' >> build/run_steps.tsv
fi
step telegram python3 scripts/collect_telegram.py --days 120 || echo "WARNING: Telegram channels not updated" >&2
step remax python3 scripts/collect_remax_listings.py --coords 60 --max-minutes 25 || echo "WARNING: RE/MAX listings not updated" >&2
step ktimatoemporiki python3 scripts/collect_ktimatoemporiki.py --max-pages 400 || echo "WARNING: Ktimatoemporiki listings not updated" >&2
step xe python3 scripts/collect_xe_profiles.py --max-minutes 20 || echo "WARNING: XE agency pages not updated" >&2
step iown python3 scripts/collect_iown.py --max-pages 10 --detail-pages 30 || echo "WARNING: iOWN listings not updated" >&2
step agencies python3 scripts/collect_listings.py --incremental --workers 25 || { echo "collection failed" >&2; exit 1; }
step normalize python3 scripts/normalize_listings.py || exit 1
# listings that only say "Θεσσαλονίκη": read the page once for the district, then normalize again
step districts python3 scripts/refine_districts.py --max-pages 1500 || echo "WARNING: district check failed" >&2
step normalize2 python3 scripts/normalize_listings.py || exit 1
step group python3 scripts/group_properties.py || exit 1
python3 scripts/update_report.py || echo "WARNING: update report not written" >&2
python3 scripts/build_search_page.py build/spiti-radar-search.html || exit 1
# Telegram: new properties and price drops for the saved filters + the update report (needs TELEGRAM_BOT_TOKEN)
python3 scripts/notify_telegram.py || echo "WARNING: Telegram message not sent" >&2
