"""XE.gr listings of Thessaloniki agencies, from their public agency pages.

XE result pages are closed to cloud servers and to robots (Disallow: /property/results), but the
agency profile pages (/property/s/mesitiko-grafeio/...) and the listing pages (/property/d/...)
are allowed. A profile page carries the agency's latest listings in carousels
(data-ads-data JSON): price, area, type, floor, bedrooms, year, address, map point, link.

Daily:
  1. every agency of data/sources/agencies_thessaloniki.csv with an xe_url: read its profile,
     take the listings (new ones are added, known ones are checked: price refreshed);
  2. re-check listings not seen on a profile for a week on their own page, oldest first
     (--recheck a run): 200 = still online (price from the page title), a redirect away = removed
     (data/listings/removed.csv).
Descriptions, photos and contact details are not stored.

Usage: python3 scripts/collect_xe_profiles.py [--max-profiles 0] [--recheck 150] [--max-minutes 20]
Output: data/listings/listings_xe_profiles.csv (columns of listings_thessaloniki.csv + xe_id, checked_at, seen_at)
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
REGISTRY = "data/sources/agencies_thessaloniki.csv"
OUT = "data/listings/listings_xe_profiles.csv"
REMOVED = "data/listings/removed.csv"
DELAY_S = 3.0
MAX_FAILS_IN_ROW = 6
FIELDS = ["source_domain", "agency", "url", "title", "transaction", "type", "price_eur", "area_m2",
          "bedrooms", "floor", "year_built", "location", "lat", "lon", "image",
          "date_published", "date_updated", "date_sitemap", "date_source", "scraped_at", "xe_id", "checked_at", "seen_at"]
TYPES = {"APARTMENT": "apartment", "STUDIO": "studio", "MAISONETTE": "maisonette", "DETACHED_HOUSE": "house",
         "HOUSE": "house", "VILLA": "house", "BUILDING": "building", "APARTMENT_COMPLEX": "building",
         "PARCEL": "land", "PLOT": "land", "LAND": "land", "STORE": "store", "OFFICE": "office",
         "WAREHOUSE": "warehouse", "INDUSTRIAL_SPACE": "warehouse", "PARKING": "parking", "HOTEL": "hotel"}
_last = [0.0]


class Gone(Exception):
    pass


def fetch(url):
    """Polite GET; a redirect to another page raises Gone (XE answers 302 for removed listings)."""
    wait = DELAY_S - (time.time() - _last[0])
    if wait > 0:
        time.sleep(wait)

    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *a, **k):
            return None

    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "el"})
    try:
        with urllib.request.build_opener(NoRedirect).open(req, timeout=40) as r:
            return r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        if e.code in (301, 302, 303, 307, 308, 404, 410):
            raise Gone(f"http {e.code} -> {e.headers.get('Location', '')[:100]}")
        raise
    finally:
        _last[0] = time.time()


def money(s):
    m = re.search(r"(\d{1,3}(?:\.\d{3})+|\d+)", (s or "").replace("\xa0", " "))
    return float(m.group(1).replace(".", "")) if m else ""


def ago(literal, today):
    """'Πριν 3 ημέρες' / 'Πριν 18 εβδομάδες' / 'πριν από 2 ημέρες' -> date (approximate)."""
    m = re.search(r"(\d+)\s*(λεπτ|ώρ|ωρ|ημέρ|ημερ|μέρ|μερ|εβδομ|μήν|μην|χρόν|χρον)", (literal or "").lower())
    if not m:
        return today.isoformat() if re.search(r"σήμερα|λεπτ|ώρ", (literal or "").lower()) else ""
    n, unit = int(m.group(1)), m.group(2)
    days = 0 if unit[0] in "λώω" else n * {"η": 1, "μ": 1, "ε": 7}.get(unit[0], 30)
    if unit.startswith(("μήν", "μην")):
        days = n * 30
    if unit.startswith("χρ"):
        days = n * 365
    return (today - datetime.timedelta(days=days)).isoformat()


def row_from(it, now):
    today = datetime.date.fromisoformat(now[:10])
    size = re.search(r"(\d+(?:[.,]\d+)?)", it.get("size_with_square_meter") or "")
    levels = it.get("levels") or []
    title = " · ".join(x for x in (it.get("title"), it.get("address")) if x)
    return {
        "source_domain": "xe.gr",
        "agency": (it.get("company_title") or "").strip(),
        "url": it["url"],
        "title": title,
        "transaction": {"SALE": "sale", "RENT": "rent"}.get(it.get("transaction_type"), ""),
        "type": TYPES.get(it.get("type") or "", ""),
        "price_eur": money(it.get("price")),
        "area_m2": float(size.group(1).replace(",", ".")) if size else "",
        "bedrooms": it.get("bedrooms") or "",
        "floor": levels[0] if levels else "",
        "year_built": it.get("construction_year") or "",
        "location": it.get("address") or "",
        "lat": "" if it.get("geo_is_address_hidden") else (it.get("geo_lat") or ""),
        "lon": "" if it.get("geo_is_address_hidden") else (it.get("geo_lng") or ""),
        "image": "",
        "date_published": ago(it.get("active_time_literal") or it.get("date"), today),
        "date_updated": "", "date_sitemap": "",
        "date_source": "xe.gr agency page",
        "scraped_at": now,
        "xe_id": it.get("id", ""),
        "checked_at": now[:10],
        "seen_at": now[:10],
    }


def profile_items(page):
    items = []
    for raw in re.findall(r'data-ads-data="([^"]*)"', page):
        try:
            items += json.loads(html.unescape(raw))
        except ValueError:
            continue
    return [it for it in items if isinstance(it, dict) and it.get("url") and it.get("id")]


def log_removed(gone, today):
    if not gone:
        return
    new = not os.path.exists(REMOVED)
    with open(REMOVED, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if new:
            w.writerow(["date", "source_domain", "url", "reason"])
        w.writerows([today, "xe.gr", r["url"], why] for r, why in gone)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-profiles", type=int, default=0, help="limit agency pages (test runs)")
    ap.add_argument("--recheck", type=int, default=150, help="listing pages re-checked per run")
    ap.add_argument("--max-minutes", type=float, default=20)
    a = ap.parse_args()
    deadline = time.time() + a.max_minutes * 60
    now = datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    today = now[:10]
    old = {r["xe_id"]: r for r in csv.DictReader(open(OUT, encoding="utf-8"))} if os.path.exists(OUT) else {}
    profiles = sorted({r["xe_url"] for r in csv.DictReader(open(REGISTRY, encoding="utf-8")) if r.get("xe_url")})
    # a different start each day, so a run cut by the time limit still covers every agency in a few days
    k = datetime.date.today().toordinal() % max(1, len(profiles))
    profiles = profiles[k:] + profiles[:k]
    if a.max_profiles:
        profiles = profiles[:a.max_profiles]
    rows, fails, read, new, changed = dict(old), 0, 0, 0, 0
    for i, url in enumerate(profiles, 1):
        if time.time() > deadline:
            print(f"time budget spent after {read} agency pages", file=sys.stderr)
            break
        try:
            page = fetch(url)
            fails = 0
        except Gone:
            continue  # the agency left XE
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            fails += 1
            print(f"skip {url}: {getattr(e, 'code', type(e).__name__)}", file=sys.stderr)
            if fails >= MAX_FAILS_IN_ROW:
                print("stopping: repeated refusals; earlier listings are kept", file=sys.stderr)
                break
            continue
        read += 1
        for it in profile_items(page):
            r = row_from(it, now)
            prev = old.get(r["xe_id"])
            if prev is None:
                new += 1
            else:
                r["date_published"] = prev.get("date_published") or r["date_published"]
                if str(prev.get("price_eur")) != str(r["price_eur"]):
                    changed += 1
            rows[r["xe_id"]] = r
        if i % 25 == 0:
            print(f"{i}/{len(profiles)} agency pages, {len(rows)} listings", file=sys.stderr)

    # listings not on a profile lately: their own page tells if they are still online
    week_ago = (datetime.date.today() - datetime.timedelta(days=7)).isoformat()
    due = sorted((r for r in rows.values() if (r.get("checked_at") or "") <= week_ago), key=lambda r: r.get("checked_at") or "")
    gone, rechecked = [], 0
    for r in due[:a.recheck]:
        if time.time() > deadline + 5 * 60:
            break
        try:
            page = fetch(r["url"])
        except Gone as e:
            gone.append((r, str(e)))
            rows.pop(r["xe_id"], None)
            continue
        except (urllib.error.URLError, TimeoutError, OSError):
            continue
        rechecked += 1
        t = re.search(r'og:title"\s+content="([^"]*)"', page)
        price = money(html.unescape(t.group(1)).rsplit(",", 1)[-1]) if t and "€" in t.group(1) else ""
        r.update(checked_at=today, scraped_at=now, **({"price_eur": price} if price else {}))
    log_removed(gone, today)
    tmp = OUT + ".tmp"
    with open(tmp, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore")
        w.writeheader()
        w.writerows(sorted(rows.values(), key=lambda r: r["url"]))
    os.replace(tmp, OUT)
    print(f"done: {len(rows)} XE listings from {read} agency pages; {new} new, {changed} price changes, "
          f"{rechecked} re-checked, {len(gone)} removed", file=sys.stderr)


if __name__ == "__main__":
    main()
