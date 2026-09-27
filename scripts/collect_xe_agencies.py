"""Collect real estate agencies from xe.gr for one region.

xe.gr publishes all agency profile pages in its sitemap
(https://www.xe.gr/sitemap/property/real-estate-agencies; agency pages are
allowed by robots.txt). Each profile shows the office address; we keep agencies
whose postal code falls in the given prefixes.

Usage: python3 scripts/collect_xe_agencies.py OUT.csv [POSTAL_PREFIX ...]
Default prefixes cover Thessaloniki prefecture (54x, 55x, 56x, 570-572).
"""
import csv
import html
import re
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor

SITEMAP = "https://www.xe.gr/sitemap/property/real-estate-agencies"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0 Safari/537.36 SpitiRadar/0.1"
WORKERS = 3
DELAY_S = 1.0
READ_BYTES = 160_000  # the address block sits in the first ~110 KB


def fetch(url, limit=None):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "el"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read(limit).decode("utf-8", "replace") if limit else r.read().decode("utf-8", "replace")


def parse(url, page):
    name = re.search(r"<title>([^<|]+)", page)
    addr = re.search(r"Διεύθυνση:\s*</[^>]+>\s*(?:<[^>]+>\s*)*([^<]+)", page)
    address = html.unescape(addr.group(1)).strip() if addr else ""
    pc = re.search(r"\b(\d{3})\s?(\d{2})\b", address)
    return {
        "name": html.unescape(name.group(1)).strip() if name else "",
        "address": address,
        "postal_code": (pc.group(1) + pc.group(2)) if pc else "",
        "xe_url": url,
    }


def main(out_path, prefixes):
    urls = [u for u in re.findall(r"<loc>([^<]+)</loc>", fetch(SITEMAP)) if "/mesitiko-grafeio/" in u]
    print(f"{len(urls)} agency pages", file=sys.stderr)

    def work(url):
        time.sleep(DELAY_S)
        for attempt in range(2):
            try:
                return parse(url, fetch(url, READ_BYTES))
            except Exception:
                time.sleep(5)
        return {"name": "", "address": "", "postal_code": "", "xe_url": url}

    rows = []
    with ThreadPoolExecutor(WORKERS) as ex:
        for i, r in enumerate(ex.map(work, urls), 1):
            rows.append(r)
            if i % 250 == 0:
                print(f"{i}/{len(urls)}", file=sys.stderr)
    keep = [r for r in rows if r["postal_code"].startswith(tuple(prefixes))]
    print(f"kept {len(keep)} of {len(rows)} (no address: {sum(not r['address'] for r in rows)})", file=sys.stderr)
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["name", "address", "postal_code", "xe_url"])
        w.writeheader()
        w.writerows(keep)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2:] or ["54", "55", "56", "570", "571", "572"])
