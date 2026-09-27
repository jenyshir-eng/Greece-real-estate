"""Collect Thessaloniki listings from xe.gr result pages.

xe.gr publishes its result pages per area in sitemaps
(https://www.xe.gr/sitemap/property/results/...). robots.txt allows the first
page of each result URL; listing detail pages (/property/d/*) and paginated or
filtered result URLs (with "?") are disallowed for all bots, so we only read
the listing cards shown on the first result page of every Thessaloniki area.

Each card gives: listing id and URL, title (type + m2), price, area, floor,
bedrooms, year built, owner (agency or private), the owner's xe.gr page,
"bumped" time ("Πριν 23 ώρες") and a thumbnail URL.

Usage: python3 scripts/collect_xe_listings.py [--max-pages 0]
Resumable: rerun continues where the previous run stopped (progress in listings_xe.csv.pages).
Output: data/listings/listings_xe.csv (same columns as listings_thessaloniki.csv)
"""
import argparse
import csv
import datetime
import html
import re
import sys
import time
import urllib.request

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/128.0 Safari/537.36 SpitiRadar/0.1 (+https://spitiradar.gr/opt-out)")
DELAY_S = 20.0          # xe.gr blocks faster crawling (403 after ~50 pages at 3 s)
MAX_FAILS_IN_ROW = 5    # stop on repeated refusals instead of hammering the site
OUT = "data/listings/listings_xe.csv"
SUBTYPES = {
    "residence": ["", "apartment", "studios-small-apartment", "one-bedroom-apartment", "two-bedroom-apartment",
                  "maisonette", "house", "new-build-apartment", "penthouse", "furnished-apartment"],
    "commercial": ["", "office", "retail", "storage", "building", "space"],
    "land": ["", "plot"],
}
# each (sub)type has its own first result page per area, so every sitemap adds different listings
SITEMAPS = [f"https://www.xe.gr/sitemap/property/results/{deal}/{kind}" + (f"/{sub}" if sub else "")
            for deal in ("buy", "rent") for kind, subs in SUBTYPES.items() for sub in subs
            if not (deal == "rent" and kind == "land")]
# latin slugs xe.gr uses for places in the Thessaloniki prefecture
THESS = re.compile(
    r"thessalonik|kalamari|pylai|pylea|panorama|therm|perai|peraia|eyosm|evosm|neapol|sykie|stayroypol|stavroupol|"
    r"polixn|polichn|ampelokhp|ampelokip|menemen|kordeli|oraiokastr|xortiat|chortiat|triandri|toymp|toump|xarilao|"
    r"epanom|mhxanion|michanion|neoi-epibat|neoi-epivat|pefka|retziki|sindos|kalochori|kaloxori|lagkada|xalastr|"
    r"diabat|diavat|eykarpi|efkarpi|nea-krinh|aretsoy|karampournak|analhpsh|mpotsar|martioy|ntepo|kifisia|faliro|"
    r"xarilaou|agia-triada|plagiari|trilofo|nea-raidesto|baxliak|asbestoxori|filyro|exoxh|pentalofo|mikra|kardia|"
    r"tagarades|kato-scholari|plagiari|agios-pablos|agios-pavlos|eleytherio|eleftherio", re.I)
ALREADY_SEEN = set()


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "el"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", "replace")


def rel_date(s, today):
    """'Πριν 23 ώρες' / 'Πριν 5 ημέρες' / 'Πριν 2 εβδομάδες' / 'Πριν 3 μήνες' / '12/09/2026' -> ISO date."""
    s = (s or "").strip().lower()
    m = re.search(r"(\d{1,2})/(\d{1,2})/(\d{4})", s)
    if m:
        try:
            return datetime.date(int(m.group(3)), int(m.group(2)), int(m.group(1))).isoformat()
        except ValueError:
            return ""
    m = re.search(r"(\d+)\s*(λεπτ|ώρ|ωρ|ημέρ|ημερ|μέρ|εβδομ|μήν|μην|χρόν|χρον)", s)
    if not m:
        return today.isoformat() if re.search(r"μόλις|σήμερα", s) else ""
    n, unit = int(m.group(1)), m.group(2)
    days = {"λεπτ": 0, "ώρ": n / 24, "ωρ": n / 24, "ημέρ": n, "ημερ": n, "μέρ": n,
            "εβδομ": 7 * n, "μήν": 30 * n, "μην": 30 * n, "χρόν": 365 * n, "χρον": 365 * n}[unit]
    return (today - datetime.timedelta(days=int(days))).isoformat()


def num(s):
    s = re.sub(r"[^\d.,]", "", s or "")
    if re.fullmatch(r"\d{1,3}(\.\d{3})+(,\d+)?", s):
        s = s.replace(".", "").replace(",", ".")
    else:
        s = s.replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return ""


def text_of(fragment):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", fragment))).strip()


def testid(block, tid):
    m = re.search(r'data-testid="%s"[^>]*>(.*?)</(?:div|h3|span)>' % re.escape(tid), block, re.S)
    return text_of(m.group(1)) if m else ""


def parse_cards(page, result_url, today):
    tx = "rent" if re.search(r"/enoikiase", result_url) else "sale"
    out = []
    for m in re.finditer(r'id="common_ad_body_([0-9a-f-]{36})"', page):
        ad_id = m.group(1)
        start = page.rfind('data-testid="property-ad-image-container"', 0, m.start())
        end = page.find('data-testid="property-ad-actions"', m.start())
        block = page[start if start > 0 else m.start():end if end > 0 else m.start() + 8000]
        href = re.search(r'href="(https://www\.xe\.gr/property/d/[^"?]+)', block)
        title = testid(block, "property_ad_title")
        price = testid(block, "property_ad_price")
        area = re.search(r"([\d.,]+)\s*τ\.μ\.", title)
        owner = re.search(r'data-testid="common-ad-owner-title"[^>]*>(.*?)</div>', block, re.S)
        owner_link = re.search(r'href="(https://www\.xe\.gr/property/s/[^"]+)"', block)
        footer = block[block.find("common_ad_body_footer"):] if "common_ad_body_footer" in block else ""
        when = re.search(r">\s*(Πριν[^<]{2,30}|Μόλις[^<]{0,20}|Σήμερα[^<]{0,20}|\d{1,2}/\d{1,2}/\d{4})\s*<", footer)
        img = re.search(r'<img src="(https://blob\.cdn\.xe\.gr/[^"]+)"', block)
        out.append({
            "source_domain": "xe.gr",
            # no owner title and no realtor page = a private owner's ad
            "agency": text_of(owner.group(1)) if owner else ("" if owner_link else "Ιδιώτης (XE.gr)"),
            "url": href.group(1) if href else "",
            "title": title + " · " + testid(block, "property_ad_address"),
            "transaction": tx,
            "type": "",
            "price_eur": num(price) if re.search(r"\d", price) else "",
            "area_m2": num(area.group(1)) if area else "",
            "bedrooms": re.sub(r"\D", "", testid(block, "property_ad_icon_bedroom")),
            "floor": testid(block, "property_ad_icon_levels_new"),
            "year_built": re.sub(r"\D", "", testid(block, "property_ad_icon_house_construction"))[:4],
            "location": testid(block, "property_ad_address"),
            "lat": "", "lon": "",
            "image": html.unescape(img.group(1)) if img else "",
            "date_published": "",
            "date_updated": rel_date(when.group(1), today) if when else "",
            "date_sitemap": "",
            "date_source": "xe card",
            "xe_id": ad_id,
            "owner_url": owner_link.group(1) if owner_link else "",
            "scraped_at": datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        })
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-pages", type=int, default=0, help="limit result pages (0 = all)")
    a = ap.parse_args()
    urls = []
    for sm in SITEMAPS:
        try:
            xml = fetch(sm)
        except Exception as e:
            print(f"sitemap failed {sm}: {e}", file=sys.stderr)
            continue
        locs = [html.unescape(u) for u in re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", xml)]
        keep = [u for u in locs if "?" not in u and THESS.search(u.rsplit("_", 1)[-1] if "_" in u else u)]
        print(f"{sm.rsplit('/results/', 1)[-1]}: {len(keep)} of {len(locs)} result pages in Thessaloniki", file=sys.stderr)
        urls += keep
        time.sleep(DELAY_S)
    urls = list(dict.fromkeys(urls))
    if a.max_pages:
        urls = urls[:a.max_pages]
    today = datetime.date.today()
    fields = ["source_domain", "agency", "url", "title", "transaction", "type", "price_eur", "area_m2",
              "bedrooms", "floor", "year_built", "location", "lat", "lon", "image",
              "date_published", "date_updated", "date_sitemap", "date_source", "xe_id", "owner_url", "scraped_at"]
    # resume: keep what earlier runs saved, skip result pages already read today
    import os
    listings, seen, done_pages = [], set(), set()
    if os.path.exists(OUT):
        for r in csv.DictReader(open(OUT, encoding="utf-8")):
            listings.append(r)
            seen.add(r["xe_id"])
    progress = OUT + ".pages"
    if os.path.exists(progress):
        done_pages = set(open(progress, encoding="utf-8").read().split())
    f = open(OUT, "a" if listings else "w", newline="", encoding="utf-8")
    w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
    if not listings:
        w.writeheader()
    fails = 0
    todo = [u for u in urls if u not in done_pages]
    print(f"{len(todo)} result pages to read ({len(done_pages)} done earlier), {len(listings)} listings saved", file=sys.stderr)
    for i, u in enumerate(todo, 1):
        try:
            page = fetch(u)
            fails = 0
        except Exception as e:
            fails += 1
            print(f"skip {u[-60:]}: {getattr(e, 'code', type(e).__name__)}", file=sys.stderr)
            if fails >= MAX_FAILS_IN_ROW:
                print(f"stopping: {fails} refusals in a row; resume later", file=sys.stderr)
                break
            time.sleep(DELAY_S * 3)
            continue
        new = [r for r in parse_cards(page, u, today) if r["xe_id"] and r["xe_id"] not in seen]
        for r in new:
            seen.add(r["xe_id"])
        w.writerows(new)
        f.flush()
        with open(progress, "a", encoding="utf-8") as pf:
            pf.write(u + "\n")
        listings += new
        if i % 20 == 0:
            print(f"{i}/{len(todo)} pages, {len(listings)} listings", file=sys.stderr)
        time.sleep(DELAY_S)
    f.close()
    print(f"done: {len(listings)} unique listings saved", file=sys.stderr)


if __name__ == "__main__":
    main()
