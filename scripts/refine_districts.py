"""Find the district of listings that only say "Θεσσαλονίκη" (or nothing) by reading
their page once more: address in JSON-LD, breadcrumbs, "Περιοχή:" style labels, then
the main text (menus, headers, footers and side lists are skipped, since they name
every district). Only the district / neighbourhood found is kept, not the page text.

Each page is checked once (results cached for --recheck-days), politely: >= 3 s
between requests to one site, robots Crawl-delay honored, at most --max-pages a day.
Portal pages are not read (their detail pages are off limits).

Output: data/listings/district_hints.csv (url, region, area, neighbourhood, how, checked_at)
        used by scripts/normalize_listings.py
Usage: python3 scripts/refine_districts.py [--max-pages 1500] [--workers 25]
"""
import argparse
import csv
import datetime
import json
import os
import re
import sys
import threading
import urllib.parse
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(__file__))
from collect_listings import Site, extract, robots_setup  # noqa: E402
import districts  # noqa: E402
from normalize_listings import AREAS, PORTALS, in_thessaloniki_unit, is_other, plain  # noqa: E402

NORMALIZED = "data/listings/listings_normalized.csv"
HINTS = "data/listings/district_hints.csv"
FIELDS = ["url", "region", "area", "neighbourhood", "how", "checked_at"]
SPECIFIC = [(n, p) for n, p in AREAS if n not in ("Θεσσαλονίκη", "Πυλαία-Χορτιάτης")]
BOILERPLATE = re.compile(r"<(script|style|nav|header|footer|aside|noscript|form|select)\b.*?</\1>", re.S | re.I)
BOILER_BLOCK = re.compile(
    r"<(div|ul|section)\b[^>]*(?:class|id)=[\"'][^\"']*(menu|footer|navbar|sidebar|widget|related|similar|"
    r"recent|featured|breadcrumb-menu|cookie|mega)[^\"']*[\"'][^>]*>.*?</\1>", re.S | re.I)
LABEL = re.compile(r"(?:Περιοχή|Τοποθεσία|Διεύθυνση|Location|Area|Address|Region|Neighbou?rhood)\s*:?\s*</?[^>]*>?\s*([^<\n]{3,80})", re.I)


def one(names):
    names = list(dict.fromkeys(n for n in names if n))
    return names[0] if len(names) == 1 else ""


def districts_in(text):
    return [n for n, pat in SPECIFIC if re.search(pat, text)]


def neighbourhoods_in(text):
    """Map areas (Jeny Shir's Thessaloniki map) named in text -> [(id, district)]."""
    return [(i, districts.AREAS[i]["district"]) for i, pat in districts._compiled if pat.search(text)]


def jsonld_address(page):
    """Address parts and breadcrumb names from JSON-LD."""
    parts = []
    for block in re.findall(r"<script[^>]+application/ld\+json[^>]*>(.*?)</script>", page, re.S | re.I):
        for key in ("addressLocality", "streetAddress", "addressRegion"):
            parts += re.findall(r'"%s"\s*:\s*"([^"]{2,120})"' % key, block)
        if "BreadcrumbList" in block:
            parts += re.findall(r'"name"\s*:\s*"([^"]{2,80})"', block)
    return plain(" ".join(parts))


def decide(page):
    """-> (region, area, neighbourhood, how) or None."""
    # the listing's own place line / fields and the map point on the page (scripts/collect_listings.py)
    rec = extract("", page)
    place = plain(rec["location"])
    if is_other(place) and not districts_in(place):
        return "other", "", "", "place"
    try:
        lat, lon = float(rec["lat"]), float(rec["lon"])
        if not in_thessaloniki_unit(lat, lon):
            return "other", "", "", "map point"
    except ValueError:
        pass
    structured = jsonld_address(page)
    crumbs = " ".join(re.sub(r"<[^>]+>", " ", b) for b in
                      re.findall(r"<(?:ol|ul|nav|div)[^>]*breadcrumb[^>]*>(.*?)</(?:ol|ul|nav|div)>", page, re.S | re.I))
    labels = " ".join(LABEL.findall(page))
    body = BOILER_BLOCK.sub(" ", BOILERPLATE.sub(" ", page))
    # the listing's own text: from its heading on, before "similar listings" and the like
    h1 = re.search(r"<h1\b", body, re.I)
    start = h1.start() if h1 else 0
    text = re.sub(r"<[^>]+>", " ", body[start:start + 12000])
    text = re.split(r"(?i)παρόμοια|παρομοια|σχετικά ακίνητα|σχετικα ακινητα|similar|related|you may also|δείτε επίσης|δειτε επισησ",
                    text)[0][:2500]
    for how, src in (("address", structured), ("breadcrumb", plain(crumbs)), ("label", plain(labels)),
                     ("text", plain(re.sub(r"\s+", " ", text)))):
        if not src.strip():
            continue
        nbs = neighbourhoods_in(src)
        area = one(districts_in(src))
        nb = one([n for n, _ in nbs])
        if nb:
            parent = dict((n, p) for n, p in nbs)[nb]
            if not area or area == parent:
                area = parent
            else:
                nb = ""
        if is_other(src) and not area:
            return ("other", "", "", how) if how != "text" else None
        if area:
            return "thessaloniki", area, nb, how
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-pages", type=int, default=1500)
    ap.add_argument("--per-site", type=int, default=80)
    ap.add_argument("--workers", type=int, default=25)
    ap.add_argument("--recheck-days", type=int, default=60)
    ap.add_argument("--retry-days", type=int, default=7, help="pages where nothing was found: read again after")
    a = ap.parse_args()
    hints = {}
    if os.path.exists(HINTS):
        hints = {r["url"]: r for r in csv.DictReader(open(HINTS, encoding="utf-8"))}
    cutoff = (datetime.date.today() - datetime.timedelta(days=a.recheck_days)).isoformat()
    retry = (datetime.date.today() - datetime.timedelta(days=a.retry_days)).isoformat()
    todo = defaultdict(list)
    for r in csv.DictReader(open(NORMALIZED, encoding="utf-8")):
        if r["source_domain"] in PORTALS or r["region"] == "other":
            continue
        # district known from the listing itself: nothing to check
        if r["area"] not in ("", "Θεσσαλονίκη") and r.get("region_how") != "agency":
            continue
        h = hints.get(r["url"])
        # pages where nothing was found are read again after a week (the reader improves)
        if h and h["checked_at"] >= (cutoff if h["how"] else retry):
            continue
        todo[r["source_domain"]].append(r["url"])
    # spread the daily budget over sites
    plan, budget = {}, a.max_pages
    for d in sorted(todo, key=lambda d: len(todo[d])):
        share = min(len(todo[d]), a.per_site, max(1, budget // max(1, len(todo) - len(plan))))
        plan[d], budget = todo[d][:share], budget - share
    total = sum(len(v) for v in plan.values())
    print(f"{sum(len(v) for v in todo.values())} listings without district; checking {total} today", file=sys.stderr)
    lock, found = threading.Lock(), defaultdict(int)
    today = datetime.date.today().isoformat()

    def work(item):
        domain, urls = item
        site = Site("https://" + urllib.parse.urlparse(urls[0]).netloc + "/")
        robots_setup(site)
        for u in urls:
            try:
                _, page = site.get(u)
                res = decide(page)
            except Exception:
                res = None
            row = {"url": u, "region": "", "area": "", "neighbourhood": "", "how": "", "checked_at": today}
            if res:
                row.update(zip(("region", "area", "neighbourhood", "how"), res))
            with lock:
                hints[u] = row
                found[row["how"] or "nothing"] += 1

    with ThreadPoolExecutor(a.workers) as ex:
        list(ex.map(work, plan.items()))
    with open(HINTS, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(sorted(hints.values(), key=lambda r: r["url"]))
    print(f"checked {total}: {dict(found)}", file=sys.stderr)


if __name__ == "__main__":
    main()
