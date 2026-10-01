"""What the last update run changed, and how each source did.

Runs after group_properties.py. Compares the listings base before the run
(build/prev_normalized.csv, copied by daily_update.sh) with the new one and:
  - keeps the price history: data/listings/price_history.csv (url, date, price_eur), one row
    when a listing is first seen and one more on every price change;
  - writes data/listings/update_report.json for the search page (Sources tab) and the Telegram
    message: new / removed listings, price drops and rises, listings checked today, collection
    errors per source, step durations (build/run_steps.tsv from daily_update.sh);
  - appends one line per run to data/listings/update_log.csv.

Usage: python3 scripts/update_report.py
"""
import csv
import datetime
import json
import os
from collections import Counter, defaultdict

LISTINGS = "data/listings/listings_normalized.csv"
PREV = "build/prev_normalized.csv"
STEPS = "build/run_steps.tsv"
HISTORY = "data/listings/price_history.csv"
REMOVED = "data/listings/removed.csv"
COLLECT = "data/listings/collect_report.csv"
REPORT = "data/listings/update_report.json"
LOG = "data/listings/update_log.csv"
# a "change" larger than this is a parsing slip (a monthly figure, a missing zero), not a new price
MAX_CHANGE = 0.5


def price(r):
    try:
        return int(float(r["price_eur"])) if r.get("price_eur") else None
    except ValueError:
        return None


def load_history():
    hist = defaultdict(list)
    if os.path.exists(HISTORY):
        for r in csv.DictReader(open(HISTORY, encoding="utf-8")):
            hist[r["url"]].append((r["date"], int(r["price_eur"])))
    return hist


def main():
    now = datetime.datetime.utcnow()
    today = now.strftime("%Y-%m-%d")
    cur = list(csv.DictReader(open(LISTINGS, encoding="utf-8")))
    by_url = {r["url"]: r for r in cur}
    prev = {r["url"]: r for r in csv.DictReader(open(PREV, encoding="utf-8"))} if os.path.exists(PREV) else None

    # price history
    hist = load_history()
    changes = []  # (domain, url, old, new)
    for r in cur:
        p = price(r)
        if not p:
            continue
        h = hist[r["url"]]
        if not h:
            h.append((r.get("first_seen") or today, p))
        elif h[-1][1] != p:
            old = h[-1][1]
            if abs(p - old) / old <= MAX_CHANGE:
                h.append((today, p))
                changes.append((r["source_domain"], r["url"], old, p))
            else:
                h.append((today, p))  # recorded, but not reported as a price move
    with open(HISTORY + ".tmp", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["url", "date", "price_eur"])
        for u in sorted(hist):
            w.writerows([u, d, p] for d, p in hist[u])
    os.replace(HISTORY + ".tmp", HISTORY)

    # new and removed since the previous run
    if prev is not None:
        new = [r for u, r in by_url.items() if u not in prev]
        gone = [r for u, r in prev.items() if u not in by_url]
    else:
        new, gone = [r for r in cur if r.get("first_seen") == today], []
    why = {}
    if os.path.exists(REMOVED):
        for r in csv.DictReader(open(REMOVED, encoding="utf-8")):
            if r["date"] >= today[:8] + "01":  # this month's records are enough to name a reason
                why[r["url"]] = r["reason"]

    errors = {}
    if os.path.exists(COLLECT):
        for r in csv.DictReader(open(COLLECT, encoding="utf-8")):
            if r.get("error"):
                errors[r["domain"]] = r["error"]
    steps = []
    if os.path.exists(STEPS):
        for line in open(STEPS, encoding="utf-8"):
            parts = line.rstrip("\n").split("\t")
            if len(parts) == 4:
                name, start, sec, code = parts
                steps.append([name, int(sec), int(code)])

    per = defaultdict(Counter)
    for r in cur:
        per[r["source_domain"]]["listings"] += 1
        if r.get("checked_at") == today:
            per[r["source_domain"]]["checked"] += 1
    for r in new:
        per[r["source_domain"]]["new"] += 1
    for r in gone:
        per[r["source_domain"]]["removed"] += 1
    for d, _, old, p in changes:
        per[d]["down" if p < old else "up"] += 1
    for d in errors:
        per[d]["error"] += 0  # make sure the source is listed
    sources = sorted(([d, c["listings"], c["new"], c["removed"], c["down"], c["up"], c["checked"], errors.get(d, "")]
                      for d, c in per.items()), key=lambda x: (-(x[2] + x[3] + x[4] + x[5]), -x[1]))
    totals = {"listings": len(cur), "new": len(new), "removed": len(gone),
              "down": sum(1 for c in changes if c[3] < c[2]), "up": sum(1 for c in changes if c[3] > c[2]),
              "checked": sum(1 for r in cur if r.get("checked_at") == today),
              "errors": len(errors), "failed_steps": [s[0] for s in steps if s[2] != 0]}
    report = {
        "at": now.strftime("%Y-%m-%dT%H:%MZ"),
        "first_run": prev is None,
        "totals": totals,
        "steps": steps,
        # only sources with something to say: changes today or a collection error
        "sources": [s for s in sources if s[2] or s[3] or s[4] or s[5] or s[7]],
        "drops": [[u, old, p, d] for d, u, old, p in sorted(changes, key=lambda c: c[3] / c[2]) if p < old][:300],
        "removed": [[r["source_domain"], r["url"], why.get(r["url"], "")] for r in gone][:300],
    }
    json.dump(report, open(REPORT, "w", encoding="utf-8"), ensure_ascii=False, indent=0)
    new_log = not os.path.exists(LOG)
    with open(LOG, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if new_log:
            w.writerow(["at", "listings", "new", "removed", "price_down", "price_up", "checked", "source_errors",
                        "failed_steps", "minutes"])
        w.writerow([report["at"], totals["listings"], totals["new"], totals["removed"], totals["down"], totals["up"],
                    totals["checked"], totals["errors"], " ".join(totals["failed_steps"]),
                    round(sum(s[1] for s in steps) / 60)])
    print(f"report: {totals['new']} new, {totals['removed']} removed, {totals['down']} cheaper, {totals['up']} dearer, "
          f"{totals['checked']} checked today, {totals['errors']} sources with errors, "
          f"failed steps: {totals['failed_steps'] or 'none'}")


if __name__ == "__main__":
    main()
