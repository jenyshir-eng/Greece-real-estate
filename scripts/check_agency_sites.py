"""Check agency websites: reachable, robots.txt allows us, has listings, platform.

Adds columns to the agencies CSV:
site_status  ok / bot_check_<vendor> / http_<code> / error / no_site
robots_ok    yes / no (robots.txt disallows the site root for all bots)
has_listings yes / maybe / no (links to property pages or sale/rent keywords)
listing_links number of distinct links that look like property pages
platform     CMS/CRM fingerprint if recognised

Usage: python3 scripts/check_agency_sites.py IN.csv OUT.csv
"""
import csv
import re
import sys
import urllib.parse
import urllib.request
import urllib.robotparser
from concurrent.futures import ThreadPoolExecutor

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0 Safari/537.36 SpitiRadar/0.1"
ROBOTS_AGENT = "SpitiRadar"

LISTING_URL = re.compile(
    r"href=[\"']([^\"']*(?:/akinit|/aggeli|/property|/properties|/listing|/estate|/poliseis|/polisi|/pwlisi|/sale|/for-sale|/diamerism|/katoik|/realestate|/ακίνητ|/αγγελ)[^\"']*)[\"']",
    re.I)
KEYWORDS = re.compile(r"πώληση|πωλείται|ενοικίαση|τ\.μ\.|for sale|sq\.?m|€", re.I)
PLATFORMS = {
    "wordpress": r"wp-content|wordpress",
    "wix": r"wix\.com|wixstatic",
    "joomla": r"/media/jui/|joomla",
    "realestate_crm_gr": r"realestatecrm|rencrm|crm\.gr",
    "houzez": r"houzez",
    "wpresidence": r"wpresidence",
    "estatik": r"estatik",
    "real_homes": r"realhomes|inspiry",
}


CHALLENGES = {
    "bot_check_imperva": r"Pardon Our Interruption|_Incapsula_Resource",
    "bot_check_cloudflare": r"<title>Just a moment|cf-chl",
    "bot_check_other": r"Verifying your browser",
}


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "el,en"})
    with urllib.request.urlopen(req, timeout=40) as r:
        return r.geturl(), r.read(2_000_000).decode("utf-8", "replace")


def check(row):
    site = row.get("website", "").strip()
    out = {"site_status": "no_site", "final_url": "", "robots_ok": "", "has_listings": "",
           "listing_links": "", "platform": ""}
    if not site:
        return out
    if not site.startswith("http"):
        site = "https://" + site
    try:
        final, html = fetch(site)
    except urllib.error.HTTPError as e:
        body = e.read(20000).decode("utf-8", "replace")
        out["site_status"] = next((n for n, sig in CHALLENGES.items() if re.search(sig, body, re.I)), f"http_{e.code}")
        return out
    except Exception:
        out["site_status"] = "error"
        return out
    out["site_status"], out["final_url"] = "ok", final
    for name, sig in CHALLENGES.items():
        if re.search(sig, html[:20000], re.I):
            out["site_status"] = name
            return out

    rp = urllib.robotparser.RobotFileParser()
    try:
        rp.parse(fetch(urllib.parse.urljoin(final, "/robots.txt"))[1].splitlines())
        out["robots_ok"] = "yes" if rp.can_fetch(ROBOTS_AGENT, final) else "no"
    except Exception:
        out["robots_ok"] = "yes"  # no robots.txt means no restriction

    links = {l for l in LISTING_URL.findall(html) if not l.startswith(("mailto:", "tel:"))}
    out["listing_links"] = str(len(links))
    if len(links) >= 5:
        out["has_listings"] = "yes"
    elif links or len(KEYWORDS.findall(html)) >= 5:
        out["has_listings"] = "maybe"
    else:
        out["has_listings"] = "no"
    out["platform"] = ";".join(n for n, p in PLATFORMS.items() if re.search(p, html, re.I))
    if out["has_listings"] != "yes":
        deep = deep_listing_links(final, html)
        if deep >= 5:
            out["has_listings"], out["listing_links"] = "yes", str(deep)
    return out


SECTION = re.compile(
    r"<a[^>]+href=[\"']([^\"'#]+)[\"'][^>]*>([^<]{0,60}(?:ακίνητ|ακινητ|πωλήσ|πωλησ|αγγελ|properties|listings|for sale|αναζήτ|search)[^<]{0,40})</a>",
    re.I)
ITEM = re.compile(r"href=[\"']([^\"'#]*?(?:\d{3,}|/akinito|/property/|/listing/|/estate/)[^\"'#]*)[\"']", re.I)


def deep_listing_links(base, html):
    """Look one level deeper: listing section pages and sitemap.xml."""
    host = urllib.parse.urlparse(base).netloc
    best = 0
    candidates = []
    for href, _text in SECTION.findall(html):
        url = urllib.parse.urljoin(base, href)
        if urllib.parse.urlparse(url).netloc == host and url not in candidates:
            candidates.append(url)
    for url in candidates[:3]:
        try:
            page = fetch(url)[1]
        except Exception:
            continue
        links = {l for l in ITEM.findall(page)
                 if urllib.parse.urlparse(urllib.parse.urljoin(url, l)).netloc in ("", host)
                 and not re.search(r"\.(jpg|jpeg|png|webp|css|js|pdf)$|wp-content|tel:|mailto:", l, re.I)}
        best = max(best, len(links))
    try:
        sm = fetch(urllib.parse.urljoin(base, "/sitemap.xml"))[1]
        best = max(best, len(re.findall(r"<loc>[^<]*(?:akinit|property|properties|listing|aggeli|estate|ακίνητ)[^<]*</loc>", sm, re.I)))
    except Exception:
        pass
    return best


def main(inp, outp):
    rows = list(csv.DictReader(open(inp, encoding="utf-8")))
    with ThreadPoolExecutor(max_workers=6) as ex:
        results = list(ex.map(check, rows))
    fields = list(rows[0].keys()) + list(results[0].keys())
    with open(outp, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r, extra in zip(rows, results):
            w.writerow({**r, **extra})


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
