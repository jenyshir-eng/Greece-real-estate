"""Collect Thessaloniki-area listings from ktimatoemporiki.gr (Greek agency network).

The site lists every property in https://ktimatoemporiki.gr/sitemap-properties.xml
(~13 000 URLs for all Greece, with lastmod). Property pages carry schema.org
RealEstateListing JSON-LD: name, datePosted, address (locality/region), price,
floor size, bedrooms and images. robots.txt allows /property/ pages.

Candidates are URLs whose slug names a place of the Thessaloniki prefecture or
Chalkidiki, plus the Thessaloniki branch ids (id-th*). Pages are fetched only
when new or when the sitemap lastmod changed; the region from the JSON-LD
decides what is kept (Thessaloniki, Chalkidiki).

Usage: python3 scripts/collect_ktimatoemporiki.py [--max-pages 0]
Output: data/listings/listings_ktimatoemporiki.csv (same columns as listings_thessaloniki.csv + lastmod)
"""
import argparse
import csv
import datetime
import html
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/128.0 Safari/537.36 SpitiRadar/0.1 (+https://spitiradar.gr/opt-out)")
SITEMAP = "https://ktimatoemporiki.gr/sitemap-properties.xml"
DELAY_S = 3.0
MAX_FAILS_IN_ROW = 5
OUT = "data/listings/listings_ktimatoemporiki.csv"
SKIP = "data/listings/listings_ktimatoemporiki.skip"  # url<TAB>lastmod of pages outside the region
FIELDS = ["source_domain", "agency", "url", "title", "transaction", "type", "price_eur", "area_m2",
          "bedrooms", "floor", "year_built", "location", "lat", "lon", "image",
          "date_published", "date_updated", "date_sitemap", "date_source", "scraped_at", "lastmod"]
PLACE = re.compile(
    r"thessalon|kalamari|pylaia|pylea|panorama|thermi|perea|peraia|evosmos|eyosmos|neapoli|sykies|stavroupoli|"
    r"polichni|ampelokipi|menemeni|kordelio|oraiokastro|chortiatis|triandria|toumba|charilaou|epanomi|michaniona|"
    r"neoi-epivates|agia-triada|sindos|kalochori|lagkadas|langadas|diavata|efkarpia|nea-krini|aretsou|"
    r"plagiari|trilofo|nea-raidestos|asvestochori|filyro|exochi|mikra|kardia|tagarades|pefka|retziki|"
    r"halkidiki|chalkidiki|kassandra|sithonia|pefkochori|polichrono|kallithea|nikiti|neos-marmaras|"
    r"nea-moudania|nea-kallikratia|nea-potidea|afytos|hanioti|toroni|ouranoupoli|ierissos|vourvourou", re.I)
REGIONS = ("thessaloniki", "halkidiki", "chalkidiki")
_last = [0.0]


def fetch(url):
    wait = DELAY_S - (time.time() - _last[0])
    if wait > 0:
        time.sleep(wait)
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "el,en"})
    try:
        with urllib.request.urlopen(req, timeout=40) as r:
            return r.read().decode("utf-8", "replace")
    finally:
        _last[0] = time.time()


def listing_ld(page):
    for m in re.findall(r'<script type="application/ld\+json">(.*?)</script>', page, re.S):
        try:
            d = json.loads(m)
        except ValueError:
            continue
        if isinstance(d, dict) and d.get("@type") == "RealEstateListing":
            return d
    return None


def row_from(d, url, lastmod, now):
    name = html.unescape(d.get("name", ""))
    offer = d.get("offers") or {}
    addr = d.get("address") or {}
    size = (d.get("floorSize") or {}).get("value", "")
    img = d.get("image") or []
    img = img[0].get("url", "") if img and isinstance(img[0], dict) else (img[0] if img else "")
    posted = (d.get("datePosted") or "")[:10]
    return {
        "source_domain": "ktimatoemporiki.gr",
        "agency": "Ktimatoemporiki",
        "url": url,
        "title": name,
        "transaction": "rent" if re.search(r"\bfor rent\b|-for-rent-", name + url, re.I) else "sale",
        "type": "",
        "price_eur": offer.get("price", ""),
        "area_m2": size,
        "bedrooms": d.get("numberOfBedrooms", ""),
        "floor": "", "year_built": "",
        "location": ", ".join(x for x in (html.unescape(addr.get("addressLocality", "")),
                                          html.unescape(addr.get("addressRegion", ""))) if x),
        "lat": "", "lon": "",
        "image": img,
        "date_published": posted,
        "date_updated": "",
        "date_sitemap": lastmod,
        "date_source": "json-ld datePosted; sitemap lastmod",
        "scraped_at": now,
        "lastmod": lastmod,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-pages", type=int, default=0, help="limit property pages fetched (test runs)")
    a = ap.parse_args()
    now = datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    xml = fetch(SITEMAP)
    entries = re.findall(r"<loc>\s*([^<\s]+)\s*</loc>\s*(?:<lastmod>\s*([^<\s]+)\s*</lastmod>)?", xml)
    cand = {u: lm for u, lm in entries if PLACE.search(u.rsplit("/", 1)[-1]) or re.search(r"-id-th\d", u)}
    old, skip = {}, {}
    if os.path.exists(OUT):
        old = {r["url"]: r for r in csv.DictReader(open(OUT, encoding="utf-8"))}
    if os.path.exists(SKIP):
        skip = dict(l.rstrip("\n").split("\t", 1) for l in open(SKIP, encoding="utf-8") if "\t" in l)
    # pages outside the region are remembered, so they are not fetched again until they change
    known = {u: r["lastmod"] for u, r in old.items()} | skip
    todo = [u for u, lm in cand.items() if known.get(u) != lm]
    if a.max_pages:
        todo = todo[:a.max_pages]
    print(f"{len(entries)} properties in the sitemap, {len(cand)} candidates, {len(todo)} new or changed",
          file=sys.stderr)
    rows = {u: r for u, r in old.items() if u in cand}  # gone from the sitemap = sold / withdrawn
    fails = 0
    for i, u in enumerate(todo, 1):
        try:
            page = fetch(u)
            fails = 0
        except (urllib.error.URLError, TimeoutError) as e:
            fails += 1
            print(f"skip {u}: {getattr(e, 'code', type(e).__name__)}", file=sys.stderr)
            if fails >= MAX_FAILS_IN_ROW:
                print("stopping: repeated refusals; rerun continues", file=sys.stderr)
                break
            continue
        d = listing_ld(page)
        if not d:
            continue
        r = row_from(d, u, cand[u], now)
        region = ((d.get("address") or {}).get("addressRegion") or "").lower()
        if any(x in region for x in REGIONS):
            rows[u] = r
            skip.pop(u, None)
        else:
            rows.pop(u, None)
            skip[u] = cand[u]
        if i % 50 == 0:
            print(f"{i}/{len(todo)} pages", file=sys.stderr)
    tmp = OUT + ".tmp"
    with open(tmp, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore")
        w.writeheader()
        w.writerows(sorted(rows.values(), key=lambda r: r["url"]))
    os.replace(tmp, OUT)
    with open(SKIP, "w", encoding="utf-8") as f:
        f.writelines(f"{u}\t{lm}\n" for u, lm in sorted(skip.items()) if u in cand)
    print(f"done: {len(rows)} listings in Thessaloniki / Chalkidiki", file=sys.stderr)


if __name__ == "__main__":
    main()
