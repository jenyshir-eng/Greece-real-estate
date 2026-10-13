"""Collect bank-owned (REO) and auction properties from the marketplaces of loan servicers.

Altamira (doValue) and Intrum run the same marketplace platform, with an open JSON API
behind the search page: GET https://api.marketplace.<servicer>/v1/listings/search
?filter_by=commercialization:=<sale|auction>&&coordinates: (<4 corners lat, lon>)&page=N&per_page=100.
Every listing carries its id, title, price, size, coordinates, region, created/updated times and,
for auctions, the auction date and round. The public page of a listing is
https://marketplace.<servicer>/listings/<id>; robots.txt allows /listings/.

The search is limited to the box of the city (scripts/city.py) and each point is checked with
city.in_unit. Every run reads the whole list again (a few hundred listings, a handful of requests),
so a listing that left it is sold or withdrawn: it is dropped and written to
data/listings/removed.csv. A servicer that suddenly returns far fewer listings than known is
treated as broken and its known listings are kept unchanged.

Cepal bank-owned properties on reinvest.gr and auctions on reauction.gr (scripts/servicers_eagents.py).

Segments: auction (price = starting price) and bank (servicer sale).

Usage: python3 scripts/collect_servicers.py
Output: data/listings/listings_servicers.csv (columns of listings_thessaloniki.csv plus
        segment, auction_date, auction_round, checked_at)
"""
import csv
import datetime
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import zoneinfo

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import city  # noqa: E402
import servicers_eagents  # noqa: E402

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/128.0 Safari/537.36 SpitiRadar/0.1 (+https://spitiradar.gr/opt-out)")
# source_domain, name shown on the page, API base, public site base
SERVICERS = [
    ("altamiraproperties.gr", "Altamira (doValue)", "https://api.marketplace.altamiraproperties.gr",
     "https://marketplace.altamiraproperties.gr"),
    ("intrum.gr", "Intrum", "https://api.marketplace.intrum.gr", "https://marketplace.intrum.gr"),
]
COMMERCIALIZATIONS = {"sale": "bank", "auction": "auction"}
PER_PAGE = 100
MAX_PAGES = 40
DELAY_S = 1.5
OUT = "data/listings/listings_servicers.csv"
REMOVED = "data/listings/removed.csv"
FIELDS = ["source_domain", "agency", "url", "title", "transaction", "type", "price_eur", "area_m2",
          "bedrooms", "floor", "year_built", "location", "lat", "lon", "image",
          "date_published", "date_updated", "date_sitemap", "date_source", "scraped_at",
          "segment", "auction_date", "auction_round", "checked_at"]
# marketplace type -> Spiti Radar type (normalize_listings.py reads the Greek title first)
TYPES = {"apartment": "apartment", "studio": "studio", "maisonette": "maisonette", "residence": "house",
         "detachedHouse": "house", "complexOfVillasMaisonettes": "house", "plot": "land", "field": "land",
         "retail": "store", "officeUnit": "office", "storage": "warehouse", "industrialBuilding": "warehouse",
         "residentialBuilding": "building", "parking": "parking", "hotel": "hotel"}
THESSALONIKI_BOX = [40.40, 41.10, 22.50, 23.80]
ATHENS = zoneinfo.ZoneInfo("Europe/Athens")
_last = [0.0]


def fetch_text(url, accept="text/html"):
    wait = DELAY_S - (time.time() - _last[0])
    if wait > 0:
        time.sleep(wait)
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": accept, "Accept-Language": "el,en"})
    try:
        with urllib.request.urlopen(req, timeout=40) as r:
            return r.read().decode("utf-8", "replace")
    finally:
        _last[0] = time.time()


def fetch_json(url):
    return json.loads(fetch_text(url, "application/json"))


def search_url(api, commercialization, box, page):
    la0, la1, lo0, lo1 = box
    corners = f"({la1:.5f}, {lo1:.5f}, {la1:.5f}, {lo0:.5f}, {la0:.5f}, {lo0:.5f}, {la0:.5f}, {lo1:.5f})"
    q = urllib.parse.urlencode({"filter_by": f"commercialization:={commercialization}&&coordinates: {corners}",
                                "page": page, "sort_by": "created_at:desc", "per_page": PER_PAGE})
    return f"{api}/v1/listings/search?{q}"


def text(v, locale="el"):
    """Localized value [{"locale": "el", "value": ...}, ...] -> the Greek text, else the first one."""
    if isinstance(v, str):
        return v
    if not isinstance(v, list) or not v:
        return ""
    return next((x.get("value", "") for x in v if x.get("locale") == locale), v[0].get("value", ""))


def day(ts):
    """Unix time -> date in Athens (auction dates are given as Athens midnight)."""
    try:
        return datetime.datetime.fromtimestamp(int(ts), ATHENS).strftime("%Y-%m-%d") if ts else ""
    except (TypeError, ValueError, OverflowError, OSError):
        return ""


def row_from(x, domain, name, site, segment, now):
    """One marketplace listing -> a CSV row, or None when it is not on sale any more."""
    if x.get("acquired") or x.get("status", "public") != "public":
        return None
    lat, lon = (x.get("coordinates") or [None, None])[:2]
    if lat is None or lon is None or not city.in_unit(float(lat), float(lon)):
        return None
    hidden = x.get("price_upon_request") or x.get("price_is_reserved")
    img = next((i.get("sizes", {}).get("lg") or i.get("sizes", {}).get("md") or ""
                for i in x.get("images") or [] if isinstance(i, dict)), "")
    auction = segment == "auction" and not x.get("auction_date_to_be_announced")
    return {
        "source_domain": domain,
        "agency": name,
        "url": f"{site}/listings/{x['id']}",
        "title": text(x.get("title")),
        "transaction": "sale",
        "type": TYPES.get(x.get("type", ""), ""),
        "price_eur": "" if hidden or not x.get("price") else x["price"],
        "area_m2": x.get("size") or "",
        "bedrooms": x.get("bedrooms") or "",
        "floor": text(x.get("floor_label")),
        "year_built": x.get("build_year") or "",
        "location": text(x.get("region")),
        "lat": lat, "lon": lon,
        "image": img,
        "date_published": day(x.get("created_at")),
        "date_updated": day(x.get("updated_at")),
        "date_sitemap": "",
        "date_source": "marketplace api created_at / updated_at",
        "scraped_at": now,
        "segment": segment,
        "auction_date": day(x.get("auction_date")) if auction else "",
        "auction_round": (x.get("auction_round") or "") if segment == "auction" else "",
        "checked_at": now[:10],
    }


def collect(domain, name, api, site, box, now):
    """All listings of one servicer in the box -> {url: row}; raises on a failed request."""
    rows = {}
    for comm, segment in COMMERCIALIZATIONS.items():
        for page in range(1, MAX_PAGES + 1):
            items = (fetch_json(search_url(api, comm, box, page)).get("data") or {}).get("listings") or []
            for x in items:
                r = row_from(x, domain, name, site, segment, now)
                if r:
                    rows[r["url"]] = r
            if len(items) < PER_PAGE:
                break
    return rows


def main():
    now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    box = city.BOX or THESSALONIKI_BOX
    old = {}
    if os.path.exists(OUT):
        old = {r["url"]: r for r in csv.DictReader(open(OUT, encoding="utf-8"))}
    # (source_domain, collector): every collector returns {url: row} or raises
    sources = [(d, lambda d=d, n=n, a=a, s=s: collect(d, n, a, s, box, now)) for d, n, a, s in SERVICERS]
    sources += [(site[0], lambda site=site: servicers_eagents.collect(site, box, now, fetch_text, fetch_json, city.in_unit))
                for site in servicers_eagents.SITES]
    rows, gone, failed = {}, [], 0
    for domain, run in sources:
        known = {u: r for u, r in old.items() if r["source_domain"] == domain}
        try:
            got = run()
        except (urllib.error.URLError, TimeoutError, ValueError) as e:
            print(f"{domain}: {getattr(e, 'code', '') or type(e).__name__} {e}; known listings kept", file=sys.stderr)
            rows.update(known)
            failed += 1
            continue
        if len(known) >= 20 and len(got) < 0.5 * len(known):
            print(f"{domain}: {len(got)} listings for {len(known)} known: looks broken, known listings kept",
                  file=sys.stderr)
            rows.update(known)
            failed += 1
            continue
        rows.update(got)
        gone += [r for u, r in known.items() if u not in got]
        seg = {s: sum(1 for r in got.values() if r["segment"] == s) for s in COMMERCIALIZATIONS.values()}
        print(f"{domain}: {len(got)} listings ({seg}), {sum(1 for u in known if u not in got)} removed",
              file=sys.stderr)
    tmp = OUT + ".tmp"
    with open(tmp, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore")
        w.writeheader()
        w.writerows(sorted(rows.values(), key=lambda r: r["url"]))
    os.replace(tmp, OUT)
    if gone:
        new = not os.path.exists(REMOVED)
        with open(REMOVED, "a", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            if new:
                w.writerow(["date", "source_domain", "url", "reason"])
            w.writerows([now[:10], r["source_domain"], r["url"], "left the servicer marketplace"] for r in gone)
    print(f"done: {len(rows)} servicer / auction listings, {len(gone)} removed", file=sys.stderr)
    return 1 if failed == len(sources) else 0


if __name__ == "__main__":
    sys.exit(main())
