"""Turn portal alert emails (Google Sheet published as CSV) into listings.

The alerts Gmail account runs integrations/gmail_alerts/Code.gs, which writes
one row per listing link found in alert emails from Spitogatos, Spiti24,
Tospitimou, Plot, Indomio and XE. This script reads that CSV and keeps only
normalized fields (price, m2, type words, area, sale/rent), the listing URL
and the date of the alert; the email text itself is not stored.

Usage: python3 scripts/ingest_portal_alerts.py [--url CSV_URL]
       (default: environment variable PORTAL_ALERTS_CSV_URL)
Output: data/listings/listings_alerts.csv (same columns as listings_thessaloniki.csv);
        earlier rows are kept, so listings stay after the sheet is cleaned.
"""
import argparse
import csv
import datetime
import html
import io
import os
import re
import sys
import urllib.request

OUT = "data/listings/listings_alerts.csv"
FIELDS = ["source_domain", "agency", "url", "title", "transaction", "type", "price_eur", "area_m2",
          "bedrooms", "floor", "year_built", "location", "lat", "lon", "image",
          "date_published", "date_updated", "date_sitemap", "date_source", "scraped_at"]
DOMAIN = {"Spitogatos": "spitogatos.gr", "Spiti24": "spiti24.gr", "Tospitimou": "tospitimou.gr",
          "Plot": "plot.gr", "Indomio": "indomio.gr", "XE": "xe.gr"}
# words that end the location part of a card and start the property type
TYPE_WORD = (r"Διαμέρισμα|Studio|Γκαρσονιέρα|Μεζονέτα|Μονοκατοικία|Μονοκατοικια|Κατοικία|Οροφοδιαμέρισμα|Loft|"
             r"Βίλα|Πολυκατοικία|Κτίριο|Γραφείο|Κατάστημα|Αποθήκη|Επαγγελματικός|Οικόπεδο|Αγροτεμάχιο|Γη|"
             r"Parking|Θέση στάθμευσης|Ξενοδοχείο")


PRICE = re.compile(r"€\s?(\d{1,3}(?:[.,]\d{3})+|\d+)(?![\d.,])|(?<![\d.,])(\d{1,3}(?:[.,]\d{3})+|\d+)\s?€")


def clean(ctx):
    s = html.unescape(ctx or "")
    s = re.sub(r"^[^<>]*?>", " ", s) if re.match(r"^[^<>]*?(;|\")[^<>]*>", s) else s  # cut-off tag at the start
    s = re.sub(r"<[^>]*>|<[^>]*$|[\w-]+:\s*[\w#%.\s-]+;|colspan=\"\d+\"", " ", s)
    return re.sub(r"[\s﻿]+", " ", s).strip()


def num(s):
    s = s.strip()
    if re.fullmatch(r"\d{1,3}([.,]\d{3})+", s):
        s = re.sub(r"[.,]", "", s)  # 72.000 / 72,000
    else:
        s = s.replace(",", ".")      # 37.0 / 37,5
    try:
        return float(s)
    except ValueError:
        return ""


def parse_row(r):
    url = re.sub(r"[?&]utm_[^#]*$", "", r["url"].strip())
    ctx = r["context"]
    MARK = r"(?:Νέα αγγελία|Νέες αγγελίες|Νέα τιμή|Μείωση τιμής|περίμενες!)\s*:?\s*"
    if "⟦LINK⟧" in ctx:
        # newer sheet rows: text before and after the link; the card is where the price is
        before, after = (clean(x) for x in ctx.split("⟦LINK⟧", 1))
        context_all = before + " " + after
        if PRICE.search(after[:300]):
            card = after
        else:
            card = re.split(MARK, before)[-1]  # card text right before the link
    else:
        # older rows: header + card from the start of the email fragment
        context_all = clean(ctx)
        m = re.search(MARK + r"(.*)", context_all)
        card = m.group(1) if m else context_all
    agency = re.search(r"Αγγελιοδότ\w*\s*:\s*([^\W\d_].*?)(?=\s+(Δες|Δείτε|Νέα|Νέες|Απενεργοποίηση)|$)", card)
    card = re.split(r"Αγγελιο|Δες την αγγελία|Δείτε την αγγελία|Δες όλες|Απενεργοποίηση", card)[0].strip()
    card = re.sub(r"\s+Α(γ(γ\w*)?)?$", "", card)  # "Αγγ…" cut off at the end of an old fragment
    text = context_all
    price = PRICE.search(card)
    area = re.search(r"(\d{1,6}(?:[.,]\d+)?)\s*(?:τ\.?μ\.?|m²|m2)(?!\s*\))", card)
    words = (card + " " + r["subject"] + " " + text).lower()
    tx = ("rent" if re.search(r"ενοικ|μίσθ", words) else "sale" if re.search(r"πώλη|πωλ", words) else "")
    loc = ""
    if "|" in card:
        # XE card: "Διαμέρισμα 37.0 τ.μ. 72.000 € | 1.946 € / τ.μ. Ισόγειο | 1 υ/δ | 1 μπ. | 1970 Συκιές"
        loc = re.sub(r"^\d{4}\s+", "", card.rsplit("|", 1)[-1].strip())
    elif price:
        after_price = card[price.end():]
        lm = re.match(r"\s*(.*?)\s*(?=%s)" % TYPE_WORD, after_price)
        loc = (lm.group(1) if lm else after_price[:80]).strip(" -·,")
    bedrooms = re.search(r"(\d+)\s*υ/δ", card)
    title = re.sub(r"^€\s?[\d.,]+\s*", "", card.split(" | ")[0] + (" · " + loc if "|" in card else ""))[:160]
    day = ""
    dm = re.match(r"(\d{1,2})/(\d{1,2})/(\d{4})", r["received"] or "")
    if dm:
        day = datetime.date(int(dm.group(3)), int(dm.group(1)), int(dm.group(2))).isoformat()
    return {
        "source_domain": DOMAIN.get(r["portal"], r["portal"].lower()),
        "agency": agency.group(1).strip()[:80] if agency else r["portal"],
        "url": url,
        "title": title,
        "transaction": tx,
        "type": "",
        "price_eur": num(price.group(1) or price.group(2)) if price else "",
        "area_m2": num(area.group(1)) if area else "",
        "bedrooms": bedrooms.group(1) if bedrooms else "", "floor": "", "year_built": "",
        "location": loc,
        "lat": "", "lon": "", "image": "",
        # the alert says the listing is new (or newly changed) on the day the email arrived
        "date_published": "", "date_updated": day, "date_sitemap": "",
        "date_source": "portal alert",
        "scraped_at": (day + "T00:00:00Z") if day else datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default=os.environ.get("PORTAL_ALERTS_CSV_URL", ""))
    a = ap.parse_args()
    if not a.url:
        sys.exit("set PORTAL_ALERTS_CSV_URL or pass --url")
    req = urllib.request.Request(a.url, headers={"User-Agent": "SpitiRadar/0.1"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        rows = list(csv.DictReader(io.StringIO(resp.read().decode("utf-8"))))
    kept = {}
    if os.path.exists(OUT):
        for r in csv.DictReader(open(OUT, encoding="utf-8")):
            kept[r["url"]] = r
    new = skipped = 0
    for r in rows:
        if not r.get("url"):
            skipped += 1  # confirmation / service emails without listing links
            continue
        item = parse_row(r)
        old = kept.get(item["url"])
        if old:
            # keep the first alert date as publication, the latest as update
            item["date_published"] = old["date_published"] or old["date_updated"]
            item["date_updated"] = max(old["date_updated"], item["date_updated"])
        else:
            new += 1
        kept[item["url"]] = item
    with open(OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore")
        w.writeheader()
        w.writerows(sorted(kept.values(), key=lambda x: (x["source_domain"], x["url"])))
    print(f"{len(rows)} alert rows, {skipped} without listing link, {new} new listings, {len(kept)} total", file=sys.stderr)


if __name__ == "__main__":
    main()
