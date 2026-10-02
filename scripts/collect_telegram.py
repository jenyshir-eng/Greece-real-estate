"""Collect property listings from public Telegram channels.

Public channels have a public web view (https://t.me/s/<channel>) that anyone can read
without an account; groups (chats) do not, they need a logged-in account (not done here).

Only posts that look like a listing are kept: a price, an area and a sale/rent word,
and not marked as let/sold. Kept per post: price, m2, bedrooms, floor, sale/rent,
place name, map coordinates, first line as title, post date and the link to the post.
The post text itself is not stored.

Usage: python3 scripts/collect_telegram.py [--days 120]
Channels: data/sources/telegram_channels.csv (kind=channel)
Output:   data/listings/listings_telegram.csv (same columns as listings_thessaloniki.csv)
"""
import argparse
import csv
import datetime
import html
import os
import re
import sys
import time
import urllib.request

CHANNELS = "data/sources/telegram_channels.csv"
OUT = "data/listings/listings_telegram.csv"
UA = "Mozilla/5.0 (compatible; SpitiRadar/0.1; +https://spitiradar.gr/opt-out)"
DELAY_S = 3.0
FIELDS = ["source_domain", "agency", "url", "title", "transaction", "type", "price_eur", "area_m2",
          "bedrooms", "floor", "year_built", "location", "lat", "lon", "image",
          "date_published", "date_updated", "date_sitemap", "date_source", "scraped_at"]

# Russian / English place names -> the Greek or Latin form the normalizer knows
RU_PLACES = [
    (r"салоник|фессалоник|тессалоник", "Θεσσαλονίκη"), (r"каламари", "Καλαμαριά"), (r"пере[яеи]", "Περαία"),
    (r"эпиватес|епиватес", "Νέοι Επιβάτες"), (r"терми\b|терме", "Θέρμη"), (r"панорам[аеуы]\b", "Πανόραμα"),
    (r"пиле[яи]|пилеа|пилайа", "Πυλαία"), (r"тумб", "Τούμπα"), (r"харила", "Χαριλάου"), (r"неапол", "Νεάπολη"),
    (r"сики[ея]", "Συκιές"), (r"ставропол|ставрупол", "Σταυρούπολη"), (r"эвосмос|эвозмос", "Εύοσμος"),
    (r"ор[еэ]окастр", "Ωραιόκαστρο"), (r"михани|миханион", "Μηχανιώνα"), (r"эпано", "Επανομή"),
    (r"вардар", "Βαρδάρης"), (r"лададик", "Λαδάδικα"), (r"ано поли", "Άνω Πόλη"), (r"аналипс|аналепс", "Ανάληψη"),
    (r"депо\b", "Ντεπώ"), (r"мартиу", "Μαρτίου"), (r"полихни", "Πολίχνη"), (r"амбелокип|ампелокип", "Αμπελόκηποι"),
    (r"халкидик|кассандр|ситони|полихроно|ханиоти|пефкохори", "Χαλκιδική"), (r"катерин", "Κατερίνη"),
    (r"пиери|олимпийск|лептокар|паралия катерин", "Πιερία"), (r"пире", "Πειραιάς"),
    (r"глифад", "Γλυφάδα"), (r"вулиагмен", "Βουλιαγμένη"), (r"\bвул[аеуы]\b", "Βούλα"), (r"кифиси", "Κηφισιά"),
    (r"маруси", "Μαρούσι"), (r"халандри", "Χαλάνδρι"), (r"калифе|каллифе", "Καλλιθέα"), (r"колонаки", "Κολωνάκι"),
    (r"фалиро", "Φάληρο"), (r"неа смирн|нея смирн", "Νέα Σμύρνη"), (r"пангкрати|панграти", "Παγκράτι"),
    (r"экзархи|эксархи", "Εξάρχεια"), (r"кукаки", "Κουκάκι"), (r"плака\b", "Πλάκα"), (r"варкиз", "Βάρκιζα"),
    (r"афин|аттик", "Αθήνα"),
    (r"кавал", "Καβάλα"), (r"крит|ираклион|ханья", "Κρήτη"), (r"лутраки", "Λουτράκι"), (r"миконос", "Μύκονος"),
    (r"кипр|лимассол|пафос", "Κύπρος"),
]
SALE = re.compile(r"прода[её]тся|продажа|продам|for sale|\bsale\b|πωλ[ηεί]|πώλ|купить|стоимость объекта", re.I)
RENT = re.compile(r"аренд|сда[её]тся|сдам|сдаю|for rent|\brent\b|ενοικ|в месяц|/мес|per month|monthly", re.I)
# digests, selections of several projects, news: not one listing
DIGEST = re.compile(r"подборк|дайджест|топ-?\s?\d|\bтоп\b|новост|проект[аов]{0,2}\b.*проект|asked questions|инвестиционн\w+ проект", re.I)
DONE = re.compile(r"сдан[аоы]?\b|продан[аоы]?\b|\bsold\b|\brented\b|πουλήθηκε|νοικιάστηκε", re.I)
PRICE = re.compile(r"(?:€|eur|евро)\s*(\d{1,3}(?:[’'., ]\d{3})+|\d+)(?![\d’'.,])|(?<![\d’'.,])(\d{1,3}(?:[’'., ]\d{3})+|\d+)\s*(?:€|eur\b|евро)", re.I)
AREA = re.compile(r"(\d{2,5}(?:[.,]\d+)?)\s*(?:м²|м2|кв\.?\s?м|m²|m2|sq\.?\s?m|sqm|τ\.?μ\.?)", re.I)
TYPES_RU = [("studio", r"студи"), ("maisonette", r"мезонет|таунхаус|дуплекс"), ("apartment", r"квартир|апартамент|пентхаус"),
            ("house", r"\bдом\b|дома\b|вилл|коттедж"), ("land", r"участ|земл"), ("store", r"магазин|коммерческ"),
            ("office", r"офис"), ("hotel", r"гостиниц|отел")]


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "ru,en;q=0.8"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", "replace")


def text_of(fragment):
    s = re.sub(r"<br\s*/?>", "\n", fragment)
    return html.unescape(re.sub(r"<[^>]+>", "", s)).strip()


def num(s):
    return float(re.sub(r"[’'., ]", "", s))


# the channel's own region (column "focus") decides where its places are: Ampelokipoi in an Athens channel is Athens
CHANNEL_REGION = [(r"^athens|athens:", "Αθήνα"), (r"^crete", "Κρήτη"), (r"^kefalonia", "Κεφαλονιά"),
                  (r"^halkidiki", "Χαλκιδική"), (r"^peloponnese", "Πελοπόννησος"), (r"^thessaloniki", "Θεσσαλονίκη")]


def parse_post(block, channel_title, channel_focus=""):
    link = re.search(r'data-post="([^"]+)"', block)
    when = re.search(r'<time datetime="([^"]+)"', block)
    body = re.search(r'<div class="tgme_widget_message_text[^>]*>(.*?)</div>', block, re.S)
    if not (link and when and body):
        return None
    raw = body.group(1)
    text = text_of(raw)
    low = text.lower()
    head = low[:300]
    if DONE.search(head):
        return None  # already let / sold
    prices = [num(m.group(1) or m.group(2)) for m in PRICE.finditer(text)]
    prices = [p for p in prices if p >= 100]
    if DIGEST.search(head) or len(set(prices)) > 3:
        return None  # several objects or a news post
    area = AREA.search(text)
    rent, sale = RENT.search(low), SALE.search(low)
    if not (prices and area and (rent or sale)):
        return None
    tx = "rent" if rent and (not sale or rent.start() < sale.start()) else "sale"
    price = prices[0]
    if tx == "rent" and price > 20000:
        tx = "sale"
    coords = re.search(r"[?&@/](?:q=|ll=)?(4\d\.\d{3,}),\s*(2\d\.\d{3,})", raw)
    places = [greek for pat, greek in RU_PLACES if re.search(pat, low)]
    home = next((g for pat, g in CHANNEL_REGION if re.search(pat, channel_focus.lower())), "")
    if home and home != "Θεσσαλονίκη":
        places = [home] + [p for p in places if p != home]  # a place name alone must not move it to Thessaloniki
    elif home and not places:
        places = [home]
    first_line = next((l.strip(" 🇬🇷‼️🔥🌊🏡📍") for l in text.splitlines() if len(l.strip()) > 8), "")[:120]
    ptype = next((t for t, pat in TYPES_RU if re.search(pat, low)), "")
    beds = re.search(r"(\d)\s*(?:спальн|bedroom|υπνοδωμ)|спальн\w*\s*[-–:]\s*(\d)", low)
    floor = re.search(r"(\d{1,2})\s*-?(?:й|ой|ий)?\s*(?:греческий\s*)?этаж|(\d{1,2})(?:st|nd|rd|th)\s*floor", low)
    ground = re.search(r"цокол|ground floor|ισόγει", low)
    return {
        "source_domain": "t.me", "agency": channel_title,
        "url": "https://t.me/" + link.group(1),
        # the first line (the post's own headline) plus the place, as a listing title
        "title": first_line + (" · " + ", ".join(dict.fromkeys(places)) if places else ""),
        "transaction": tx, "type": ptype, "price_eur": price,
        "area_m2": float(area.group(1).replace(",", ".")),
        "bedrooms": (beds.group(1) or beds.group(2)) if beds else "",
        "floor": "0" if ground else ((floor.group(1) or floor.group(2)) if floor else ""),
        "year_built": "", "location": ", ".join(dict.fromkeys(places)),
        "lat": coords.group(1) if coords else "", "lon": coords.group(2) if coords else "",
        "image": "", "date_published": when.group(1)[:10], "date_updated": "", "date_sitemap": "",
        "date_source": "telegram post",
        "scraped_at": datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=120, help="how far back to read each channel")
    a = ap.parse_args()
    cutoff = (datetime.date.today() - datetime.timedelta(days=a.days)).isoformat()
    kept = {}
    if os.path.exists(OUT):
        kept = {r["url"]: r for r in csv.DictReader(open(OUT, encoding="utf-8"))}
    channels = [r for r in csv.DictReader(open(CHANNELS, encoding="utf-8")) if r["kind"] == "channel"]
    new = 0
    for ch in channels:
        before, pages, got = "", 0, 0
        while pages < 15:
            url = f"https://t.me/s/{ch['handle']}" + (f"?before={before}" if before else "")
            try:
                page = fetch(url)
            except Exception as e:
                print(f"{ch['handle']}: {getattr(e, 'code', type(e).__name__)}", file=sys.stderr)
                break
            time.sleep(DELAY_S)
            pages += 1
            blocks = re.split(r'<div class="tgme_widget_message_wrap', page)[1:]
            if not blocks:
                break
            oldest = ""
            for b in blocks:
                when = re.search(r'<time datetime="([^"]+)"', b)
                if when and (not oldest or when.group(1) < oldest):
                    oldest = when.group(1)
                rec = parse_post(b, ch["title"], ch.get("focus", ""))
                if rec and rec["date_published"] >= cutoff:
                    new += rec["url"] not in kept
                    got += 1
                    kept[rec["url"]] = rec
            ids = [int(x) for x in re.findall(r'data-post="[^"/]+/(\d+)"', page)]
            if not ids or (oldest and oldest[:10] < cutoff):
                break
            before = str(min(ids))
        print(f"{ch['handle']}: {pages} pages, {got} listing posts", file=sys.stderr)
    # listings older than the window are dropped (they are old news on a channel)
    rows = [r for r in kept.values() if r["date_published"] >= cutoff]
    with open(OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore")
        w.writeheader()
        w.writerows(sorted(rows, key=lambda r: r["url"]))
    print(f"{len(rows)} listing posts ({new} new)", file=sys.stderr)


if __name__ == "__main__":
    main()
