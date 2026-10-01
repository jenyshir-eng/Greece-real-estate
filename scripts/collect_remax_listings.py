"""Collect Thessaloniki listings from remax.gr result pages (all RE/MAX offices).

remax.gr lists every office's properties on area result pages such as
https://www.remax.gr/pwliseis-agora-katoikies/108 (area 108 = Thessaloniki
municipality, 109 = the other municipalities of the prefecture). robots.txt
allows these pages and the property pages; paging is ?Property_page=N.

Each card gives: RE/MAX id, property URL, category, approximate location
(neighbourhood), municipality, rooms, floor, m2, price, office and a thumbnail.
Property pages add the approximate map point ("var $lat/$lng"); only listings
without a point are opened, at most --coords a day.

Usage: python3 scripts/collect_remax_listings.py [--areas 108 109] [--coords 60] [--max-minutes 25] [--max-pages 0]
The daily run has a time budget: when it is spent the run stops, keeps the listings it had and
saves what it found; the next run starts from the first page again.
Output: data/listings/listings_remax.csv (same columns as listings_thessaloniki.csv + remax_id, job);
        a listing seen on a result page is checked that day (checked_at: price and availability);
        listings missing from a category/area that this run read to the last page without errors
        are dropped and written to data/listings/removed.csv.
"""
import argparse
import csv
import datetime
import html
import os
import re
import sys
import time
import urllib.error
import urllib.request

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/128.0 Safari/537.36 SpitiRadar/0.1 (+https://spitiradar.gr/opt-out)")
BASE = "https://www.remax.gr"
DELAY_S = 5.0     # remax.gr answers 403 to faster runs
MAX_FAILS_IN_ROW = 5
OUT = "data/listings/listings_remax.csv"
REMOVED = "data/listings/removed.csv"
CATEGORIES = {  # url part -> transaction
    "pwliseis-agora-katoikies": "sale", "pwliseis-agora-epaggelmatika": "sale", "pwliseis-agora-gi": "sale",
    "enoikiaseis-katoikies": "rent", "enoikiaseis-epaggelmatika": "rent", "enoikiaseis-gi": "rent",
}
FIELDS = ["source_domain", "agency", "url", "title", "transaction", "type", "price_eur", "area_m2",
          "bedrooms", "floor", "year_built", "location", "lat", "lon", "image",
          "date_published", "date_updated", "date_sitemap", "date_source", "scraped_at", "remax_id",
          "checked_at", "job"]

_last = [0.0]
DEADLINE = float("inf")


def fetch(url, retries=2):
    """remax.gr often answers 500 or 403 to a page that loads fine a few seconds later:
    retry twice after a longer pause before counting it as a refusal."""
    for attempt in range(retries + 1):
        wait = DELAY_S * (1 + 4 * attempt) - (time.time() - _last[0])
        if wait > 0:
            time.sleep(wait)
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "el"})
        try:
            with urllib.request.urlopen(req, timeout=40) as r:
                return r.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            if attempt == retries or e.code not in (403, 500, 502, 503, 504):
                raise
        finally:
            _last[0] = time.time()


def text_of(fragment):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", fragment or ""))).strip()


def cls(block, name):
    """Text of the first element with this class inside a card."""
    m = re.search(r'class="%s"[^>]*>(.*?)</div>' % re.escape(name), block, re.S)
    return text_of(m.group(1)) if m else ""


def feature(block, name):
    m = re.search(r'class="feature %s".*?class="label">(.*?)</span>' % re.escape(name), block, re.S)
    return text_of(m.group(1)) if m else ""


def num(s):
    s = re.sub(r"[^\d.,]", "", s or "")
    if re.fullmatch(r"\d{1,3}([.,]\d{3})+", s):
        s = re.sub(r"[.,]", "", s)
    else:
        s = s.replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return ""


def parse_cards(page, tx, now):
    out = []
    # a card starts at its "property-miniature" block (id + photos) and holds the info block after it
    starts = [m.start() for m in re.finditer(r'<div class="property-miniature"', page)]
    for i, st in enumerate(starts):
        block = page[st:starts[i + 1] if i + 1 < len(starts) else st + 12000]
        href = re.search(r'href="(/property/(\d+)-[^"?#]+)"', block)
        if not href:
            continue
        price = cls(block, "price")
        area = feature(block, "sqrMeters")
        img = re.search(r'<img[^>]+src="(/assets/media/properties/[^"]+)"', block)
        office = re.search(r'class="office-name">(.*?)</div>', block, re.S)
        category = cls(block, "category")
        place = re.search(r'<h4 class="title">(.*?)</h4>', block, re.S)
        place = text_of(place.group(1)) if place else ""
        muni = cls(block, "path")
        out.append({
            "source_domain": "remax.gr",
            "agency": text_of(office.group(1)) if office else "REMAX",
            "url": BASE + href.group(1),
            "title": " · ".join(x for x in (category, place, muni) if x),
            "transaction": tx,
            "type": "",
            "price_eur": num(price) if re.search(r"\d", price) else "",
            "area_m2": num(re.sub(r"m\s*2.*", "", area)) if area else "",
            "bedrooms": re.sub(r"\D", "", feature(block, "rooms")),
            "floor": feature(block, "floor"),
            "year_built": "",
            "location": ", ".join(x for x in (place, muni) if x),
            "lat": "", "lon": "",
            "image": BASE + html.unescape(img.group(1)) if img else "",
            "date_published": "", "date_updated": "", "date_sitemap": "",
            "date_source": "",
            "scraped_at": now,
            "checked_at": now[:10],
            "remax_id": href.group(2),
        })
    return out


def paging(page, cat, area):
    """Last page number and the area path the page links use for pages 2.. (/cat/108 or /cat/108-slug)."""
    links = re.findall(r'href="(/%s/%s(?:-[^"?]+)?)\?Property_page=(\d+)"' % (re.escape(cat), re.escape(area)), page)
    if not links:
        return 1, None
    return max(int(n) for _, n in links), links[0][0]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--areas", nargs="+", default=["108", "109"])
    ap.add_argument("--coords", type=int, default=60, help="property pages opened for the map point (0 = none)")
    ap.add_argument("--max-minutes", type=float, default=25, help="time budget for the whole run (result pages + map points)")
    ap.add_argument("--max-pages", type=int, default=0, help="limit result pages (test runs)")
    a = ap.parse_args()
    global DEADLINE
    DEADLINE = time.time() + a.max_minutes * 60
    now = datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    old = {}
    if os.path.exists(OUT):
        old = {r["remax_id"]: r for r in csv.DictReader(open(OUT, encoding="utf-8"))}
    found, pages, fails, complete, done_jobs = {}, 0, 0, True, set()
    # with the time budget a run covers part of the site: start each day at a different
    # area/category so every part is refreshed within a few days
    jobs = [(area, cat, tx) for area in a.areas for cat, tx in CATEGORIES.items()]
    k = datetime.date.today().toordinal() % len(jobs)
    for area, cat, tx in jobs[k:] + jobs[:k]:
        n, last, path, job_ok = 1, 1, f"/{cat}/{area}", True
        while n <= last:
            if (a.max_pages and pages >= a.max_pages) or time.time() > DEADLINE:
                complete = job_ok = False
                break
            # page 1 by area id; later pages under the path the page itself links to
            url = BASE + path + (f"?Property_page={n}" if n > 1 else "")
            try:
                page = fetch(url)
                fails = 0
            except (urllib.error.URLError, TimeoutError) as e:
                fails += 1
                complete = job_ok = False
                print(f"skip {url}: {getattr(e, 'code', type(e).__name__)}", file=sys.stderr)
                if fails >= MAX_FAILS_IN_ROW:
                    print("stopping: repeated refusals; the listings file keeps earlier rows", file=sys.stderr)
                    return save(old, found, False, a.coords, done_jobs)
                n += 1
                continue
            pages += 1
            lp, full = paging(page, cat, area)
            last, path = max(last, lp), full or path
            cards = parse_cards(page, tx, now)
            for c in cards:
                c["job"] = f"{area}/{cat}"
                found.setdefault(c["remax_id"], c)
            if not cards:
                break
            n += 1
        if job_ok:
            done_jobs.add(f"{area}/{cat}")
        print(f"{area}/{cat}: {last} pages, {len(found)} listings so far", file=sys.stderr)
    save(old, found, complete, a.coords, done_jobs)


def save(old, found, complete, coords, done_jobs=frozenset()):
    rows = {}
    # listings gone from a fully read category/area are dropped; others stay until their part is read
    gone = [r for k, r in old.items() if k not in found and (complete or r.get("job") in done_jobs)]
    gone_ids = {r["remax_id"] for r in gone}
    log_removed(gone)
    for k, r in [(k, r) for k, r in old.items() if k not in gone_ids] + list(found.items()):
        prev = old.get(k, {})
        for f in ("lat", "lon"):  # the map point was read once; keep it
            r[f] = r.get(f) or prev.get(f, "")
        rows[k] = r
    todo = [r for r in rows.values() if not r["lat"]][:coords]
    for i, r in enumerate(todo, 1):
        if time.time() > DEADLINE:
            print(f"time budget spent: {i - 1} map points this run", file=sys.stderr)
            break
        try:
            page = fetch(r["url"], retries=0)  # a missing map point is not worth long waits
        except (urllib.error.URLError, TimeoutError) as e:
            print(f"no point for {r['url']}: {getattr(e, 'code', type(e).__name__)}", file=sys.stderr)
            continue
        lat = re.search(r"var \$lat\s*=\s*(-?\d+\.\d+)", page)
        lon = re.search(r"var \$lng\s*=\s*(-?\d+\.\d+)", page)
        if lat and lon:
            r["lat"], r["lon"] = lat.group(1), lon.group(1)
        if i % 50 == 0:
            print(f"map points: {i}/{len(todo)}", file=sys.stderr)
    tmp = OUT + ".tmp"
    with open(tmp, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore")
        w.writeheader()
        w.writerows(sorted(rows.values(), key=lambda r: int(r["remax_id"])))
    os.replace(tmp, OUT)
    print(f"done: {len(rows)} listings ({len(found)} seen this run, complete={complete}, "
          f"{len(done_jobs)} parts read fully, {len(gone)} removed), "
          f"{sum(1 for r in rows.values() if r['lat'])} with a map point", file=sys.stderr)


def log_removed(rows):
    if not rows:
        return
    new = not os.path.exists(REMOVED)
    today = datetime.datetime.utcnow().strftime("%Y-%m-%d")
    with open(REMOVED, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if new:
            w.writerow(["date", "source_domain", "url", "reason"])
        w.writerows([today, "remax.gr", r["url"], "not on result pages"] for r in rows)


if __name__ == "__main__":
    main()
