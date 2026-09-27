"""Normalize collected listings: drop non-listing pages, detect sale/rent and
property type, map the location to a Thessaloniki area, remove duplicates.

Input:  data/listings/listings_thessaloniki.csv  (scripts/collect_listings.py)
Output: data/listings/listings_normalized.csv
        prints a quality summary

Usage: python3 scripts/normalize_listings.py
"""
import csv
import re
import unicodedata
from collections import Counter

IN = "data/listings/listings_thessaloniki.csv"
OUT = "data/listings/listings_normalized.csv"


def plain(s):
    """Lowercase, strip Greek accents (ΔΙΑΜΕΡΙΣΜΑ == διαμέρισμα), unify final sigma."""
    s = unicodedata.normalize("NFD", (s or "").lower())
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return s.replace("ς", "σ")


# Thessaloniki prefecture areas: (area name, patterns on accent-free lowercase text).
# Neighbourhoods first, municipalities after, so the most specific match wins.
AREAS = [
    ("Καλαμαριά", r"καλαμαρι|kalamari|νεα κρηνη|nea krini|αρετσου|aretsou|καραμπουρνακι|karampournaki|βυζαντιο"),
    ("Πυλαία", r"πυλαια|pylaia|pylea|πυλαιασ"),
    ("Πανόραμα", r"πανοραμα|panorama"),
    ("Θέρμη", r"θερμη|thermi|νεα ραιδεστοσ|νεο ρυσιο|ταγαραδεσ|τριαδι|βασιλικα|σουρωτη"),
    ("Χορτιάτης", r"χορτιατ|chortiat|φιλυρο|εξοχη|ασβεστοχωρι"),
    ("Θερμαϊκός", r"περαια|peraia|νεοι επιβατεσ|neoi epivates|αγια τριαδα|agia triada|μηχανιωνα|michaniona|επανομη|epanomi|θερμαικ|thermaik"),
    ("Νεάπολη-Συκιές", r"νεαπολ|neapol|συκιε|sykie|sykies"),
    ("Παύλος Μελάς", r"σταυρουπολ|stavroupol|πολιχνη|polichni|polixni|ευκαρπια|efkarpia|παυλοσ μελασ"),
    ("Κορδελιό-Εύοσμος", r"ευοσμ|evosm|κορδελι|kordeli|ελευθεριο"),
    ("Αμπελόκηποι-Μενεμένη", r"αμπελοκηπ|ampelokip|μενεμεν|menemen"),
    ("Ωραιόκαστρο", r"ωραιοκαστρ|oraiokastr|oreokastr|παλαιοκαστρ"),
    ("Δέλτα", r"σινδοσ|sindos|καλοχωρι|kalochori|χαλαστρα|chalastra|διαβατα|diavata|δελτα"),
    ("Λαγκαδάς", r"λαγκαδα|lagkada|langada|λαγυνα"),
    ("Πυλαία-Χορτιάτης", r"πυλαια|χορτιατ"),
    ("Θεσσαλονίκη-Ανατολικά", r"τουμπα|toumpa|toumba|χαριλαου|charilaou|ανω τουμπα|κατω τουμπα|αναληψη|analipsi|μποτσαρη|νεα παραλια|25ησ μαρτιου|μαρτιου|martiou|ντεπω|depo|κηφισια|βουλγαρη|ιπποκρατειο|φαληρο|faliro|τριανδρια|triandria"),
    ("Θεσσαλονίκη-Κέντρο", r"κεντρο θεσσαλον|center of thessalon|thessaloniki center|αριστοτελουσ|καμαρα|kamara|ροτοντα|λαδαδικα|βαρδαρ|vardar|ανω πολη|ano poli|αγια σοφια|αγιοσ δημητριοσ|ιπποδρομιου|λευκοσ πυργοσ|δεθ|πανεπιστημι|σκρα|λαχανοκηπ|ξηροκρηνη|ευαγγελιστρια|συντριβανι|παραλια θεσσαλον"),
    ("Θεσσαλονίκη", r"θεσσαλονικ|thessalonik|salonic|saloniki"),
]
OTHER_REGIONS = r"χαλκιδικ|halkidik|chalkidik|κασσανδρ|kassandr|kasandr|σιθωνι|sithon|αθην|athens|athina|πειραια|piraeus|πιερια|pieria|κατεριν|katerin|καβαλ|kaval|σερρ|serres|κιλκισ|kilkis|αλεξανδρουπ|alexandroup|βεροια|veria|λαρισ|laris|κρητ|crete|evia|ευβοια|πευκοχωρι|χανιωτη|σανη|sani|ποτιδαι|νεα μουδανια|moudania|αχαρνε|αλιμο|καλαμακι|μικρολιμανο|αριδαια|πολυκαστρο|κεφαλονι|ροδο|θασο|thasos|κυπρ|cyprus|nicosia|λευκωσ|limassol|λεμεσ"
NOT_LISTING = re.compile(r"^αποτελεσματα|^results|^αναζητηση|^search|blog|ιστορια|ανοικοδομηση", re.I)
FOREIGN = re.compile(r"[Ѐ-ӿ]")  # Cyrillic: translated duplicates of the same object

TYPES = [
    ("studio", r"γκαρσονιερ|στουντιο|studio|garsonier"),
    ("maisonette", r"μεζονετ|maisonette|mezonet"),
    ("apartment", r"διαμερισμ|apartment|flat\b|diamerism|ρετιρε|penthouse|οροφοδιαμερισμ"),
    ("house", r"μονοκατοικ|βιλα|villa|house|μονοκατ|monokatoik|detached|εξοχικ|κατοικια"),
    ("land", r"οικοπεδ|αγροτεμαχ|αγροτικ|plot|land\b|γη\b|oikoped|agrotemax|εκταση"),
    ("store", r"καταστημ|store|shop|katastim|μαγαζι|επαγγελματικοσ χωροσ|επαγγελματικο ακινητο|commercial"),
    ("office", r"γραφει|office|grafeio"),
    ("warehouse", r"αποθηκ|warehouse|apothik|βιοτεχν|βιομηχαν|industrial"),
    ("parking", r"παρκινγκ|θεση σταθμευσ|parking|γκαραζ|garage"),
    ("building", r"κτιριο|building|συγκροτημ|πολυκατοικ"),
    ("hotel", r"ξενοδοχ|hotel|ξενωνα"),
]


def first_area(text):
    for name, pat in AREAS:
        if re.search(pat, text):
            return name
    return ""


def main():
    rows = list(csv.DictReader(open(IN, encoding="utf-8")))
    out, seen_url, seen_key = [], set(), set()
    drop = Counter()
    for r in rows:
        title, url = r["title"], r["url"]
        t = plain(title)
        u = plain(urlunquote(url))
        if NOT_LISTING.search(t) or re.search(r"/listings/(areas/)?n\d+|/blog/|/news/", u):
            drop["not a listing"] += 1
            continue
        if FOREIGN.search(title) or re.search(r"/(ru|bg|sr|tr|zh|de|he)/", u):
            drop["translated duplicate"] += 1
            continue
        key_url = re.sub(r"[?#].*$|/+$", "", url.lower())
        if key_url in seen_url:
            drop["duplicate url"] += 1
            continue
        seen_url.add(key_url)

        text = " ".join([t, plain(r["location"]), u])
        try:
            price = float(r["price_eur"]) if r["price_eur"] else None
        except ValueError:
            price = None
        try:
            area = float(r["area_m2"]) if r["area_m2"] else None
        except ValueError:
            area = None
        if area is not None and not (5 <= area <= 100000):
            area = None

        # sale / rent: words first, then price level
        tx = ""
        if re.search(r"ενοικ|προσ ενοικ|to rent|for rent|\brent|enoik|μισθωσ|lease", text):
            tx = "rent"
        if re.search(r"πωλ|προσ πωλ|for sale|\bsale|pwl|polis|poleit|agora|αγορα", text):
            tx = "sale" if not tx else tx
        if price:
            if price < 10000 and tx != "sale":
                tx = "rent"
            elif price >= 30000:
                tx = "sale"
        if price and tx == "rent" and price >= 30000:
            tx = "sale"
        if price and tx == "sale" and price < 3000:
            price = None  # a monthly figure on a sale page is not the price

        # the agency name ("Μεσιτικό Γραφείο X") must not be read as an office
        t_obj = re.sub(r"(κτηματο)?μεσιτικ\w*\s+γραφει\w*[^|·,-]*", " ", t)
        ptype = ""
        for name, pat in TYPES:
            if re.search(pat, t_obj):
                ptype = name
                break
        if not ptype:
            ptype = r["type"] or next((n for n, p in TYPES if re.search(p, u)), "")

        area_name = first_area(text)
        if area_name:
            region = "thessaloniki"
        elif re.search(OTHER_REGIONS, text):
            region = "other"
        else:
            region = "unknown"

        dkey = (r["source_domain"], tx, ptype, price, area)
        if price and area and dkey in seen_key:
            drop["duplicate object"] += 1
            continue
        seen_key.add(dkey)

        out.append({
            "source_domain": r["source_domain"], "agency": r["agency"], "url": url, "title": title,
            "transaction": tx, "type": ptype, "price_eur": int(price) if price else "",
            "area_m2": round(area, 1) if area else "", "price_per_m2": round(price / area) if price and area else "",
            "bedrooms": r["bedrooms"], "floor": r["floor"], "year_built": r["year_built"],
            "region": region, "area": area_name, "location_raw": r["location"],
            "lat": r["lat"], "lon": r["lon"], "image": r["image"], "scraped_at": r["scraped_at"],
        })

    with open(OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(out[0].keys()))
        w.writeheader()
        w.writerows(out)

    n = len(out)
    pct = lambda k: f"{100 * sum(1 for x in out if x[k]) / n:.0f}%"
    print(f"input {len(rows)}, kept {n}, dropped {dict(drop)}")
    print(f"filled: transaction {pct('transaction')}, type {pct('type')}, price {pct('price_eur')}, "
          f"area {pct('area_m2')}, district {pct('area')}")
    print("region:", Counter(x["region"] for x in out))
    print("transaction:", Counter(x["transaction"] or "?" for x in out))
    print("type:", Counter(x["type"] or "?" for x in out).most_common())
    print("area:", Counter(x["area"] for x in out if x["region"] == "thessaloniki").most_common())


def urlunquote(u):
    from urllib.parse import unquote
    return unquote(u)


if __name__ == "__main__":
    main()
