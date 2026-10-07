"""Build the one-file search page from normalized listings.

Usage: python3 scripts/build_search_page.py OUT.html
Reads data/listings/listings_normalized.csv, price_history.csv, update_report.json and
web/search_template.html.

The data is written compactly (the page must open quickly on a phone): one array per property
with the keys listed once, repeated strings (agency, district, site, ...) as numbers into a
string table, dates as days since 2020-01-01, links as [site prefix, rest]. The page unpacks it.
"""
import csv
import datetime
import json
import os
import re
import sys

sys.path.insert(0, "scripts")
import city  # noqa: E402
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


HISTORY = {}
if os.path.exists("data/listings/price_history.csv"):
    for h in csv.DictReader(open("data/listings/price_history.csv", encoding="utf-8")):
        HISTORY.setdefault(h["url"], []).append([h["date"], int(h["price_eur"])])


def history(url):
    """[[date, price], ...] when the price changed at least once, else None."""
    h = HISTORY.get(url) or []
    return h if len(h) > 1 else None


def words(s):
    return set(re.findall(r"[^\W\d_]{3,}", (s or "").lower()))


def short_title(r):
    """The title for search and the sheet, without the agency's name and site boilerplate."""
    t = r["title"]
    for name in {r["agency"], r["agency"].split(" - ")[0]}:
        if len(name) >= 4:
            t = t.replace(name, " ")
    t = re.sub(r"\s*[-|·–]\s*(Μεσιτικό Γραφείο|Real Estate|Κτηματομεσιτικό)[^-|·–]*$", "", t, flags=re.I)
    t = re.sub(r"\s+", " ", t).strip(" -|·–,")
    return t[:90]


def short_location(r):
    """The address line only when it says something the title does not."""
    lr = r["location_raw"][:40]
    return "" if words(lr) <= words(r["title"]) | {"θεσσαλονίκη", "θεσσαλονίκης", "ελλάδα", "greece", city.GENERIC.lower()} else lr


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
    own = num(r, "price_eur")
    rows.append({"u": r["url"], "t": short_title(r), "ag": r["agency"], "tx": r["transaction"],
                 "ty": first("type"), "p": p, "px": max(prices) if len(set(prices)) > 1 else None,
                 # the main link's own price when it is not the lowest of the group (0 = no price there)
                 "p0": (own or 0) if own != p else None,
                 "ck": r.get("checked_at") or None, "h": history(r["url"]),
                 # when this link was seen (alert email date for portals, otherwise the site date / first seen)
                 "sd": r.get("listing_date") or r.get("first_seen") or None,
                 "m": m2, "pm": round(p / m2) if p and m2 else None, "bd": first("bedrooms")[:2] if (first("bedrooms")[:2].isdigit() and 0 < int(first("bedrooms")[:2]) <= 10) else "",
                 "fn": floor_code(first("floor"), r["title"]), "yr": first("year_built"), "rg": r["region"], "nb": first("neighbourhood"),
                 # district: the one of the map area if known, else the most specific one in the group
                 "ar": (districts.AREAS[first("neighbourhood")]["district"] if first("neighbourhood") in districts.AREAS
                        else next((m["area"] for m in members if m.get("area") not in ("", city.GENERIC)), first("area"))),
                 "lr": short_location(r), "ld": newest.get("listing_date", ""),
                 "lk": newest.get("listing_date_kind", ""), "fs": min((m["first_seen"] for m in members if m.get("first_seen")), default=""),
                 "src": r.get("source_domain", ""), "pv": r.get("private_owner", ""),
                 "ot": next((m.get("origin_type", "") for m in members if m.get("origin_confidence") == "high" and m.get("origin_type", "") not in ("", "UNKNOWN")),
                            next((m.get("origin_type", "") for m in members if m.get("origin_type", "") not in ("", "UNKNOWN")), "")),
                 "ags": sorted({m["agency"] for m in members}),
                 "srcs": sorted({m.get("source_domain", "") for m in members}),
                 # other sites with the same property: [name, url, price, checked, price history]
                 "alt": [[PORTAL_NAME.get(m.get("source_domain"), m["agency"]), m["url"], num(m, "price_eur"),
                          m.get("checked_at") or None, history(m["url"]), m.get("listing_date") or m.get("first_seen") or None]
                         for m in members[1:]] or None,
                 # map point and its precision: s = the site's own point, a = map area centre, d = district centre
                 **map_point(members)})
# map areas for the page: id -> [Russian name, Greek name, district, sale EUR/m2, rent EUR/m2]
areas = {i: [a["ru"], a["gr"], a["district"], a.get("sale"), a.get("rent")] for i, a in districts.AREAS.items()}
# map outlines: [id, [[lon, lat], ...] per ring]; areas without a polygon are drawn at their centre
geo = json.load(open(city.GEOJSON, encoding="utf-8")) if os.path.exists(city.GEOJSON) else {"features": [], "areas_without_polygon": []}
outlines = []
for f in geo["features"]:
    g, pid = f["geometry"], f["properties"].get("id")
    polys = [g["coordinates"]] if g["type"] == "Polygon" else g["coordinates"]
    outlines.append([pid, [[[round(x, 4), round(y, 4)] for x, y in ring] for poly in polys for ring in poly[:1]]])
centres = {a["id"]: a["centre"] for a in geo["areas_without_polygon"] if a.get("centre")}


# networks collected as a whole; the agency registry names one office with the network's domain
NETWORK_NAME = {"remax.gr": "RE/MAX (все офисы)", "ktimatoemporiki.gr": "Ktimatoemporiki"}


def sources():
    """Sources tab: one row per site or portal with its listings in the base and how collection went."""
    count = {}
    for r in csv.DictReader(open("data/listings/listings_normalized.csv", encoding="utf-8")):
        count[r["source_domain"]] = count.get(r["source_domain"], 0) + 1
    report = {r["domain"]: r for r in csv.DictReader(open("data/listings/collect_report.csv", encoding="utf-8"))}
    reg = list(csv.DictReader(open(city.REGISTRY, encoding="utf-8")))
    names = {r["domain"]: r["name"] for r in reg}
    out = []
    for d, n in sorted(count.items(), key=lambda kv: -kv[1]):
        rep = report.get(d, {})
        kind = "portal" if d in PORTAL_NAME or d == "t.me" else ("network" if d in ("remax.gr", "ktimatoemporiki.gr") else "site")
        # listings are in the base but the last pass of the site failed: still working, not broken
        status = ("partial" if n else "error") if rep.get("error") else "ok"
        name = NETWORK_NAME.get(d) or PORTAL_NAME.get(d) or ("Telegram" if d == "t.me" else names.get(d, d))
        out.append([name, d, kind, n, status])
    for d, r in report.items():
        if d not in count:
            out.append([names.get(d, d), d, "site", 0, "error" if r.get("error") else "empty"])
    stat = {}
    for r in reg:
        s = r["site_status"]
        s = "blocked" if s.startswith("bot_check") or s in ("http_403", "http_429") else s
        stat[s] = stat.get(s, 0) + 1
    return {"rows": out, "registry": stat, "agencies": len(reg)}


DAY0 = datetime.date(2020, 1, 1)
DICT = {"ag", "tx", "ty", "rg", "nb", "ar", "lk", "src", "pv", "gq", "ot"}
DATES = {"ld", "fs", "ck", "sd"}


def pack(rows):
    """Rows -> {"k": keys, "s": strings, "r": [[values in key order], ...]} (see the module doc)."""
    strings, index = [], {}

    def sid(x):
        if x not in index:
            index[x] = len(strings)
            strings.append(x)
        return index[x]

    def day(iso):
        try:
            return (datetime.date.fromisoformat(iso[:10]) - DAY0).days
        except ValueError:
            return None

    def link(u):
        m = re.match(r"(https?://[^/]+/?)(.*)", u)
        return [sid(m.group(1)), m.group(2)] if m else [sid(""), u]

    def number(v):
        return int(v) if isinstance(v, float) and v.is_integer() else v

    def hist(h):
        return [[day(d), p] for d, p in h] if h else None

    out = []
    for r in rows:
        d = {}
        for k, v in r.items():
            if v in ("", None, []):
                continue
            if k in DICT:
                v = sid(v)
            elif k in DATES:
                v = day(v)
            elif k == "u":
                v = link(v)
            elif k == "h":
                v = hist(v)
            elif k == "ags":
                if v == [r["ag"]]:
                    continue
                v = [sid(x) for x in v]
            elif k == "srcs":
                if v == [r["src"]]:
                    continue
                v = [sid(x) for x in v]
            elif k == "alt":
                v = [[sid(n), link(u), number(p), day(c) if c else None, hist(h), day(sd) if sd else None]
                     for n, u, p, c, h, sd in v]
                v = [a[:max(i for i, x in enumerate(a) if x is not None) + 1] for a in v]
            else:
                v = number(v)
            d[k] = v
        out.append(d)
    # the most often filled keys first, so missing values are mostly at the end and can be left off
    fill = {}
    for d in out:
        for k in d:
            fill[k] = fill.get(k, 0) + 1
    keys = sorted(fill, key=lambda k: -fill[k])
    packed = []
    for d in out:
        a = [d.get(k) for k in keys]
        while a and a[-1] is None:
            a.pop()
        packed.append(a)
    return {"k": keys, "s": strings, "r": packed}


def report():
    """The last run's report for the Sources tab (scripts/update_report.py), without the long lists."""
    path = "data/listings/update_report.json"
    if not os.path.exists(path):
        return None
    r = json.load(open(path, encoding="utf-8"))
    r["removed"] = len(r.get("removed", []))
    r["drops"] = len(r.get("drops", []))
    return r


# what the page says about the city (the template keeps the Thessaloniki tables as defaults)
CITY = {"key": city.KEY, "name": city.NAME_RU, "gen": city.NAME_RU_GEN, "generic": city.GENERIC,
        "map_url": city.MAP_URL if os.path.exists(city.GEOJSON) else "", "has_map": bool(outlines or centres),
        "area_ru": city.AREA_RU, "area_words": city.AREA_WORDS, "map_box": city.MAP_BOX, "examples": city.EXAMPLES}
page = open("web/search_template.html", encoding="utf-8").read()
data = json.dumps(pack(rows), ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
asof = max((r["scraped_at"] for r in csv.DictReader(open("data/listings/listings_normalized.csv", encoding="utf-8"))), default="")[:10]
asof = datetime.date.fromisoformat(asof).strftime("%d.%m.%Y") if asof else ""
open(sys.argv[1], "w", encoding="utf-8").write(page.replace("__DATA__", data).replace("__ASOF__", asof)
                                                 .replace("__MAPAREAS__", json.dumps(areas, ensure_ascii=False))
                                                 .replace("__OUTLINES__", json.dumps(outlines, separators=(",", ":")))
                                                 .replace("__CENTRES__", json.dumps(centres))
                                                 .replace("__CITY__", json.dumps(CITY, ensure_ascii=False))
                                                 .replace("__SOURCES__", json.dumps(sources(), ensure_ascii=False, separators=(",", ":")))
                                                 .replace("__REPORT__", json.dumps(report(), ensure_ascii=False, separators=(",", ":"))))
print(f"{sum(len(g) for g in groups.values())} listings, {len(rows)} properties -> {sys.argv[1]}")
