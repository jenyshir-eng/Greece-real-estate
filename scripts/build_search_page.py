"""Build the one-file search page from normalized listings.

Usage: python3 scripts/build_search_page.py OUT.html
Reads data/listings/listings_normalized.csv and web/search_template.html.
"""
import csv
import datetime
import json
import re
import sys

sys.path.insert(0, "scripts")
import districts  # noqa: E402

PORTAL_NAME = {"xe.gr": "XE.gr", "spitogatos.gr": "Spitogatos", "spiti24.gr": "Spiti24",
               "tospitimou.gr": "Tospitimou", "plot.gr": "Plot", "indomio.gr": "Indomio"}
groups = {}
for r in csv.DictReader(open("data/listings/listings_normalized.csv", encoding="utf-8")):
    groups.setdefault(r.get("property_id") or r["url"], []).append(r)


def num(r, k):
    return float(r[k]) if r.get(k) else None


def floor_code(s, title=""):
    """Greek floor -> level: -2 basement (υπόγειο), -1 semi-basement (ημιυπόγειο), 0 ground (ισόγειο),
    0.5 mezzanine / raised ground (ημιόροφος, υπερυψωμένο), 1.. upper floors.
    No floor field: the title is used. Values above 12 are data errors (usually the area) -> None."""
    t = (s or "").strip().lower()
    for text in (t, (title or "").lower()):
        if not text:
            continue
        if re.search(r"ημιυπ|semi.?basement", text):
            return -1
        if re.search(r"υπόγ|υπογει|basement", text):
            return -2
        if re.search(r"ημιόρ|ημιορ|ημιώρ|ημιωρ|mezzanine|υπερυψ|raised", text):
            return 0.5
        if re.search(r"ισόγ|ισογ|ground", text):
            return 0
        if text is t:
            try:
                n = int(float(t.split()[0].rstrip("οςηº")))
            except ValueError:
                continue
            return -2 if n < 0 else (n if n <= 12 else None)
    return None


def rank(r):
    # main link: the agency's own page first, then a dated listing, then the most complete one
    filled = sum(1 for k in ("price_eur", "area_m2", "bedrooms", "floor", "year_built", "area") if r.get(k))
    return (r.get("source_kind") != "portal", bool(r.get("listing_date")), r.get("listing_date", ""), filled)


rows = []
for members in groups.values():
    members.sort(key=rank, reverse=True)
    r = members[0]
    first = lambda k: next((m[k] for m in members if m.get(k)), "")
    prices = [num(m, "price_eur") for m in members if m.get("price_eur")]
    dated = [m for m in members if m.get("listing_date")]
    newest = max(dated, key=lambda m: m["listing_date"]) if dated else r
    p, m2 = (min(prices) if prices else None), num(r, "area_m2") or (num(members[0], "area_m2"))
    rows.append({"u": r["url"], "t": r["title"][:140], "ag": r["agency"], "tx": r["transaction"],
                 "ty": first("type"), "p": p, "px": max(prices) if len(set(prices)) > 1 else None,
                 "m": m2, "pm": round(p / m2) if p and m2 else None, "bd": first("bedrooms")[:2] if (first("bedrooms")[:2].isdigit() and 0 < int(first("bedrooms")[:2]) <= 10) else "",
                 "fn": floor_code(first("floor"), r["title"]), "yr": first("year_built"), "rg": r["region"], "nb": first("neighbourhood"),
                 # district: the one of the map area if known, else the most specific one in the group
                 "ar": (districts.AREAS[first("neighbourhood")]["district"] if first("neighbourhood") in districts.AREAS
                        else next((m["area"] for m in members if m.get("area") not in ("", "Θεσσαλονίκη")), first("area"))),
                 "lr": r["location_raw"][:40], "ld": newest.get("listing_date", ""),
                 "lk": newest.get("listing_date_kind", ""), "fs": min((m["first_seen"] for m in members if m.get("first_seen")), default=""),
                 "src": r.get("source_domain", ""), "pv": r.get("private_owner", ""),
                 "ags": sorted({m["agency"] for m in members}),
                 "srcs": sorted({m.get("source_domain", "") for m in members}),
                 # other sites with the same property: [name, url, price]
                 "alt": [[PORTAL_NAME.get(m.get("source_domain"), m["agency"]), m["url"], num(m, "price_eur")]
                         for m in members[1:]]})
# map areas for the page: id -> [Russian name, Greek name, district, sale EUR/m2, rent EUR/m2]
areas = {i: [a["ru"], a["gr"], a["district"], a.get("sale"), a.get("rent")] for i, a in districts.AREAS.items()}
page = open("web/search_template.html", encoding="utf-8").read()
data = json.dumps(rows, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
asof = max((r["scraped_at"] for r in csv.DictReader(open("data/listings/listings_normalized.csv", encoding="utf-8"))), default="")[:10]
asof = datetime.date.fromisoformat(asof).strftime("%d.%m.%Y") if asof else ""
open(sys.argv[1], "w", encoding="utf-8").write(page.replace("__DATA__", data).replace("__ASOF__", asof)
                                                 .replace("__MAPAREAS__", json.dumps(areas, ensure_ascii=False)))
print(f"{sum(len(g) for g in groups.values())} listings, {len(rows)} properties -> {sys.argv[1]}")
