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
  python3 scripts/collect_listings.py --incremental [--max-new 60]
      daily mode: listing pages already collected are not fetched again unless the
      sitemap says they changed; only new ones are read (at most --max-new per site).
      Listings not seen for --forget-days are dropped.
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
# pages read in daily mode that turned out not to be listings: not read again
NOT_LISTINGS = "data/listings/not_listings.txt"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/128.0 Safari/537.36 SpitiRadar/0.1 (+https://spitiradar.gr/opt-out)")
MIN_DELAY_S = 3.0
TRANSLATED_PATH = re.compile(r"/(en|ru|de|bg|fr|it|zh|he|tr|sr|ro|uk|ar|nl|pl)(/|$)", re.I)
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
        self.lastmod = {}

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


def remember_lastmod(site, xml):
    for block in re.findall(r"<url>(.*?)</url>", xml, re.S):
        loc = re.search(r"<loc>\s*([^<\s]+)\s*</loc>", block)
        mod = re.search(r"<lastmod>\s*([^<\s]+)\s*</lastmod>", block)
        if loc and mod:
            d = parse_date(mod.group(1))
            if d:
                site.lastmod[html.unescape(loc.group(1)).rstrip("/")] = d


def parse_date(s):
    """ISO or dd/mm/yyyy -> 'YYYY-MM-DD'; rejects impossible and future dates."""
    s = (s or "").strip()
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", s)
    if m:
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
    else:
        m = re.match(r"(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{2,4})", s)
        if not m:
            return ""
        d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        y += 2000 if y < 100 else 0
    try:
        dt = datetime.date(y, mo, d)
    except ValueError:
        return ""
    if dt.year < 2010 or dt > datetime.date.today() + datetime.timedelta(days=1):
        return ""
    return dt.isoformat()


DATE_LABEL = re.compile(
    r"(Ημερομηνία\s+(?:καταχώρ\w*|δημοσίευσ\w*|ανάρτησ\w*|ενημέρωσ\w*)|Καταχωρήθηκε|Δημοσιεύτηκε|Δημοσιεύθηκε|"
    r"Τελευταία\s+(?:ενημέρωση|τροποποίηση|ανανέωση)|Ενημερώθηκε|Ανανεώθηκε|Date\s+(?:added|posted|published|listed)|"
    r"Listed|Published|Last\s+updated?|Updated)\s*:?\s*(\d{1,2}[/.\-]\d{1,2}[/.\-]\d{2,4}|\d{4}-\d{2}-\d{2})", re.I)


def extract_dates(page, text):
    """Returns (published, updated, source)."""
    pub, upd, src = "", "", []
    for it in jsonld_items(page):
        for k in ("datePosted", "datePublished", "dateCreated", "uploadDate"):
            if it.get(k) and not pub:
                pub = parse_date(str(it[k]))
        if it.get("dateModified") and not upd:
            upd = parse_date(str(it["dateModified"]))
    if pub or upd:
        src.append("jsonld")
    for prop, slot in (("article:published_time", "pub"), ("article:modified_time", "upd"), ("og:updated_time", "upd")):
        v = parse_date(meta(page, prop))
        if v:
            if slot == "pub" and not pub:
                pub = v
            elif slot == "upd" and not upd:
                upd = v
            src.append("meta")
    for label, value in DATE_LABEL.findall(text):
        v = parse_date(value)
        if not v:
            continue
        if re.search(r"ενημέρ|τροποπ|ανανέ|updated", label, re.I):
            upd = upd or v
        else:
            pub = pub or v
        src.append("text")
    return pub, upd, "+".join(dict.fromkeys(src))


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
        remember_lastmod(site, xml)
        for u in locs:
            add(html.unescape(u))
        for sub in [s for s in subs if re.search(r"propert|listing|akin|estate|aggel", s, re.I)][:3]:
            try:
                sub_xml = site.get(sub)[1]
                remember_lastmod(site, sub_xml)
                for u in re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", sub_xml):
                    add(html.unescape(u))
            except Exception:
                pass
        if len(found) >= per_site:
            break
    if found and site.lastmod:
        # newest first: with a per-site limit we keep the freshest listings
        found.sort(key=lambda u: site.lastmod.get(u, ""), reverse=True)
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

    rec["date_published"], rec["date_updated"], rec["date_source"] = extract_dates(page, text)
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


def collect_site(row, per_site, known=None, max_new=0, ignore=frozenset()):
    """known: {url: record} from earlier runs (incremental mode), else None.
    ignore: pages known not to be listings."""
    base = row["final_url"] or row["website"]
    site = Site(base)
    report = {"domain": row["domain"], "listing_urls": 0, "parsed": 0, "with_price": 0, "with_area": 0,
              "new": 0, "changed": 0, "error": ""}
    out = []
    now = datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
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
        # the same listing in English / Russian / ...: normalize drops it as a translated duplicate,
        # so do not spend the day's page budget on it when the site has Greek pages
        local = [u for u in urls if not TRANSLATED_PATH.search(urllib.parse.urlparse(u).path)]
        if len(local) >= 0.3 * len(urls):
            urls = local
        report["listing_urls"] = len(urls)
        fetched = 0
        for u in urls[:per_site]:
            key = u.rstrip("/")
            old = known.get(key) if known is not None else None
            mod = site.lastmod.get(key, "")
            if old is not None and not (mod and mod > (old.get("date_sitemap") or "")):
                # still on the site and unchanged: keep the record, mark it as seen today
                out.append(dict(old, scraped_at=now))
                continue
            if known is not None and (fetched >= max_new or key in ignore):
                continue
            fetched += 1
            try:
                fu, page = site.get(u)
            except Exception:
                if old is not None:
                    out.append(old)
                continue
            rec = extract(fu, page)
            if not (rec["price_eur"] or rec["area_m2"]):
                report.setdefault("_skipped", []).append(key)
                continue
            if known is not None and fu.rstrip("/") in known and fu.rstrip("/") != key:
                old = known[fu.rstrip("/")]  # a redirect to a listing we already have
            rec["found_url"] = key
            rec["date_sitemap"] = mod
            rec.update(source_domain=row["domain"], agency=row["name"], scraped_at=now)
            report["changed" if old is not None else "new"] += 1
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
    ap.add_argument("--incremental", action="store_true", help="daily mode: fetch only new or changed listing pages")
    ap.add_argument("--max-new", type=int, default=60, help="incremental: new listing pages to read per site")
    ap.add_argument("--forget-days", type=int, default=45, help="incremental: drop listings not seen for this long")
    a = ap.parse_args()
    import os
    known_by_site = {}
    if a.incremental:
        if a.per_site == 30:
            # look at the whole site (sitemaps are cheap); only unknown or changed pages are fetched,
            # at most --max-new a day, so big agencies (1000+ listings) fill in over a few days
            a.per_site = 5000
        for r in csv.DictReader(open(OUT, encoding="utf-8")):
            k = known_by_site.setdefault(r["source_domain"], {})
            k[r["url"].rstrip("/")] = r
            if r.get("found_url"):
                k[r["found_url"]] = r  # the link on the site redirects to r["url"]
    ignore = set(open(NOT_LISTINGS, encoding="utf-8").read().split()) if os.path.exists(NOT_LISTINGS) else set()
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
        known = known_by_site.get(row["domain"], {}) if a.incremental else None
        out, rep = collect_site(row, a.per_site, known, a.max_new, ignore)
        if a.incremental:
            skipped = rep.pop("_skipped", [])
            known = {id(r): r for r in known.values()}  # one entry per record (url and found_url point to it)
            known = {r["url"].rstrip("/"): r for r in known.values()}
            # site down or blocked today: keep what we had; otherwise keep listings not
            # rediscovered today (discovery is limited) until they are too old
            got = {r["url"].rstrip("/") for r in out} | {r.get("found_url", "") for r in out}
            cutoff = (datetime.datetime.utcnow() - datetime.timedelta(days=a.forget_days)).strftime("%Y-%m-%d")
            out += [r for u, r in known.items() if u not in got and (r.get("scraped_at") or "")[:10] >= cutoff]
        with lock:
            if a.incremental:
                ignore.update(skipped)
            listings.extend(out)
            reports.append(rep)
            done[0] += 1
            if done[0] % 10 == 0:
                print(f"{done[0]}/{len(rows)} sites, {len(listings)} listings", file=sys.stderr)

    with ThreadPoolExecutor(a.workers) as ex:
        list(ex.map(work, rows))

    fields = ["source_domain", "agency", "url", "title", "transaction", "type", "price_eur", "area_m2",
              "bedrooms", "floor", "year_built", "location", "lat", "lon", "image",
              "date_published", "date_updated", "date_sitemap", "date_source", "scraped_at", "found_url"]
    if a.incremental:
        with open(NOT_LISTINGS, "w", encoding="utf-8") as f:
            f.write("\n".join(sorted(ignore)) + "\n")
    os.makedirs("data/listings", exist_ok=True)
    if a.incremental and only is None:
        # sites not collected today (left the registry filter, or --sites limit) keep their listings
        done_sites = {r["domain"] for r in reports}
        listings = [r for d, recs in known_by_site.items() if d not in done_sites for r in recs.values()] + listings
        old_rep = [r for r in csv.DictReader(open(REPORT, encoding="utf-8")) if r["domain"] not in done_sites] \
            if os.path.exists(REPORT) else []
        for r in old_rep:
            r["parsed"] = int(r["parsed"])
        reports += old_rep
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
        w = csv.DictWriter(f, fieldnames=["domain", "listing_urls", "parsed", "with_price", "with_area",
                                          "new", "changed", "error"], restval="", extrasaction="ignore")
        w.writeheader()
        w.writerows(sorted(reports, key=lambda r: -r["parsed"]))
    print(f"done: {len(listings)} listings from {sum(1 for r in reports if r['parsed'])} of {len(rows)} sites"
          + (f"; today {sum(int(r.get('new') or 0) for r in reports)} new, "
             f"{sum(int(r.get('changed') or 0) for r in reports)} changed" if a.incremental else ""), file=sys.stderr)


if __name__ == "__main__":
    main()
