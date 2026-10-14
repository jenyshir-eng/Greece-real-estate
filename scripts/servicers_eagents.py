"""Cepal (reinvest.gr) and REauction (reauction.gr): two sites of the e-agents platform (used by scripts/collect_servicers.py).

reinvest.gr sells the bank-owned (REO) properties Cepal manages; reauction.gr, linked from it, lists
e-auctions of properties across Greece (the official eauction.gr closes itself to crawlers in robots.txt).
Both sites serve the same two endpoints, filtered by a box (robots.txt allows everything):
  <base>/map-results?aim=N&southWestLat=..&...  JSON [{id, latitude, longitude, price}, ...]
  <base>/properties-list?aim=N&<box>&pageSize=50&page=P  HTML cards: place, type, size, price,
      bedrooms (reinvest), auction date, entry deadline, round and ownership share (reauction)
Listing pages: <base>/properties/<id> (reinvest), <base>/auctions/<id> (reauction).
"""
import html
import re

PAGE_SIZE = 50
MAX_PAGES = 60
# source_domain, name shown on the page, base URL, aim (1 = sale, 3 = auction), listing path, segment
SITES = [
    ("reinvest.gr", "Cepal (reinvest.gr)", "https://www.reinvest.gr/el", 1, "properties", "bank"),
    ("reauction.gr", "REauction", "https://www.reauction.gr/el", 3, "auctions", "auction"),
]
# Greek type on the card -> Spiti Radar type (normalize_listings.py reads the title as well)
TYPES = [("γκαρσονιέρα", "studio"), ("μεζονέτα", "maisonette"), ("διαμέρισμα", "apartment"),
         ("μονοκατοικία", "house"), ("βίλα", "house"), ("οικόπεδο", "land"), ("αγροτεμάχιο", "land"),
         ("κατάστημα", "store"), ("γραφείο", "office"), ("αποθήκη", "warehouse"), ("βιομηχαν", "warehouse"),
         ("βιοτεχν", "warehouse"), ("κτίριο", "building"), ("πολυκατοικία", "building"),
         ("θέση στάθμευσης", "parking"), ("parking", "parking"), ("ξενοδοχ", "hotel")]


def box_query(aim, box, page=None):
    la0, la1, lo0, lo1 = box
    q = f"aim={aim}&southWestLat={la0}&southWestLng={lo0}&northEastLat={la1}&northEastLng={lo1}&zoom=10"
    return q + (f"&pageSize={PAGE_SIZE}&page={page}" if page else "")


def plain_text(fragment):
    t = html.unescape(re.sub(r"<[^>]+>", " ", fragment))
    return re.sub(r"\s+", " ", t).strip()


def number(s):
    """'77.000 €' -> 77000, '90,68' -> 90.68, '' -> ''."""
    m = re.search(r"\d[\d.]*(?:,\d+)?", s or "")
    if not m:
        return ""
    v = float(m.group(0).replace(".", "").replace(",", "."))
    return int(v) if v.is_integer() else v


def iso(d):
    """'22-04-2027' -> '2027-04-22'."""
    m = re.fullmatch(r"(\d{2})-(\d{2})-(\d{4})", (d or "").strip())
    return f"{m.group(3)}-{m.group(2)}-{m.group(1)}" if m else ""


def kind(text):
    low = text.lower()
    return next((t for word, t in TYPES if word in low), "")


def parse_cards(page):
    """List page HTML -> [{id, place, type_gr, area, price, bedrooms, image, auction_date, round, share}]."""
    out = []
    for chunk in page.split('class="listing-style1"')[1:]:
        m = re.search(r'data-property-id="(\d+)"', chunk)
        if not m:
            continue
        title = re.search(r'<h6 class="list-title[^"]*">(.*?)</h6>', chunk, re.S)
        title = title.group(1) if title else ""
        spans = [plain_text(s) for s in re.findall(r"<span>(.*?)</span>", title, re.S)]
        place = spans[0].strip(" ,") if spans else ""
        after = plain_text(re.sub(r"<span>.*?</span>", " ", title, flags=re.S))  # reauction: type in the h6
        typ = re.search(r'<p class="">\s*([^<]+)', chunk)  # reinvest: type in the paragraph below
        type_gr = (typ.group(1) if typ else after).strip(" |\n")
        area = re.search(r"([\d.,]+)\s*(?:<span>)?\s*m<sup>2", chunk)
        price = re.search(r'<div class="list-price">.*?([\d.]+)\s*€', chunk, re.S)
        bed = re.search(r'fa-bed-front[^>]*></i>\s*<span[^>]*>(\d+)', chunk)
        img = re.search(r'<img[^>]*src="([^"]+)"', chunk)
        date = re.search(r'title="Ημερομηνία Δημοπρασίας">.*?(\d{2}-\d{2}-\d{4})', chunk, re.S)
        rnd = re.search(r"(\d+)\s*ος\s*γύρος", chunk)
        share = re.search(r"\((\d+(?:[.,]\d+)?)%\)", title)
        out.append({"id": m.group(1), "place": place, "type_gr": type_gr,
                    "area": number(area.group(1)) if area else "", "price": number(price.group(1)) if price else "",
                    "bedrooms": bed.group(1) if bed else "", "image": img.group(1) if img else "",
                    "auction_date": iso(date.group(1)) if date else "", "round": rnd.group(1) if rnd else "",
                    "share": share.group(1).replace(",", ".") if share else ""})
    return out


def row_from(card, point, site, now, in_unit):
    """Card + map point -> a listings_servicers.csv row, or None outside the city / without a point."""
    domain, name, base, _aim, path, segment = site
    if not point:
        return None
    lat, lon = point
    if not in_unit(lat, lon):
        return None
    share = card["share"]
    partial = share and float(share) < 100
    title = ", ".join(x for x in (card["type_gr"], f"{card['area']} τ.μ." if card["area"] else "", card["place"]) if x)
    if partial:
        title += f" (μερίδιο {share}%)"  # only a share of the property is auctioned
    return {
        "source_domain": domain, "agency": name, "url": f"{base}/{path}/{card['id']}", "title": title,
        "transaction": "sale", "type": kind(card["type_gr"]), "price_eur": card["price"], "area_m2": card["area"],
        "bedrooms": card["bedrooms"], "floor": "", "year_built": "", "location": card["place"],
        "lat": lat, "lon": lon, "image": card["image"],
        "date_published": "", "date_updated": "", "date_sitemap": "", "date_source": "",
        "scraped_at": now, "segment": segment,
        "auction_date": card["auction_date"] if segment == "auction" else "",
        "auction_round": card["round"] if segment == "auction" else "",
        "checked_at": now[:10],
    }


def collect(site, box, now, fetch_text, fetch_json, in_unit):
    """All listings of one site in the box -> {url: row}; raises on a failed request."""
    _domain, _name, base, aim, _path, _segment = site
    points = {str(p["id"]): (float(p["latitude"]), float(p["longitude"]))
              for p in fetch_json(f"{base}/map-results?{box_query(aim, box)}")
              if p.get("latitude") and p.get("longitude")}
    rows = {}
    for page in range(1, MAX_PAGES + 1):
        cards = parse_cards(fetch_text(f"{base}/properties-list?{box_query(aim, box, page)}"))
        for c in cards:
            r = row_from(c, points.get(c["id"]), site, now, in_unit)
            if r:
                rows[r["url"]] = r
        if len(cards) < PAGE_SIZE:
            break
    return rows
