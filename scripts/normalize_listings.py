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
HISTORY = "data/listings/seen_history.csv"  # url -> first_seen, last_seen across collection runs


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
OTHER_REGIONS = r"χαλκιδικ|halkidik|chalkidik|κασσανδρ|kassandr|kasandr|σιθωνι|sithon|αθην|athens|athina|πειραια|piraeus|πιερια|pieria|κατεριν|katerin|καβαλ|kaval|σερρ|serres|κιλκισ|kilkis|αλεξανδρουπ|alexandroup|βεροια|veria|λαρισ|laris|κρητ|crete|evia|ευβοια|πευκοχωρι|χανιωτη|σανη|sani|ποτιδαι|νεα μουδανια|moudania|αχαρνε|αλιμο|καλαμακι|μικρολιμανο|αριδαια|πολυκαστρο|κεφαλονι|ροδο|θασο|thasos|εξαρχ|αττικ|σοζοπολ|αφυτο|ελανη|πολυχρον|φουρκα|μολα καλυβ|χανιωτ|chanioti|ν\. χαλκιδ|αγια αναστασια ανθεμ|κυπρ|cyprus|nicosia|λευκωσ|limassol|λεμεσ"
NOT_LISTING = re.compile(r"^αποτελεσματα|^results|^αναζητηση|^search|blog|ιστορια|ανοικοδομηση|η εταιρεια|εταιρεια μασ|ποιοι ειμαστε|επικοινωνια|^ακινητα - |ευκαιριεσ ακινητων", re.I)
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


def load_history():
    import os
    if not os.path.exists(HISTORY):
        return {}
    return {r["url"]: r for r in csv.DictReader(open(HISTORY, encoding="utf-8"))}


def listing_date(r):
    """Best date the site gives: the later of 'updated' and sitemap lastmod, else 'published'."""
    upd = max(r.get("date_updated", ""), r.get("date_sitemap", ""))
    return (upd, "updated") if upd else ((r["date_published"], "published") if r.get("date_published") else ("", ""))


def main():
    rows = list(csv.DictReader(open(IN, encoding="utf-8")))
    history = load_history()
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
        # keep the query (e.g. ?dios_code=218938 identifies the listing), drop fragments and tracking
        key_url = re.sub(r"#.*$", "", url.lower())
        key_url = re.sub(r"([?&])(utm_\w+|fbclid|gclid|lang|sr)=[^&]*&?", r"\1", key_url).rstrip("?&/")
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

        # a price written in the title ("..., €700", "700 €") is the most reliable one
        m = re.search(r"€\s?(\d{1,3}(?:\.\d{3})+|\d+)(?![\d.,])|(?<![\d.,])(\d{1,3}(?:\.\d{3})+|\d+)\s?€", title)
        if m:
            price = float((m.group(1) or m.group(2)).replace(".", ""))

        # sale / rent: explicit words on the page or in the title win; price level only as a fallback
        words = t + " " + u
        tx = ""
        if re.search(r"προσ ενοικ|ενοικιαζ|ενοικιαση|enoikiasi|enoikiaz|for[-_ ]rent|to[-_ ]rent|\brent\b|μισθωσ", words):
            tx = "rent"
        elif re.search(r"προσ πωλ|πωλειται|πωλουντ|πωληση|pwlisi|polisi|poleitai|for[-_ ]sale|\bsale\b", words):
            tx = "sale"
        elif r["transaction"] in ("sale", "rent"):
            tx = r["transaction"]
        elif price:
            tx = "rent" if price < 10000 else "sale" if price >= 30000 else ""
        if price and tx == "sale" and price < 3000:
            price = None  # a monthly figure on a sale page is not the price
        if price and tx == "rent" and price > 20000:
            price = None  # a sale-sized figure on a rent page came from elsewhere on the page

        # the agency name ("Μεσιτικό Γραφείο X") must not be read as an office
        t_obj = re.sub(r"(κτηματο)?μεσιτικ\w*\s+γραφει\w*[^|·,-]*", " ", t)
        ptype = ""
        for name, pat in TYPES:
            if re.search(pat, t_obj):
                ptype = name
                break
        if not ptype:
            ptype = r["type"] or next((n for n, p in TYPES if re.search(p, u)), "")

        # region: what the listing itself says (title, URL) beats the agency's own address
        # or site menu that may have ended up in location_raw
        own = re.sub(r"(κτηματο)?μεσιτικ\w*\s+γραφει\w*\s*θεσσαλονικ\w*", " ", t) + " " + u
        loc = plain(r["location"])
        specific = [a for a in AREAS if a[0] != "Θεσσαλονίκη"]
        area_name, region = "", "unknown"
        hit = next((n for n, pat in specific if re.search(pat, own)), "")
        if re.search(OTHER_REGIONS, own) and not hit:
            region = "other"
        elif hit and not re.search(OTHER_REGIONS, own):
            area_name, region = hit, "thessaloniki"
        elif re.search(OTHER_REGIONS, own):
            region = "other"
        else:
            hit = next((n for n, pat in specific if re.search(pat, loc)), "")
            if hit and not re.search(OTHER_REGIONS, loc):
                area_name, region = hit, "thessaloniki"
            elif re.search(r"θεσσαλονικ|thessalonik", own + " " + loc):
                area_name, region = "Θεσσαλονίκη", "thessaloniki"
            elif re.search(OTHER_REGIONS, loc):
                region = "other"

        dkey = (r["source_domain"], tx, ptype, price, area)
        if price and area and dkey in seen_key:
            drop["duplicate object"] += 1
            continue
        seen_key.add(dkey)

        seen_day = (r.get("scraped_at") or "")[:10]
        h = history.setdefault(key_url, {"url": key_url, "first_seen": seen_day, "last_seen": seen_day})
        h["first_seen"] = min(h["first_seen"] or seen_day, seen_day) if seen_day else h["first_seen"]
        h["last_seen"] = max(h["last_seen"] or seen_day, seen_day)
        ldate, lkind = listing_date(r)

        out.append({
            "source_domain": r["source_domain"], "agency": r["agency"], "url": url, "title": title,
            "transaction": tx, "type": ptype, "price_eur": int(price) if price else "",
            "area_m2": round(area, 1) if area else "", "price_per_m2": round(price / area) if price and area else "",
            "bedrooms": r["bedrooms"], "floor": r["floor"], "year_built": r["year_built"],
            "region": region, "area": area_name, "location_raw": r["location"],
            "lat": r["lat"], "lon": r["lon"], "image": r["image"],
            "listing_date": ldate, "listing_date_kind": lkind, "first_seen": h["first_seen"],
            "scraped_at": r["scraped_at"],
        })

    with open(HISTORY, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["url", "first_seen", "last_seen"])
        w.writeheader()
        w.writerows(sorted(history.values(), key=lambda h: h["url"]))

    with open(OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(out[0].keys()))
        w.writeheader()
        w.writerows(out)

    n = len(out)
    pct = lambda k: f"{100 * sum(1 for x in out if x[k]) / n:.0f}%"
    print(f"input {len(rows)}, kept {n}, dropped {dict(drop)}")
    print(f"filled: transaction {pct('transaction')}, type {pct('type')}, price {pct('price_eur')}, "
          f"area {pct('area_m2')}, district {pct('area')}")
    print(f"with site date: {pct('listing_date')}")
    print("region:", Counter(x["region"] for x in out))
    print("transaction:", Counter(x["transaction"] or "?" for x in out))
    print("type:", Counter(x["type"] or "?" for x in out).most_common())
    print("area:", Counter(x["area"] for x in out if x["region"] == "thessaloniki").most_common())


def urlunquote(u):
    from urllib.parse import unquote
    return unquote(u)


if __name__ == "__main__":
    main()
