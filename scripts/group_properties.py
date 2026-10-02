"""Group listings of the same property published on several sites (Property != listing).

The same flat is often on the agency's own site, on a partner agency's site and on
portals (Spitogatos, XE, ...). Two listings are taken as one property when:
  - same transaction (sale/rent), price within 1.5 %, area within 1.5 % (or 1 m2);
  - compatible type (equal, empty, or apartment~studio, house~maisonette);
  - compatible district (equal, or one of them unknown / "Θεσσαλονίκη"),
    and never a Thessaloniki listing with one from another region;
  - floor, bedrooms, year built and the sites' own map points do not contradict;
  - and at least two points of further evidence, because equal price, area and district
    alone also fit different flats of one new building or street:
      same floor 2, same year built 2, the sites' own map points within 250 m 2,
      the same long title (one ad copied to several sites) 2,
      same bedrooms 1, same map area 1, a rare word shared by the titles/addresses
      (a street, a building name) 1, an exactly equal non-round price 1 or area 1;
  - when one of them has no district, type, price and area must be exactly equal too.
A group never holds two listings of the same site: a site does not publish one
property twice, so this keeps identical new-build units apart and stops chains.

Input/output: data/listings/listings_normalized.csv (adds property_id, group_size)
Usage: python3 scripts/group_properties.py
"""
import csv
import math
import re
import os
import sys
import unicodedata
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import city  # noqa: E402

FILE = "data/listings/listings_normalized.csv"
SIMILAR_TYPES = [{"apartment", "studio"}, {"house", "maisonette"}]
GENERIC_AREA = {"", city.GENERIC}
MIN_EVIDENCE = 2
RARE_WORD_MAX = 25  # a word in at most this many listings tells places apart (a street, a building)


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


def plain(s):
    s = unicodedata.normalize("NFD", (s or "").lower())
    return "".join(c for c in s if unicodedata.category(c) != "Mn").replace("ς", "σ")


def words(r):
    return {w for w in re.findall(r"[^\W\d_]{5,}", plain(r["title"] + " " + r["location_raw"]))}


def point(r):
    """The site's own coordinates (not an area centre, not the agency office)."""
    if r.get("geo") != "site":
        return None
    try:
        return float(r["map_lat"]), float(r["map_lon"])
    except (KeyError, ValueError):
        return None


def km(a, b):
    return math.hypot(a[0] - b[0], (a[1] - b[1]) * 0.76) * 111


def year(r):
    m = re.search(r"(?:18|19|20)\d{2}", r.get("year_built") or "")
    return int(m.group(0)) if m else None


def evidence(a, b):
    """Points of evidence beyond price, area and district; None when something contradicts."""
    score = 0
    for k, pts in (("floor", 2), ("bedrooms", 1)):
        da, db = digits(a[k]), digits(b[k])
        if da is not None and db is not None:
            if da != db:
                return None
            score += pts
    ya, yb = year(a), year(b)
    if ya and yb:
        if abs(ya - yb) > 1:
            return None
        score += 2
    pa, pb = point(a), point(b)
    if pa and pb:
        d = km(pa, pb)
        if d > 2.5:
            return None
        score += 2 if d <= 0.25 else 0
    if len(a["_t"]) >= 30 and a["_t"] == b["_t"]:
        score += 2
    if a["neighbourhood"] and a["neighbourhood"] == b["neighbourhood"]:
        score += 1
    if a["_w"] & b["_w"]:
        score += 1
    if a["_p"] == b["_p"] and a["_p"] % (10 if a["transaction"] == "rent" else 1000):
        score += 1
    if a["_m"] == b["_m"] and a["_m"] % 5:
        score += 1
    return score


def same_property(a, b):
    if a["transaction"] != b["transaction"] or not a["transaction"]:
        return False
    if not (close(a["_p"], b["_p"], 0.015) and close(a["_m"], b["_m"], 0.015, 1.0)):
        return False
    if not types_ok(a["type"], b["type"]):
        return False
    if {a["region"], b["region"]} == {city.KEY, "other"}:
        return False
    ga, gb = a["area"] in GENERIC_AREA, b["area"] in GENERIC_AREA
    if not ga and not gb and a["area"] != b["area"]:
        return False
    if ga or gb:
        # without the same district round figures (500 EUR, 50 m2) match unrelated objects
        if a["type"] == "land" or b["type"] == "land":
            return False
        if not (a["_p"] == b["_p"] and a["_m"] == b["_m"]):
            return False
    score = evidence(a, b)
    return score is not None and score >= MIN_EVIDENCE


def main():
    rows = list(csv.DictReader(open(FILE, encoding="utf-8")))
    fields = [k for k in rows[0].keys() if k not in ("property_id", "group_size")] + ["property_id", "group_size"]
    for i, r in enumerate(rows):
        r["_i"], r["_p"], r["_m"] = i, f(r["price_eur"]), f(r["area_m2"])
    # rare words only: area names, "apartment", "sale" and the like are in many listings
    df = Counter(w for r in rows for w in words(r))
    for r in rows:
        r["_w"] = {w for w in words(r) if df[w] <= RARE_WORD_MAX}
        r["_t"] = " ".join(re.findall(r"[^\W_]+", plain(r["title"])))

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
