#!/usr/bin/env bash
# Agency sites that refuse the GitHub Actions runners (data/sources/cloud_sites.txt), collected once a
# day from a Claude cloud session: listings go to data/cloud/ and are pushed to main. The daily update
# on GitHub skips these sites and reads data/cloud/listings.csv in normalize_listings.py.
# data/cloud/ is outside data/listings, which the GitHub runs overwrite when their push races another.
# Usage: scripts/cloud_collect.sh   (Thessaloniki; run from any directory)
set -uo pipefail
cd "$(dirname "$0")/.."
git fetch -q origin main && git checkout -q -B main origin/main || exit 1
python3 scripts/collect_listings.py --incremental --workers 10 \
  --domains data/sources/cloud_sites.txt --out-dir data/cloud || exit 1
git add data/cloud
git diff --cached --quiet && { echo "nothing to commit"; exit 0; }
n=$(python3 -c "import csv;print(sum(int(r['new'] or 0) for r in csv.DictReader(open('data/cloud/collect_report.csv'))))")
git -c user.name="Spiti Radar" -c user.email="spiti-radar@users.noreply.github.com" \
  commit -q -m "Cloud collection $(TZ=Europe/Athens date +%F\ %H:%M) (Thessaloniki): ${n} new listings"
for wait in 2 4 8 16 32; do
  git push -q origin HEAD:main && { echo "pushed"; exit 0; }
  sleep $wait
  # main moved (a GitHub update): this commit touches only data/cloud, so a rebase is clean
  git pull -q --rebase origin main || exit 1
done
exit 1
