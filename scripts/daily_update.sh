#!/usr/bin/env bash
# Daily Spiti Radar update:
#   1. new portal listings from the alert emails sheet (PORTAL_ALERTS_CSV_URL)
#   2. new / changed listings on agency sites (incremental, polite: >= 3 s per site)
#   3. district check for listings without one (each page once, max 1500 a day)
#   4. normalize, group listings of the same property, rebuild the search page -> build/spiti-radar-search.html
# Commit, push and publishing the page are done by whoever runs this.
set -uo pipefail
cd "$(dirname "$0")/.."
mkdir -p build

if [ -n "${PORTAL_ALERTS_CSV_URL:-}" ]; then
  python3 scripts/ingest_portal_alerts.py || echo "WARNING: portal alerts not updated" >&2
else
  echo "WARNING: PORTAL_ALERTS_CSV_URL not set, portal alerts skipped" >&2
fi
python3 scripts/collect_listings.py --incremental --workers 25 || { echo "collection failed" >&2; exit 1; }
python3 scripts/normalize_listings.py || exit 1
# listings that only say "Θεσσαλονίκη": read the page once for the district, then normalize again
python3 scripts/refine_districts.py --max-pages 1500 || echo "WARNING: district check failed" >&2
python3 scripts/normalize_listings.py || exit 1
python3 scripts/group_properties.py || exit 1
python3 scripts/build_search_page.py build/spiti-radar-search.html || exit 1
