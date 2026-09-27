"""Build the one-file search page from normalized listings.

Usage: python3 scripts/build_search_page.py OUT.html
Reads data/listings/listings_normalized.csv and web/search_template.html.
"""
import csv
import datetime
import json
import sys

rows = []
for r in csv.DictReader(open("data/listings/listings_normalized.csv", encoding="utf-8")):
    num = lambda k: float(r[k]) if r[k] else None
    rows.append({"u": r["url"], "t": r["title"][:140], "ag": r["agency"], "tx": r["transaction"], "ty": r["type"],
                 "p": num("price_eur"), "m": num("area_m2"), "pm": num("price_per_m2"), "bd": r["bedrooms"][:2],
                 "fl": r["floor"][:10], "yr": r["year_built"], "rg": r["region"], "ar": r["area"],
                 "lr": r["location_raw"][:40], "ld": r.get("listing_date", ""),
                 "lk": r.get("listing_date_kind", ""), "fs": r.get("first_seen", ""),
                 "src": r.get("source_domain", ""), "pv": r.get("private_owner", "")})
page = open("web/search_template.html", encoding="utf-8").read()
data = json.dumps(rows, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
asof = max((r["scraped_at"] for r in csv.DictReader(open("data/listings/listings_normalized.csv", encoding="utf-8"))), default="")[:10]
asof = datetime.date.fromisoformat(asof).strftime("%d.%m.%Y") if asof else ""
open(sys.argv[1], "w", encoding="utf-8").write(page.replace("__DATA__", data).replace("__ASOF__", asof))
print(f"{len(rows)} listings -> {sys.argv[1]}")
