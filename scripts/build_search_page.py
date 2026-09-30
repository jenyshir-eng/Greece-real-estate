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


def map_point(members):
    best = min((m for m in members if m.get("map_lat")), key=lambda m: "sad".index(m.get("geo", "d")[:1] or "d"),
               default=None)
    if not best:
        return {}
    return {"la": round(float(best["map_lat"]), 4), "lo": round(float(best["map_lon"]), 4), "gq": best["geo"][:1]}


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
                         for m in members[1:]],
                 # map point and its precision: s = the site's own point, a = map area centre, d = district centre
                 **map_point(members)})
# map areas for the page: id -> [Russian name, Greek name, district, sale EUR/m2, rent EUR/m2]
areas = {i: [a["ru"], a["gr"], a["district"], a.get("sale"), a.get("rent")] for i, a in districts.AREAS.items()}
# map outlines: [id, [[lon, lat], ...] per ring]; areas without a polygon are drawn at their centre
geo = json.load(open("data/sources/thessaloniki_districts.geojson", encoding="utf-8"))
outlines = []
for f in geo["features"]:
    g, pid = f["geometry"], f["properties"].get("id")
    polys = [g["coordinates"]] if g["type"] == "Polygon" else g["coordinates"]
    outlines.append([pid, [[[round(x, 4), round(y, 4)] for x, y in ring] for poly in polys for ring in poly[:1]]])
centres = {a["id"]: a["centre"] for a in geo["areas_without_polygon"] if a.get("centre")}


def sources():
    """Sources tab: one row per site or portal with its listings in the base and how collection went."""
    count = {}
    for r in csv.DictReader(open("data/listings/listings_normalized.csv", encoding="utf-8")):
        count[r["source_domain"]] = count.get(r["source_domain"], 0) + 1
    report = {r["domain"]: r for r in csv.DictReader(open("data/listings/collect_report.csv", encoding="utf-8"))}
    reg = list(csv.DictReader(open("data/sources/agencies_thessaloniki.csv", encoding="utf-8")))
    names = {r["domain"]: r["name"] for r in reg}
    out = []
    for d, n in sorted(count.items(), key=lambda kv: -kv[1]):
        rep = report.get(d, {})
        kind = "portal" if d in PORTAL_NAME or d == "t.me" else ("network" if d in ("remax.gr", "ktimatoemporiki.gr") else "site")
        status = "error" if rep.get("error") else "ok"
        out.append([PORTAL_NAME.get(d, "Telegram" if d == "t.me" else names.get(d, d)), d, kind, n, status])
    for d, r in report.items():
        if d not in count:
            out.append([names.get(d, d), d, "site", 0, "error" if r.get("error") else "empty"])
    stat = {}
    for r in reg:
        s = r["site_status"]
        s = "blocked" if s.startswith("bot_check") or s in ("http_403", "http_429") else s
        stat[s] = stat.get(s, 0) + 1
    return {"rows": out, "registry": stat, "agencies": len(reg)}


page = open("web/search_template.html", encoding="utf-8").read()
data = json.dumps(rows, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
asof = max((r["scraped_at"] for r in csv.DictReader(open("data/listings/listings_normalized.csv", encoding="utf-8"))), default="")[:10]
asof = datetime.date.fromisoformat(asof).strftime("%d.%m.%Y") if asof else ""
open(sys.argv[1], "w", encoding="utf-8").write(page.replace("__DATA__", data).replace("__ASOF__", asof)
                                                 .replace("__MAPAREAS__", json.dumps(areas, ensure_ascii=False))
                                                 .replace("__OUTLINES__", json.dumps(outlines, separators=(",", ":")))
                                                 .replace("__CENTRES__", json.dumps(centres))
                                                 .replace("__SOURCES__", json.dumps(sources(), ensure_ascii=False, separators=(",", ":"))))
print(f"{sum(len(g) for g in groups.values())} listings, {len(rows)} properties -> {sys.argv[1]}")
