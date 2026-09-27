"""Check agency websites: reachable, robots.txt allows us, has listings, platform.

Adds columns to the agencies CSV:
site_status  ok / http_<code> / error / no_site
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
        out["site_status"] = f"http_{e.code}"
        return out
    except Exception:
        out["site_status"] = "error"
        return out
    out["site_status"], out["final_url"] = "ok", final

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
    return out


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
