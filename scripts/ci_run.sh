#!/usr/bin/env bash
# One Spiti Radar job on GitHub Actions: run it, commit the city's data, push to main.
#
#   scripts/ci_run.sh update   thessaloniki|athens   - the update (scripts/daily_update.sh)
#   scripts/ci_run.sh discover thessaloniki|athens   - the weekly agency search (scripts/discover_agencies.py)
#   scripts/ci_run.sh watchdog thessaloniki|athens   - was the last scheduled update saved? if not, run it now
#
# Thessaloniki lives at the repository root, Athens in cities/athens. Two jobs never write the
# same files (each city has its own data folder), so a push that finds main moved is rebased
# and pushed again.
set -uo pipefail
cd "$(dirname "$0")/.."
ROOT=$(pwd)
job=$1 city=$2
case $city in
  thessaloniki) dir=. name=Thessaloniki ;;
  athens) dir=cities/athens name=Athens ;;
  *) echo "unknown city $city" >&2; exit 2 ;;
esac
log=$ROOT/build/$job-$city.log
mkdir -p "$ROOT/build"

push() {  # push(message, paths...)
  local msg=$1; shift
  git -C "$ROOT" add -- "$@"
  if git -C "$ROOT" diff --cached --quiet; then
    echo "nothing to commit"
    return 0
  fi
  git -C "$ROOT" commit -q -m "$msg"
  for wait in 2 4 8 16 32; do
    git -C "$ROOT" push -q origin HEAD:main && { echo "pushed: $msg"; return 0; }
    sleep $wait
    git -C "$ROOT" pull -q --rebase origin main || { git -C "$ROOT" rebase --abort; return 1; }
  done
  return 1
}

update() {
  (cd "$dir" && ./scripts/daily_update.sh) 2>&1 | tee "$log"
  local code=${PIPESTATUS[0]}
  if [ "$code" != 0 ]; then
    echo "update failed (exit $code):" >&2
    grep -m5 -E "Traceback|Error|failed" "$log" >&2
    return "$code"
  fi
  local n
  n=$(grep -m1 -oE "report: [0-9]+ new" "$log" | grep -oE "[0-9]+")
  push "Update $(TZ=Europe/Athens date +%F\ %H:%M) ($name): ${n:-0} new listings" "$dir/data/listings"
}

case $job in
  update)
    update ;;
  discover)
    (cd "$dir" && python3 scripts/discover_agencies.py) 2>&1 | tee "$log"
    code=${PIPESTATUS[0]}
    [ "$code" = 0 ] || exit "$code"
    last=$(tail -n 1 "$dir/data/sources/discovery_log.csv" | cut -d, -f3,5)
    push "Weekly agency search $(date +%F) ($name): ${last%,*} new agencies, ${last#*,} collectable" "$dir/data/sources" ;;
  watchdog)
    (cd "$dir" && python3 scripts/watchdog.py)
    code=$?
    if [ "$code" = 2 ]; then
      echo "last scheduled update of $name was not saved: running it now"
      update
    fi ;;  # 3 (Telegram / site warning): the script already sent it to Telegram
  *) echo "unknown job $job" >&2; exit 2 ;;
esac
