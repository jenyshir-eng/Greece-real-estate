"""Collect real estate agencies from the vrisko.gr directory into a CSV.

Reads the public category pages (allowed by robots.txt), takes name, address,
phones and coordinates from the page's JSON-LD and the website from the
listing's "Website" link.

The directory shows at most ~9 pages per area, so large areas are collected
by sweeping several area slugs and merging (duplicates removed by vrisko URL).

Usage: python3 scripts/collect_vrisko_agencies.py OUT.csv AREA [AREA ...]
"""
import csv
import json
import re
import sys
import time
import urllib.error
import urllib.request

BASE = "https://www.vrisko.gr/dir/mesites-astikon-symbaseon/{area}/?page={page}"
UA = "Mozilla/5.0 (compatible; SpitiRadarBot/0.1; +https://spitiradar.gr)"
DELAY_S = 3


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "el,en"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", "replace")


def parse(html):
    # JSON-LD ItemList with one entry per agency
    items = []
    for block in re.findall(r'<script type="application/ld\+json">(.*?)</script>', html, re.S):
        try:
            data = json.loads(block)
        except ValueError:
            continue
        nodes = data.get("@graph", [data]) if isinstance(data, dict) else data
        for node in nodes:
            if isinstance(node, dict) and node.get("@type") == "ItemList":
                items += [e["item"] for e in node.get("itemListElement", [])]

    # Each listing starts with a name header; take its details URL and "Website" link
    detail_to_site, detail_to_name = {}, {}
    chunks = re.split(r'<div[^>]*class="(?:Free|Adv)NameHeader"', html)[1:]
    for chunk in chunks:
        nav = re.search(r'class="nav-company" href="([^"]+)"[^>]*>(.*?)</a>', chunk, re.S)
        if not nav:
            continue
        detail = nav.group(1)
        detail_to_name[detail] = re.sub(r"<[^>]+>|\s+", " ", nav.group(2)).strip()
        for tag in re.findall(r"<a\s[^>]*urlClickLoggingClass[^>]*>", chunk):
            href = re.search(r'href=["\'](http[^"\']+)', tag)
            if href:
                detail_to_site[detail] = href.group(1)
                break
    known = {it.get("url") for it in items}
    items += [{"name": n, "url": u} for u, n in detail_to_name.items() if u not in known]

    rows = []
    for it in items:
        addr = it.get("address") or {}
        geo = (it.get("location") or {}).get("geo") or {}
        phones = it.get("telephone") or []
        site = detail_to_site.get(it.get("url"), "")
        rows.append({
            "name": it.get("name", "").strip(),
            "website": site,
            "street": addr.get("streetAddress", ""),
            "locality": addr.get("addressLocality", ""),
            "postal_code": addr.get("postalCode", ""),
            "phones": ";".join(phones if isinstance(phones, list) else [phones]),
            "email": it.get("email", ""),
            "lat": geo.get("latitude", ""),
            "lon": geo.get("longitude", ""),
            "vrisko_url": it.get("url", ""),
        })
    return rows


def collect_area(area, rows, seen):
    page = 1
    while True:
        html = None
        for attempt in range(3):
            try:
                html = fetch(BASE.format(area=area, page=page))
                break
            except urllib.error.HTTPError as e:
                print(f"{area}: HTTP {e.code}, skipped", file=sys.stderr)
                return
            except (urllib.error.URLError, TimeoutError, OSError) as e:
                print(f"{area} page {page}: {e}, retry {attempt + 1}", file=sys.stderr)
                time.sleep(10 * (attempt + 1))
        if html is None:
            print(f"{area}: no answer, skipped", file=sys.stderr)
            return
        batch = [r for r in parse(html) if r["vrisko_url"] not in seen]
        if not batch:
            return
        for r in batch:
            seen.add(r["vrisko_url"])
            r["vrisko_area"] = area
        rows += batch
        print(f"{area} page {page}: +{len(batch)} (total {len(rows)})", file=sys.stderr)
        page += 1
        time.sleep(DELAY_S)


def main(out_path, areas):
    rows, seen = [], set()
    for area in areas:
        collect_area(area, rows, seen)
    if not rows:
        sys.exit("vrisko.gr: nothing collected")
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2:])
