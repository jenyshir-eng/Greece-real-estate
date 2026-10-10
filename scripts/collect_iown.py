"""Collect property listings from iown.gr (servicer / REO properties).

iown.gr (properties.iown.gr) lists bank-owned and fund-owned properties
managed by iOWN Real Estate. The site uses a Vue SPA behind Cloudflare,
so curl gets empty data; Playwright (headless Chromium) is required.

Usage:
  python3 scripts/collect_iown.py [--max-pages 10] [--detail-pages 40]

Output: data/listings/listings_iown.csv  (same columns as listings_thessaloniki.csv)

The listing pages give: price, location, type, area, bedrooms, bathrooms, code/URL.
Detail pages add: floor, year_built, energy_class. Up to --detail-pages detail pages
are fetched per run (new listings first, then oldest-checked).
"""
import argparse
import asyncio
import csv
import datetime
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import city  # noqa: E402

BASE = "https://properties.iown.gr"
LANG = "en"
OUT = "data/listings/listings_iown.csv"
DELAY_S = 3.0
FIELDS = ["source_domain", "agency", "url", "title", "transaction", "type", "price_eur", "area_m2",
          "bedrooms", "floor", "year_built", "location", "lat", "lon", "image",
          "date_published", "date_updated", "date_sitemap", "date_source", "scraped_at",
          "checked_at"]

TYPES_MAP = {
    "apartment": "apartment", "studio": "studio", "maisonette": "maisonette",
    "detached house": "house", "villa": "house", "residential complex": "house",
    "residential building": "building", "loft": "apartment",
    "office": "office", "commercial office building": "office",
    "shop": "store", "store": "store",
    "warehouse": "warehouse", "industrial space": "warehouse",
    "land plot": "land", "plot": "land",
    "building": "building", "hotel": "hotel",
}

# map API gives coordinates for all properties
MAP_URL = f"{BASE}/{LANG}/map-results"


def parse_price(text):
    """'735,000' -> 735000, '1' or '' -> ''"""
    s = re.sub(r"[^\d]", "", (text or "").strip())
    if not s:
        return ""
    n = int(s)
    return str(n) if n > 1 else ""


def parse_area(info_text):
    """'Apartment 85 m2 for sale' -> ('apartment', '85', 'sale')"""
    m = re.match(r"(.+?)\s+([\d.,]+)\s*m", info_text or "", re.I)
    prop_type = m.group(1).strip().lower() if m else ""
    area = m.group(2).replace(",", ".") if m else ""
    tx = "rent" if "rent" in (info_text or "").lower() else ("sale" if "sale" in (info_text or "").lower() else "")
    return TYPES_MAP.get(prop_type, prop_type), area, tx


async def collect(max_pages=10, detail_pages=40):
    from playwright.async_api import async_playwright

    now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M")
    today = now[:10]

    # load existing data for incremental updates
    existing = {}
    if os.path.exists(OUT):
        for r in csv.DictReader(open(OUT, encoding="utf-8")):
            existing[r["url"]] = r

    async with async_playwright() as p:
        launch_args = {"headless": True, "args": ["--ignore-certificate-errors", "--no-sandbox"]}
        chromium_path = os.environ.get("PLAYWRIGHT_CHROMIUM_PATH")
        if not chromium_path:
            for candidate in ["/opt/pw-browsers/chromium-1194/chrome-linux/chrome",
                              "/opt/pw-browsers/chromium/chrome-linux/chrome"]:
                if os.path.exists(candidate):
                    chromium_path = candidate
                    break
        if chromium_path:
            launch_args["executable_path"] = chromium_path
        browser = await p.chromium.launch(**launch_args)
        page = await browser.new_page()

        # 1. Load page and capture map API response
        coords = {}
        map_prices = {}
        map_future = asyncio.get_event_loop().create_future()

        async def on_response(response):
            if "map-results" in response.url and response.status == 200:
                try:
                    data = await response.json()
                    if not map_future.done():
                        map_future.set_result(data)
                except Exception:
                    pass

        page.on("response", on_response)

        try:
            resp = await page.goto(f"{BASE}/{LANG}/properties", timeout=60000)
            print(f"  page status: {resp.status if resp else 'no response'}")
            # dismiss cookie banner if present
            try:
                btn = await page.wait_for_selector("text=Συμφωνώ", timeout=5000)
                if btn:
                    await btn.click()
                    await asyncio.sleep(1)
            except Exception:
                pass
            # wait for listing items to appear (data fills in asynchronously)
            for attempt in range(6):
                await asyncio.sleep(3)
                items = await page.query_selector_all(".listing-item")
                if items:
                    print(f"  {len(items)} listing items found after {(attempt+1)*3}s")
                    break
            else:
                title = await page.title()
                body_len = await page.evaluate("() => document.body ? document.body.innerHTML.length : 0")
                raise RuntimeError(f"no listing items after 18s (title={title}, body={body_len} chars)")

            # wait for map API response
            try:
                map_data = await asyncio.wait_for(map_future, timeout=10)
                for item in map_data:
                    pid = str(item["id"])
                    coords[pid] = (item.get("latitude", ""), item.get("longitude", ""))
                    map_prices[pid] = parse_price(item.get("price", ""))
                print(f"  map API: {len(coords)} properties with coordinates")
            except asyncio.TimeoutError:
                print("WARNING: map API response not captured", file=sys.stderr)
        except Exception as e:
            print(f"ERROR: page load failed: {e}", file=sys.stderr)
            await browser.close()
            return []

        # 2. Collect listing cards from all pages
        cards = []
        for pg in range(1, max_pages + 1):
            url = f"{BASE}/{LANG}/properties" + (f"?page={pg}" if pg > 1 else "")
            if pg > 1:
                await asyncio.sleep(DELAY_S)
                await page.goto(url, timeout=60000)
                try:
                    await page.wait_for_selector(".listing-item", timeout=20000)
                    await asyncio.sleep(3)
                except Exception:
                    break  # no more pages

            items = await page.eval_on_selector_all(".listing-item", """
                els => els.map(el => {
                    let link = el.querySelector('a[href*=properties]');
                    let price = el.querySelector('[class*=price]');
                    let title = el.querySelector('.title-sin_item');
                    let spans = title ? Array.from(title.querySelectorAll('span')) : [];
                    let info = el.querySelector('.pb-10.color1');
                    let code = el.querySelector('.codeDiv span');
                    let beds = el.querySelector('.fal.fa-bed-front');
                    let baths = el.querySelector('.fal.fa-bath');
                    let img = el.querySelector('.carousel-item.active img, .carousel-item img');
                    return {
                        href: link ? link.getAttribute('href') : null,
                        price: price ? price.textContent.trim() : '',
                        location: spans.map(s => s.textContent.trim().replace(/,\\s*$/, '')).filter(Boolean),
                        info: info ? info.textContent.replace(/\\s+/g, ' ').trim() : '',
                        code: code ? code.textContent.replace(/\\D/g, '') : '',
                        beds: beds ? beds.parentElement.textContent.trim().replace(/\\D/g, '') : '',
                        baths: baths ? baths.parentElement.textContent.trim().replace(/\\D/g, '') : '',
                        img: img ? img.getAttribute('src') : '',
                    }
                })
            """)

            if not items:
                break

            for item in items:
                if not item.get("href"):
                    continue
                pid = re.search(r"(\d+)", item["href"])
                if not pid:
                    continue
                pid = pid.group(1)
                prop_type, area, tx = parse_area(item["info"])
                price = parse_price(item["price"])
                if not price:
                    price = map_prices.get(pid, "")
                loc_parts = item["location"]
                location = ", ".join(loc_parts) if loc_parts else ""
                lat, lon = coords.get(pid, ("", ""))

                full_url = f"{BASE}/{LANG}/properties/{pid}"
                title_str = f"{prop_type.title()} {area} m² {location}".strip() if prop_type else location

                cards.append({
                    "source_domain": "iown.gr",
                    "agency": "iOWN",
                    "url": full_url,
                    "title": title_str,
                    "transaction": tx,
                    "type": prop_type,
                    "price_eur": price,
                    "area_m2": area,
                    "bedrooms": item["beds"],
                    "floor": "",
                    "year_built": "",
                    "location": location,
                    "lat": lat,
                    "lon": lon,
                    "image": item["img"],
                    "date_published": "",
                    "date_updated": "",
                    "date_sitemap": "",
                    "date_source": "",
                    "scraped_at": now,
                    "checked_at": today,
                    "_pid": pid,
                })

            print(f"  page {pg}: {len(items)} cards (total {len(cards)})")

            if len(items) < 18:
                break  # last page

        # 3. Merge with existing data (keep detail-enriched fields)
        seen_urls = {c["url"] for c in cards}
        merged = {}
        for c in cards:
            url = c["url"]
            old = existing.get(url, {})
            if old:
                # keep enriched fields from previous detail-page fetches
                for k in ("floor", "year_built"):
                    if old.get(k) and not c.get(k):
                        c[k] = old[k]
                if old.get("date_source"):
                    c["date_source"] = old["date_source"]
                else:
                    c["date_source"] = today
            else:
                c["date_source"] = today
            merged[url] = c

        # 4. Fetch detail pages for enrichment (floor, year_built)
        needs_detail = [c for c in merged.values()
                        if not c.get("floor") or not c.get("year_built")]
        # prioritize new listings, then oldest-checked
        needs_detail.sort(key=lambda c: (bool(existing.get(c["url"])),
                                          existing.get(c["url"], {}).get("checked_at", "")))
        fetched = 0
        for c in needs_detail[:detail_pages]:
            await asyncio.sleep(DELAY_S)
            try:
                await page.goto(c["url"], timeout=30000)
                await page.wait_for_selector(".details-list li", timeout=10000)

                details = await page.eval_on_selector_all(".details-list li", """
                    els => els.map(el => el.textContent.replace(/\\s+/g, ' ').trim())
                """)

                for d in details:
                    dl = d.lower()
                    if dl.startswith("floor"):
                        val = d.split(maxsplit=1)[1] if len(d.split(maxsplit=1)) > 1 else ""
                        c["floor"] = val.strip()
                    elif "year built" in dl:
                        m = re.search(r"\d{4}", d)
                        if m:
                            c["year_built"] = m.group()
                    elif dl.startswith("bedrooms"):
                        val = re.search(r"\d+", d)
                        if val and not c["bedrooms"]:
                            c["bedrooms"] = val.group()

                fetched += 1
            except Exception as e:
                print(f"  detail {c['_pid']}: {e}", file=sys.stderr)

        print(f"  enriched {fetched} detail pages")

        await browser.close()

    # 5. Keep all properties (region filtering is done by normalize_listings.py)
    results = []
    for c in merged.values():
        del c["_pid"]
        results.append(c)

    # 6. Write output
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(results)

    print(f"iown.gr: {len(cards)} total, {len(results)} in region -> {OUT}")
    return results


def main():
    try:
        import playwright  # noqa: F401
    except ImportError:
        print("WARNING: playwright not installed, skipping iown.gr collection", file=sys.stderr)
        return
    parser = argparse.ArgumentParser(description="Collect iown.gr listings")
    parser.add_argument("--max-pages", type=int, default=10)
    parser.add_argument("--detail-pages", type=int, default=40)
    args = parser.parse_args()
    asyncio.run(collect(max_pages=args.max_pages, detail_pages=args.detail_pages))


if __name__ == "__main__":
    main()
