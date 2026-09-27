"""Collect property listings from agency websites (generic, platform-agnostic).

For every collectable agency site in the registry (site_status=ok, listings
found, robots_ok != explicit_no) the collector:
  1. finds listing page URLs - sitemap.xml first, otherwise listing sections
     linked from the home page and their pagination;
  2. fetches up to --per-site listing pages, politely (spec section 2, item 4:
     >= 3 s between requests to one site, Crawl-delay honored);
  3. extracts normalized fields from JSON-LD, OpenGraph and page text.

Descriptions are not stored (spec section 2, item 6) - only normalized fields,
the listing URL and one thumbnail URL.

Usage:
  python3 scripts/collect_listings.py [--per-site 30] [--sites 0] [--workers 20]
Outputs:
  data/listings/listings_thessaloniki.csv
  data/listings/collect_report.csv   (per-site yield)
"""
import argparse
import csv
import datetime
import html
import json
import re
import sys
import threading
import time
import urllib.parse
import urllib.request
import urllib.robotparser
from concurrent.futures import ThreadPoolExecutor

REGISTRY = "data/sources/agencies_thessaloniki.csv"
OUT = "data/listings/listings_thessaloniki.csv"
REPORT = "data/listings/collect_report.csv"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/128.0 Safari/537.36 SpitiRadar/0.1 (+https://spitiradar.gr/opt-out)")
MIN_DELAY_S = 3.0
MAX_PAGES_DISCOVERY = 12

LISTING_HINT = re.compile(
    r"/(property|properties|akinito|akinita|aggelia|aggelies|listing|listings|estate|ad|"
    r"results?|pwlisi|polisi|poleitai|enoikiasi|sale|rent|for-sale|for-rent|diamerisma|"
    r"katoikia|monokatoikia|mezoneta|oikopedo|ακίνητ|πώληση|ενοικίαση)[/-]?", re.I)
DETAIL_ID = re.compile(r"(\d{3,})")
SKIP = re.compile(r"\.(jpg|jpeg|png|webp|gif|svg|pdf|css|js|ico|xml|zip)(\?|$)|"
                  r"/(wp-content|wp-json|feed|tag|category|author|blog|news|contact|epikoinonia|"
                  r"about|profil|login|register|cart|privacy|terms|cookies?)\b|mailto:|tel:|javascript:|#", re.I)
SECTION_TEXT = re.compile(r"ακίνητ|πωλήσ|ενοικιάσ|αγγελ|properties|listings|for sale|for rent|αναζήτ|search", re.I)

TYPES = [
    ("apartment", r"διαμέρισμα|apartment|flat"),
    ("studio", r"γκαρσονιέρα|studio|στούντιο"),
    ("maisonette", r"μεζονέτα|maisonette"),
    ("house", r"μονοκατοικία|detached house|villa|βίλα|κατοικία"),
    ("land", r"οικόπεδο|αγροτεμάχιο|plot|land"),
    ("store", r"κατάστημα|store|shop"),
    ("office", r"γραφείο|office"),
    ("parking", r"θέση στάθμευσης|parking|γκαράζ"),
    ("building", r"κτίριο|building"),
]


def fetch(url, limit=1_500_000):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "el,en;q=0.8"})
    with urllib.request.urlopen(req, timeout=25) as r:
        return r.geturl(), r.read(limit).decode("utf-8", "replace")


class Site:
    """Per-site fetcher that keeps the politeness delay."""

    def __init__(self, base):
        self.base = base
        self.host = urllib.parse.urlparse(base).netloc
        self.delay = MIN_DELAY_S
        self.last = 0.0
        self.requests = 0

    def get(self, url):
        wait = self.last + self.delay - time.time()
        if wait > 0:
            time.sleep(wait)
        self.last = time.time()
        self.requests += 1
        return fetch(url)

    def same_host(self, url):
        h = urllib.parse.urlparse(url).netloc
        return h == self.host or h.removeprefix("www.") == self.host.removeprefix("www.")


def robots_setup(site):
    rp = urllib.robotparser.RobotFileParser()
    try:
        txt = site.get(urllib.parse.urljoin(site.base, "/robots.txt"))[1]
    except Exception:
        return
    rp.parse(txt.splitlines())
    cd = rp.crawl_delay("SpitiRadar") or rp.crawl_delay("*")
    if cd:
        site.delay = max(MIN_DELAY_S, float(cd))
    return txt


def links(base, page):
    for href in re.findall(r"href=[\"']([^\"'<> ]+)[\"']", page):
        u = urllib.parse.urljoin(base, html.unescape(href)).split("#")[0]
        if u.startswith("http"):
            yield u


DETAIL_QUERY = re.compile(r"(?:^|&)(?:dios_code|code|id|pid|property_id|propertyid|listing_id|aid|ref|kodikos)=\d{3,}", re.I)
DETAIL_PAGE = re.compile(r"detail|listing|property|estate|akinit|aggeli|ad\.php|view", re.I)


def looks_like_detail(url):
    p = urllib.parse.urlparse(url)
    if SKIP.search(url) or len(p.path) < 2 or re.search(r"blog|news|article|service", p.path, re.I):
        return False
    # e.g. estate_details_listing.php?dios_code=218938
    if p.query and DETAIL_QUERY.search(p.query) and DETAIL_PAGE.search(p.path):
        return True
    return bool(DETAIL_ID.search(p.path)) and (bool(LISTING_HINT.search(p.path)) or p.path.count("/") <= 2)


def discover(site, home, per_site):
    found = []

    def add(u):
        u = u.rstrip("/")
        if u not in found and site.same_host(u) and looks_like_detail(u):
            found.append(u)

    # 1. sitemap
    for sm in ("/sitemap.xml", "/sitemap_index.xml", "/property-sitemap.xml"):
        try:
            _, xml = site.get(urllib.parse.urljoin(site.base, sm))
        except Exception:
            continue
        locs = re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", xml)
        subs = [l for l in locs if l.endswith(".xml")]
        for u in locs:
            add(html.unescape(u))
        for sub in [s for s in subs if re.search(r"propert|listing|akin|estate|aggel", s, re.I)][:3]:
            try:
                for u in re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", site.get(sub)[1]):
                    add(html.unescape(u))
            except Exception:
                pass
        if len(found) >= per_site:
            return found
    # 2. listing sections from the home page, then their pagination
    for u in links(site.base, home):
        add(u)
    sections = []
    for m in re.finditer(r"<a[^>]+href=[\"']([^\"']+)[\"'][^>]*>(.{0,120}?)</a>", home, re.S | re.I):
        text = re.sub(r"<[^>]+>", " ", m.group(2))
        u = urllib.parse.urljoin(site.base, html.unescape(m.group(1)))
        if SECTION_TEXT.search(text) and site.same_host(u) and u not in sections:
            sections.append(u)
    for u in links(site.base, home):
        if site.same_host(u) and u not in sections and not looks_like_detail(u) and \
                re.search(r"search|results?|listings?|anazitisi|akinita|properties|pwlhsh|poliseis|enoikiaseis", u, re.I):
            sections.append(u)
    queue, seen = sections[:6], set()
    while queue and len(seen) < MAX_PAGES_DISCOVERY and len(found) < per_site:
        u = queue.pop(0)
        if u in seen:
            continue
        seen.add(u)
        try:
            _, page = site.get(u)
        except Exception:
            continue
        for l in links(u, page):
            add(l)
            if site.same_host(l) and re.search(r"[?&](page|p|pg|offset)=\d+|/page/\d+", l) and l not in seen:
                queue.append(l)
    return found


def num(s):
    s = s.replace("\xa0", "").replace(" ", "")
    if re.fullmatch(r"\d{1,3}(\.\d{3})+(,\d+)?", s):
        s = s.replace(".", "").replace(",", ".")
    elif re.fullmatch(r"\d{1,3}(,\d{3})+(\.\d+)?", s):
        s = s.replace(",", "")
    else:
        s = s.replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def jsonld_items(page):
    for block in re.findall(r"<script[^>]+application/ld\+json[^>]*>(.*?)</script>", page, re.S | re.I):
        try:
            data = json.loads(html.unescape(block).strip())
        except ValueError:
            continue
        stack = [data]
        while stack:
            x = stack.pop()
            if isinstance(x, list):
                stack += x
            elif isinstance(x, dict):
                yield x
                stack += [v for v in x.values() if isinstance(v, (dict, list))]


def meta(page, prop):
    m = re.search(r"<meta[^>]+(?:property|name)=[\"']%s[\"'][^>]+content=[\"']([^\"']*)" % re.escape(prop), page, re.I) \
        or re.search(r"<meta[^>]+content=[\"']([^\"']*)[\"'][^>]+(?:property|name)=[\"']%s[\"']" % re.escape(prop), page, re.I)
    return html.unescape(m.group(1)).strip() if m else ""


def extract(url, page):
    title = meta(page, "og:title") or html.unescape((re.search(r"<title[^>]*>([^<]*)", page, re.I) or [None, ""])[1]).strip()
    text = html.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", re.sub(r"<script.*?</script>|<style.*?</style>", " ", page, flags=re.S | re.I))))
    rec = {"url": url, "title": title[:200], "price_eur": "", "area_m2": "", "bedrooms": "", "floor": "",
           "year_built": "", "type": "", "transaction": "", "location": "", "lat": "", "lon": "",
           "image": meta(page, "og:image")}

    for it in jsonld_items(page):
        offers = it.get("offers")
        if isinstance(offers, list) and offers:
            offers = offers[0]
        if isinstance(offers, dict) and offers.get("price") and not rec["price_eur"]:
            rec["price_eur"] = num(str(offers["price"])) or ""
        fs = it.get("floorSize")
        if isinstance(fs, dict) and fs.get("value") and not rec["area_m2"]:
            rec["area_m2"] = num(str(fs["value"])) or ""
        for k in ("numberOfBedrooms", "numberOfRooms"):
            if it.get(k) and not rec["bedrooms"]:
                v = it[k]["value"] if isinstance(it[k], dict) else it[k]
                rec["bedrooms"] = num(str(v)) or ""
        geo = it.get("geo")
        if isinstance(geo, dict) and geo.get("latitude") and not rec["lat"]:
            rec["lat"], rec["lon"] = geo.get("latitude"), geo.get("longitude")
        addr = it.get("address")
        if isinstance(addr, dict) and not rec["location"]:
            rec["location"] = ", ".join(str(addr[k]) for k in ("addressLocality", "addressRegion") if addr.get(k))
    rec["lat"] = rec["lat"] or meta(page, "place:location:latitude")
    rec["lon"] = rec["lon"] or meta(page, "place:location:longitude")

    head = title + " " + text[:6000]
    if not rec["price_eur"]:
        # "150.000 €" / "€ 150.000" / "€700"; digits separated by spaces are never joined
        # (titles like "2577591 – ... €700" would otherwise become 700700)
        m = re.search(r"(?:€|EUR)\s?(\d{1,3}(?:[.,]\d{3})+|\d+)(?![\d.,])|(\d{1,3}(?:[.,]\d{3})+|\d+)\s?(?:€|EUR|ευρώ)", head, re.I)
        if m:
            v = num(m.group(1) or m.group(2))
            rec["price_eur"] = v if v and v >= 50 else ""
    if not rec["area_m2"]:
        m = re.search(r"(\d{1,5}(?:[.,]\d{1,2})?)\s*(?:τ\.?\s?μ\.?|m²|m2|sq\.?\s?m)", head, re.I)
        if m:
            rec["area_m2"] = num(m.group(1)) or ""
    if not rec["bedrooms"]:
        m = re.search(r"(?:υπνοδωμάτι\w*|bedrooms?)\s*:?\s*(\d{1,2})|(\d{1,2})\s*(?:υ/δ|υπνοδωμάτι|bedrooms?)", head, re.I)
        if m:
            rec["bedrooms"] = m.group(1) or m.group(2)
    m = re.search(r"(?:όροφος|floor)\s*:?\s*(-?\d{1,2}|ισόγειο|υπόγειο|ημιυπόγειο|ground)|(\d{1,2})(?:ος|ο)\s*όροφ", head, re.I)
    if m:
        rec["floor"] = (m.group(1) or m.group(2) or "").lower()
    m = re.search(r"(?:έτος κατασκευής|κατασκευή|year built|built)\s*:?\s*((?:19|20)\d{2})", head, re.I)
    if m:
        rec["year_built"] = m.group(1)
    for t, pat in TYPES:
        if re.search(pat, title, re.I) or (not rec["type"] and re.search(pat, url, re.I)):
            rec["type"] = t
            break
    tr = (title + " " + url).lower()
    if re.search(r"ενοικ|μίσθ|enoik|for[-_ ]rent|to[-_ ]rent|\brent\b", tr):
        rec["transaction"] = "rent"
    elif re.search(r"πώλη|πωλ|pwlis|polisi|poleitai|for[-_ ]sale|\bsale\b", tr):
        rec["transaction"] = "sale"
    # Spitogatos-style location line used by many agency CRMs:
    # "Δήμος Θεσσαλονίκης , Χαριλάου" / "Θεσσαλονίκη Περιφ/κοί δήμοι, Καλαμαριά, Κέντρο"
    cells = html.unescape(re.sub(r"<[^>]+>", " | ", re.sub(r"<script.*?</script>|<style.*?</style>", " ", page, flags=re.S | re.I)))
    cells = re.sub(r"\s+", " ", cells)
    m = re.search(r"((?:Δήμος Θεσσαλονίκης|Θεσσαλονίκη(?:\s*-\s*Δήμος|\s*-?\s*Περιφ/κοί δήμοι|\s*-\s*Υπόλ\. Νομού)?)"
                  r"\s*,\s*(?!Ελλάδα|Greece)[^|€\d]{3,60})", cells)
    if m:
        rec["location"] = m.group(1).strip(" ,")
    m = re.search(r"\|\s*(ΠΡΟΣ ΠΩΛΗΣΗ|ΠΡΟΣ ΕΝΟΙΚΙΑΣΗ|ΠΩΛΕΙΤΑΙ|ΕΝΟΙΚΙΑΖΕΤΑΙ|Προς πώληση|Προς ενοικίαση|For sale|For rent)\s*\|", cells, re.I)
    if m:
        rec["transaction"] = "rent" if re.search(r"ενοικ|rent", m.group(1), re.I) else "sale"
    # district from the property facts ("Περιοχή: Καλαμαριά", "Area: Toumpa", "Τοποθεσία ...")
    m = re.search(r"(?:Περιοχή|Τοποθεσία|Location|Area|Region)\s*:\s*([A-Za-zΑ-Ωα-ωάέήίόύώϊϋΐΰΆΈΉΊΌΎΏ][^:|<>\n]{2,60}?)"
                  r"(?=\s{2,}|\s*(?:Τιμή|Εμβαδό|Εμβαδόν|Price|Size|Όροφος|Floor|Κωδικός|Code|Τύπος|Type)\b|$)", text)
    if m and not re.search(r"^(του|της|των|of|the)\b", m.group(1).strip(), re.I):
        rec["location"] = (rec["location"] + " | " if rec["location"] else "") + m.group(1).strip()[:60]
    if not rec["location"]:
        m = re.search(r"(Θεσσαλονίκη[^,|<]{0,40}|Καλαμαριά|Πυλαία|Πανόραμα|Θέρμη|Περαία|Εύοσμος|Νεάπολη|Σταυρούπολη|"
                      r"Αμπελόκηποι|Συκιές|Τούμπα|Χαριλάου|Πολίχνη|Ωραιόκαστρο|Επανομή|Τριανδρία|Κορδελιό|Μενεμένη)", title + " " + text[:3000])
        rec["location"] = m.group(1).strip() if m else ""
    return rec


def collect_site(row, per_site):
    base = row["final_url"] or row["website"]
    site = Site(base)
    report = {"domain": row["domain"], "listing_urls": 0, "parsed": 0, "with_price": 0, "with_area": 0, "error": ""}
    out = []
    try:
        txt = robots_setup(site)
        if txt and re.search(r"user-agent:\s*spitiradar", txt, re.I):
            rp = urllib.robotparser.RobotFileParser()
            rp.parse(txt.splitlines())
            if not rp.can_fetch("SpitiRadar", base):
                report["error"] = "robots: SpitiRadar disallowed"
                return out, report
        final, home = site.get(base)
        site.base = final
        urls = discover(site, home, per_site)
        report["listing_urls"] = len(urls)
        for u in urls[:per_site]:
            try:
                fu, page = site.get(u)
            except Exception:
                continue
            rec = extract(fu, page)
            if not (rec["price_eur"] or rec["area_m2"]):
                continue
            rec.update(source_domain=row["domain"], agency=row["name"],
                       scraped_at=datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"))
            out.append(rec)
    except Exception as e:
        report["error"] = type(e).__name__
    report["parsed"] = len(out)
    report["with_price"] = sum(1 for r in out if r["price_eur"])
    report["with_area"] = sum(1 for r in out if r["area_m2"])
    return out, report


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--per-site", type=int, default=30)
    ap.add_argument("--sites", type=int, default=0, help="limit number of sites (0 = all)")
    ap.add_argument("--workers", type=int, default=20)
    ap.add_argument("--domains", help="file with domains to (re)collect; results replace those domains in the outputs")
    a = ap.parse_args()
    only = {l.strip() for l in open(a.domains)} if a.domains else None
    rows, seen = [], set()
    for r in csv.DictReader(open(REGISTRY, encoding="utf-8")):
        if r["site_status"] == "ok" and r["has_listings"] == "yes" and r["robots_ok"] != "explicit_no" \
                and r["domain"] not in seen and (only is None or r["domain"] in only):
            seen.add(r["domain"])
            rows.append(r)
    if a.sites:
        rows = rows[:a.sites]
    print(f"{len(rows)} sites", file=sys.stderr)
    listings, reports, lock, done = [], [], threading.Lock(), [0]

    def work(row):
        out, rep = collect_site(row, a.per_site)
        with lock:
            listings.extend(out)
            reports.append(rep)
            done[0] += 1
            if done[0] % 10 == 0:
                print(f"{done[0]}/{len(rows)} sites, {len(listings)} listings", file=sys.stderr)

    with ThreadPoolExecutor(a.workers) as ex:
        list(ex.map(work, rows))

    fields = ["source_domain", "agency", "url", "title", "transaction", "type", "price_eur", "area_m2",
              "bedrooms", "floor", "year_built", "location", "lat", "lon", "image", "scraped_at"]
    import os
    os.makedirs("data/listings", exist_ok=True)
    if only is not None and os.path.exists(OUT):
        listings = [r for r in csv.DictReader(open(OUT, encoding="utf-8")) if r["source_domain"] not in only] + listings
        reports = [r for r in csv.DictReader(open(REPORT, encoding="utf-8")) if r["domain"] not in only] + reports
        for r in reports:
            r["parsed"] = int(r["parsed"])
    with open(OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(listings)
    with open(REPORT, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(reports[0].keys()))
        w.writeheader()
        w.writerows(sorted(reports, key=lambda r: -r["parsed"]))
    print(f"done: {len(listings)} listings from {sum(1 for r in reports if r['parsed'])} of {len(rows)} sites", file=sys.stderr)


if __name__ == "__main__":
    main()
