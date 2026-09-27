"""Group listings of the same property published on several sites (Property != listing).

The same flat is often on the agency's own site, on a partner agency's site and on
portals (Spitogatos, XE, ...). Two listings are taken as one property when:
  - same transaction (sale/rent), price within 1.5 %, area within 1.5 % (or 1 m2);
  - compatible type (equal, empty, or apartment~studio, house~maisonette);
  - compatible district (equal, or one of them unknown / "Θεσσαλονίκη"),
    and never a Thessaloniki listing with one from another region;
  - floor and bedrooms do not contradict when both are known;
  - when neither has a district, type, price and area must be exactly equal.
A group never holds two listings of the same site: a site does not publish one
property twice, so this keeps identical new-build units apart and stops chains.

Input/output: data/listings/listings_normalized.csv (adds property_id, group_size)
Usage: python3 scripts/group_properties.py
"""
import csv
import re
from collections import Counter, defaultdict

FILE = "data/listings/listings_normalized.csv"
SIMILAR_TYPES = [{"apartment", "studio"}, {"house", "maisonette"}]
GENERIC_AREA = {"", "Θεσσαλονίκη"}


def f(x):
    try:
        return float(x) if x not in ("", None) else None
    except ValueError:
        return None


def close(a, b, rel, absolute=0.0):
    return abs(a - b) <= max(absolute, rel * max(a, b))


def types_ok(a, b):
    return not a or not b or a == b or any({a, b} <= s for s in SIMILAR_TYPES)


def digits(s):
    t = (s or "").lower()
    if re.search(r"ισόγει|ισογει|ground|υπερυψ", t):
        return "0"
    if re.search(r"υπόγει|υπογει|basement", t):
        return "-1"
    m = re.search(r"-?\d+", t)
    return m.group(0) if m else None


def traits(r):
    """What a group may hold only one value of: district, floor, bedrooms."""
    kind = {"studio": "apartment", "maisonette": "house"}.get(r["type"], r["type"])
    return {"area": {r["area"]} - GENERIC_AREA,
            "type": {kind} - {""},
            "floor": {digits(r["floor"])} - {None},
            "bedrooms": {digits(r["bedrooms"])} - {None}}


def same_property(a, b):
    if a["transaction"] != b["transaction"] or not a["transaction"]:
        return False
    if not (close(a["_p"], b["_p"], 0.015) and close(a["_m"], b["_m"], 0.015, 1.0)):
        return False
    if not types_ok(a["type"], b["type"]):
        return False
    if {a["region"], b["region"]} == {"thessaloniki", "other"}:
        return False
    ga, gb = a["area"] in GENERIC_AREA, b["area"] in GENERIC_AREA
    if not ga and not gb and a["area"] != b["area"]:
        return False
    if ga or gb:
        # without the same district, round figures (500 EUR, 50 m2) match unrelated objects:
        # need exact figures plus one more sign (same floor or bedrooms, or non-round numbers)
        if a["type"] == "land" or b["type"] == "land":
            return False
        if not (a["_p"] == b["_p"] and a["_m"] == b["_m"]):
            return False
        same_extra = any(digits(a[k]) is not None and digits(a[k]) == digits(b[k]) for k in ("floor", "bedrooms"))
        round_step = 50 if a["transaction"] == "rent" else 5000
        if not same_extra and a["_p"] % round_step == 0 and a["_m"] % 5 == 0:
            return False
    for k in ("floor", "bedrooms"):
        da, db = digits(a[k]), digits(b[k])
        if da is not None and db is not None and da != db:
            return False
    return True


def main():
    rows = list(csv.DictReader(open(FILE, encoding="utf-8")))
    fields = [k for k in rows[0].keys() if k not in ("property_id", "group_size")] + ["property_id", "group_size"]
    for i, r in enumerate(rows):
        r["_i"], r["_p"], r["_m"] = i, f(r["price_eur"]), f(r["area_m2"])

    parent = list(range(len(rows)))
    sites = [{r["source_domain"]} for r in rows]
    trait = [traits(r) for r in rows]
    span = [(r["_p"], r["_p"], r["_m"], r["_m"]) for r in rows]  # min/max price, min/max area

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    # candidates share transaction and rounded area (neighbouring buckets cover the 1.5 %)
    buckets = defaultdict(list)
    for r in rows:
        if r["_p"] and r["_m"] and r["transaction"]:
            buckets[(r["transaction"], round(r["_m"]))].append(r)
    for (tx, m), group in sorted(buckets.items()):
        higher = [x for d in range(1, max(2, int(m * 0.015)) + 2) for x in buckets.get((tx, m + d), [])]
        for k, a in enumerate(group):
            for b in group[k + 1:] + higher:  # each pair once
                if a["source_domain"] == b["source_domain"]:
                    continue
                ra, rb = find(a["_i"]), find(b["_i"])
                if ra == rb or sites[ra] & sites[rb] or not same_property(a, b):
                    continue
                # the whole group must stay consistent, not only this pair
                # (otherwise a listing without district chains two districts together)
                merged = {k: trait[ra][k] | trait[rb][k] for k in trait[ra]}
                if any(len(v) > 1 for v in merged.values()):
                    continue
                sp = (min(span[ra][0], span[rb][0]), max(span[ra][1], span[rb][1]),
                      min(span[ra][2], span[rb][2]), max(span[ra][3], span[rb][3]))
                if not (close(sp[0], sp[1], 0.015) and close(sp[2], sp[3], 0.015, 1.0)):
                    continue  # tolerances must hold for the whole group, not pair by pair
                parent[rb] = ra
                sites[ra] |= sites[rb]
                trait[ra] = merged
                span[ra] = sp

    groups = defaultdict(list)
    for r in rows:
        groups[find(r["_i"])].append(r)
    for root, members in groups.items():
        pid = "p%06d" % root
        for r in members:
            r["property_id"], r["group_size"] = pid, len(members)

    with open(FILE, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    sizes = Counter(len(m) for m in groups.values())
    multi = sum(n for s, n in sizes.items() if s > 1)
    print(f"{len(rows)} listings -> {len(groups)} properties; {multi} properties on 2+ sites; sizes {dict(sorted(sizes.items()))}")


if __name__ == "__main__":
    main()
