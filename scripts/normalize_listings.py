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
IN_PORTALS = ["data/listings/listings_xe.csv",      # open portals collected by their own scripts
              "data/listings/listings_alerts.csv"]  # portal alert emails (scripts/ingest_portal_alerts.py)
PORTALS = ("xe.gr", "spitogatos.gr", "spiti24.gr", "tospitimou.gr", "plot.gr", "indomio.gr")
OUT = "data/listings/listings_normalized.csv"
HINTS = "data/listings/district_hints.csv"  # district read from the page (scripts/refine_districts.py)
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
    ("Θέρμη", r"\bmikra\b|\bkardia\b|καρδια θερμ|καρδια,? θεσσαλον|τησ καρδιασ θεσσαλον|πλαγιαρι|plagiari|θερμη|thermi|νεα ραιδεστοσ|νεο ρυσιο|ταγαραδεσ|τριαδι|βασιλικα|σουρωτη"),
    ("Χορτιάτης", r"χορτιατ|chortiat|φιλυρο|εξοχη|ασβεστοχωρι"),
    ("Θερμαϊκός", r"μεσημερι|mesimeri|αγγελοχωρι|aggelochori|νεα μηχανιωνα|περαια|peraia|νεοι επιβατεσ|neoi epivates|αγια τριαδα|agia triada|μηχανιωνα|michaniona|επανομη|epanomi|θερμαικ|thermaik"),
    ("Νεάπολη-Συκιές", r"νεαπολ|neapol|συκιε|sykie|sykies|\bπευκα\b|\bpefka\b|ρετζικι|retziki|αγιοσ παυλοσ|agios pavlos"),
    ("Παύλος Μελάς", r"σταυρουπολ|stavroupol|πολιχνη|polichni|polixni|ευκαρπια|efkarpia|παυλοσ μελασ"),
    ("Κορδελιό-Εύοσμος", r"ευοσμ|evosm|κορδελι|kordeli|ελευθεριο"),
    ("Αμπελόκηποι-Μενεμένη", r"αμπελοκηπ|ampelokip|μενεμεν|menemen"),
    ("Ωραιόκαστρο", r"ωραιοκαστρ|oraiokastr|oreokastr|παλαιοκαστρ"),
    ("Χαλκηδόνα", r"κουφαλι|koufali|χαλκηδον|chalkidon|μαλγαρα|malgara|κοιμηση θεοτοκου"),
    ("Βόλβη", r"βολβη|volvi|ασπροβαλτα|asprovalta|σταυροσ θεσσαλον|νεα απολλωνια|apollonia|ρεντινα|nea madytos|μαδυτοσ"),
    ("Δέλτα", r"νεα μαγνησια|magnisia|αδενδρο|adendro|κυμινα|kymina|νεα χαλκηδονα|σινδοσ|sindos|καλοχωρι|kalochori|χαλαστρα|chalastra|διαβατα|diavata|δελτα"),
    ("Λαγκαδάς", r"λαγκαδα|lagkada|langada|λαγυνα|μυγδονι|mygdoni|\bλητη|\bliti\b|δρυμοσ|drymos|μελισσοχωρι|melissochori|ζαγκλιβερ|zagkliver|ασσηροσ|σοχοσ|κολχικο"),
    ("Πυλαία-Χορτιάτης", r"πυλαια|χορτιατ"),
    ("Θεσσαλονίκη-Ανατολικά", r"βασιλισσησ ολγασ|βασ\. ολγασ|vasilissis olgas|δελφων|παπαναστασιου|papanastasiou|κωνσταντινουπολεωσ|παπαφη|papafi|ευαγγελιστριασ|τουμπα|toumpa|toumba|χαριλαου|charilaou|ανω τουμπα|κατω τουμπα|αναληψη|analipsi|μποτσαρη|νεα παραλια|25ησ μαρτιου|μαρτιου|martiou|ντεπω|depo|κηφισια|βουλγαρη|ιπποκρατειο|φαληρο|faliro|τριανδρια|triandria"),
    ("Θεσσαλονίκη-Κέντρο", r"τσιμισκ|tsimisk|μητροπολεωσ|mitropoleos|εγνατια|egnatia|ερμου|βενιζελου|προξενου κορομηλα|παυλου μελα|αγιασ σοφιασ|ναυαρινου|navarinou|κατουνη|ολυμπου|φιλικησ εταιρειασ|κεντρο θεσσαλον|center of thessalon|thessaloniki center|αριστοτελουσ|καμαρα|kamara|ροτοντα|λαδαδικα|βαρδαρ|vardar|ανω πολη|ano poli|αγια σοφια|αγιοσ δημητριοσ|ιπποδρομιου|λευκοσ πυργοσ|δεθ|πανεπιστημι|σκρα|λαχανοκηπ|ξηροκρηνη|ευαγγελιστρια|συντριβανι|παραλια θεσσαλον"),
    ("Θεσσαλονίκη", r"θεσσαλονικ|θεσ/νικ|thes+alonik|salonic|saloniki"),
]
# finer level inside the districts: (neighbourhood, district, pattern on accent-free lowercase text)
NEIGHBOURHOODS = [
    ("Βαρδάρης", "Θεσσαλονίκη-Κέντρο", r"βαρδαρ|vardar|πλατεια δημοκρατιασ|λαχανοκηπ|lachanokip"),
    ("Λαδάδικα", "Θεσσαλονίκη-Κέντρο", r"λαδαδικ|ladadik"),
    ("Άνω Πόλη", "Θεσσαλονίκη-Κέντρο", r"ανω πολη|ano poli|καστρα\b|kastra\b"),
    ("Ξηροκρήνη", "Θεσσαλονίκη-Κέντρο", r"ξηροκρην|xirokrin|παναγια φανερωμενη"),
    ("Καμάρα - Ροτόντα", "Θεσσαλονίκη-Κέντρο", r"καμαρα|kamara|ροτοντα|rotonda|ναυαρινου|navarinou"),
    ("Αγία Σοφία", "Θεσσαλονίκη-Κέντρο", r"αγια σοφια|αγιασ σοφιασ|agia sofia"),
    ("Ιπποδρόμιο", "Θεσσαλονίκη-Κέντρο", r"ιπποδρομι|ippodromi"),
    ("Αριστοτέλους", "Θεσσαλονίκη-Κέντρο", r"αριστοτελουσ|aristotelous"),
    ("Λευκός Πύργος", "Θεσσαλονίκη-Κέντρο", r"λευκοσ πυργοσ|λευκου πυργου|white tower"),
    ("Πανεπιστήμια - ΔΕΘ", "Θεσσαλονίκη-Κέντρο", r"πανεπιστημι|\bδεθ\b|\bαπθ\b"),
    ("Άνω Τούμπα", "Θεσσαλονίκη-Ανατολικά", r"ανω τουμπα|ano toump|ano toumb"),
    ("Κάτω Τούμπα", "Θεσσαλονίκη-Ανατολικά", r"κατω τουμπα|kato toump|kato toumb"),
    ("Τούμπα", "Θεσσαλονίκη-Ανατολικά", r"τουμπα|toumpa|toumba"),
    ("Χαριλάου", "Θεσσαλονίκη-Ανατολικά", r"χαριλαου|charilaou|xarilaou"),
    ("Μαρτίου", "Θεσσαλονίκη-Ανατολικά", r"25ησ μαρτιου|μαρτιου|martiou"),
    ("Ντεπώ", "Θεσσαλονίκη-Ανατολικά", r"ντεπω|depo\b"),
    ("Ανάληψη - Μπότσαρη", "Θεσσαλονίκη-Ανατολικά", r"αναληψη|analipsi|μποτσαρη|botsari"),
    ("Νέα Παραλία - Φάληρο", "Θεσσαλονίκη-Ανατολικά", r"νεα παραλια|nea paralia|φαληρο|faliro"),
    ("Βούλγαρη", "Θεσσαλονίκη-Ανατολικά", r"βουλγαρη|voulgari"),
    ("Τριανδρία", "Θεσσαλονίκη-Ανατολικά", r"τριανδρια|triandria"),
    ("Παπάφη", "Θεσσαλονίκη-Ανατολικά", r"παπαφη|papafi"),
    ("Ιπποκράτειο", "Θεσσαλονίκη-Ανατολικά", r"ιπποκρατει|ippokratei"),
    ("Αρετσού", "Καλαμαριά", r"αρετσου|aretsou"),
    ("Καραμπουρνάκι", "Καλαμαριά", r"καραμπουρνακι|karampournaki|karabournaki"),
    ("Νέα Κρήνη", "Καλαμαριά", r"νεα κρηνη|nea krini"),
    ("Σταυρούπολη", "Παύλος Μελάς", r"σταυρουπολ|stavroupol"),
    ("Πολίχνη", "Παύλος Μελάς", r"πολιχνη|polichni|polixni"),
    ("Ευκαρπία", "Παύλος Μελάς", r"ευκαρπια|efkarpia"),
    ("Νεάπολη", "Νεάπολη-Συκιές", r"νεαπολ|neapol"),
    ("Συκιές", "Νεάπολη-Συκιές", r"συκιε|sykie"),
    ("Πεύκα", "Νεάπολη-Συκιές", r"\bπευκα\b|\bpefka\b"),
    ("Εύοσμος", "Κορδελιό-Εύοσμος", r"ευοσμ|evosm"),
    ("Κορδελιό", "Κορδελιό-Εύοσμος", r"κορδελι|kordeli"),
    ("Αμπελόκηποι", "Αμπελόκηποι-Μενεμένη", r"αμπελοκηπ|ampelokip"),
    ("Μενεμένη", "Αμπελόκηποι-Μενεμένη", r"μενεμεν|menemen"),
    ("Περαία", "Θερμαϊκός", r"περαια|peraia"),
    ("Νέοι Επιβάτες", "Θερμαϊκός", r"νεοι επιβατεσ|neoi epivates"),
    ("Αγία Τριάδα", "Θερμαϊκός", r"αγια τριαδα|agia triada"),
    ("Μηχανιώνα", "Θερμαϊκός", r"μηχανιωνα|michaniona"),
    ("Επανομή", "Θερμαϊκός", r"επανομη|epanomi"),
    ("Νέα Ραιδεστός", "Θέρμη", r"νεα ραιδεστοσ|nea raidestos"),
    ("Ταγαράδες", "Θέρμη", r"ταγαραδεσ|tagarades"),
    ("Τριάδι", "Θέρμη", r"τριαδι\b|triadi\b"),
]


def neighbourhood(text, district):
    """First neighbourhood named in text that lies in the district (or any, if district is generic)."""
    for name, parent, pat in NEIGHBOURHOODS:
        if re.search(pat, text) and (district in ("", "Θεσσαλονίκη") or parent == district):
            return name, parent
    return "", ""


OTHER_REGIONS = r"χαλκιδικ|halkidik|chalkidik|κασσανδρ|kassandr|kasandr|σιθωνι|sithon|αθην|athens|athina|πειραια|piraeus|πιερια|pieria|κατεριν|katerin|καβαλ|kaval|σερρ|serres|κιλκισ|kilkis|αλεξανδρουπ|alexandroup|βεροια|veria|λαρισ|laris|κρητ|crete|evia|ευβοια|πευκοχωρι|χανιωτη|σανη|sani|ποτιδαι|νεα μουδανια|moudania|αχαρνε|αλιμο|καλαμακι|μικρολιμανο|αριδαια|πολυκαστρο|κεφαλονι|ροδο|θασο|thasos|εξαρχ|αττικ|σοζοπολ|αφυτο|ελανη|πολυχρον|φουρκα|μολα καλυβ|χανιωτ|chanioti|ν\. χαλκιδ|αγια αναστασια ανθεμ|κυπρ|cyprus|nicosia|λευκωσ|limassol|λεμεσ|καλλικρατ|kallikrat|λιτοχωρ|litochor|αλεξανδρει|alexandrei|πετραλων|petralon|κατω πετραλων|φλογητ|flogit|βεροι|ημαθι|imathi|πελλα|pella|γιαννιτσ|giannitsa|εδεσσα|edessa|ναουσα|naousa|κοζαν|kozani|ιωαννιν|ioannin|βολοσ\b|volos|πατρα|patra|θεσσαλια|παλληνη|pallini|ραφηνα|γλυφαδα|μαρουσι|κηφισια αττικ"
NOT_LISTING = re.compile(r"^αποτελεσματα|^results|^αναζητηση|^search|blog|ιστορια|ανοικοδομηση|η εταιρεια|εταιρεια μασ|ποιοι ειμαστε|επικοινωνια|^ακινητα - |ευκαιριεσ ακινητων|^ergebnisse|^print$|^rezultat|^risultati", re.I)
FOREIGN = re.compile(r"[Ѐ-ӿ]")  # Cyrillic: translated duplicates of the same object

TYPES = [
    ("studio", r"γκαρσονιερ|στουντιο|studio|garsonier"),
    ("maisonette", r"μεζονετ|maisonette|mezonet"),
    ("apartment", r"διαμερισμ|apartment|flat\b|diamerism|ρετιρε|penthouse|οροφοδιαμερισμ|\bloft\b|wohnung"),
    ("house", r"μονοκατοικ|βιλα|villa|house|μονοκατ|monokatoik|detached|εξοχικ|παραθεριστικ|κατοικια|\bhaus\b"),
    ("land", r"οικοπεδ|αγροτεμαχ|αγροτικ|plot|land\b|γη\b|oikoped|agrotemax|agrotemach|εκταση|agricultural|parcel|grundst"),
    ("store", r"καταστημ|store|shop|katastim|μαγαζι|επαγγελματικοσ χωροσ|επαγγελματικο ακινητο|commercial|retail"),
    ("office", r"γραφει|office|grafeio"),
    ("warehouse", r"αποθηκ|warehouse|apothik|βιοτεχν|βιομηχαν|industrial"),
    ("parking", r"παρκινγκ|παρκιν|θεση σταθμευσ|parking|γκαραζ|garage"),
    ("building", r"κτιριο|building|συγκροτημ|πολυκατοικ"),
    ("hotel", r"ξενοδοχ|hotel|ξενωνα"),
    # generic business words only when nothing more specific is named
    ("store", r"επαγγελματικ|αιθουσα|επιχειρησ|gewerbe"),
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
    import os
    rows = list(csv.DictReader(open(IN, encoding="utf-8")))
    for extra in IN_PORTALS:
        if os.path.exists(extra):
            rows += list(csv.DictReader(open(extra, encoding="utf-8")))
    history = load_history()
    hints = {h["url"]: h for h in csv.DictReader(open(HINTS, encoding="utf-8"))} if os.path.exists(HINTS) else {}
    out, seen_url, seen_key = [], set(), set()
    drop = Counter()
    for r in rows:
        title, url = r["title"], r["url"]
        t = plain(title)
        u = plain(urlunquote(url))
        if NOT_LISTING.search(t) or re.search(r"/listings/(areas/)?n/?\d+|/blog/|/news/|/print/|/insights?/|/articles?/|-guide-", u):
            drop["not a listing"] += 1
            continue
        if FOREIGN.search(title) or re.search(r"/(ru|bg|sr|tr|zh|de|he|it|fr|ro)/|[?&](language|lang)=(de|bg|ru|sr|tr|it|fr|ro|zh|he)\b", u):
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

        h = hints.get(url)
        if h and h["region"] and area_name in ("", "Θεσσαλονίκη") and region != "other":
            if h["region"] == "other":
                region, area_name = ("other", "") if region == "unknown" else (region, area_name)
            else:
                region, area_name = "thessaloniki", h["area"] or area_name or "Θεσσαλονίκη"
        nb = ""
        if region == "thessaloniki":
            nb, parent = neighbourhood(own, area_name)
            if not nb:
                nb, parent = neighbourhood(loc, area_name)
            if not nb and h and h.get("neighbourhood") and h["area"] == area_name:
                nb, parent = h["neighbourhood"], area_name
            if nb and area_name in ("", "Θεσσαλονίκη"):
                area_name = parent  # the neighbourhood tells the district

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
            "source_kind": "portal" if r["source_domain"] in PORTALS else "agency_site",
            "private_owner": "yes" if r["agency"].startswith("Ιδιώτης") else "",
            "transaction": tx, "type": ptype, "price_eur": int(price) if price else "",
            "area_m2": round(area, 1) if area else "", "price_per_m2": round(price / area) if price and area else "",
            "bedrooms": r["bedrooms"], "floor": r["floor"], "year_built": r["year_built"],
            "region": region, "area": area_name, "neighbourhood": nb, "location_raw": r["location"],
            "lat": r["lat"], "lon": r["lon"], "image": r["image"],
            "listing_date": ldate, "listing_date_kind": lkind, "first_seen": h["first_seen"],
            "scraped_at": r["scraped_at"],
        })

    fill_from_coordinates(out)
    fill_from_agency(out)

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


# approximate centres of the districts above (lat, lon)
CENTRES = {
    "Θεσσαλονίκη-Κέντρο": (40.636, 22.943), "Θεσσαλονίκη-Ανατολικά": (40.612, 22.963),
    "Καλαμαριά": (40.582, 22.950), "Πυλαία": (40.600, 22.987), "Πανόραμα": (40.588, 23.032),
    "Θέρμη": (40.547, 23.020), "Θερμαϊκός": (40.497, 22.925), "Νεάπολη-Συκιές": (40.652, 22.953),
    "Παύλος Μελάς": (40.668, 22.936), "Κορδελιό-Εύοσμος": (40.668, 22.908),
    "Αμπελόκηποι-Μενεμένη": (40.652, 22.918), "Ωραιόκαστρο": (40.730, 22.917), "Δέλτα": (40.668, 22.800),
    "Χορτιάτης": (40.598, 23.100), "Λαγκαδάς": (40.750, 23.068), "Χαλκηδόνα": (40.775, 22.600),
    "Βόλβη": (40.690, 23.450),
}


def in_thessaloniki_unit(lat, lon):
    """Rough outline of the Thessaloniki regional unit; the south-east corner is Halkidiki."""
    if not (40.40 <= lat <= 41.10 and 22.50 <= lon <= 23.80):
        return False
    return lon <= 23.20 or lat >= 40.55


def fill_from_coordinates(out):
    """Listings with coordinates but no district: nearest district centre (within ~4 km).
    Sites that give every listing the same point (their office) are ignored."""
    import math
    by_site = {}
    for r in out:
        if r["lat"] and r["lon"]:
            by_site.setdefault(r["source_domain"], []).append((r["lat"], r["lon"]))
    office_like = {d for d, pts in by_site.items() if len(pts) >= 5 and Counter(pts).most_common(1)[0][1] / len(pts) > 0.5}
    moved = Counter()
    for r in out:
        if not (r["lat"] and r["lon"]) or r["source_domain"] in office_like or r["area"] not in ("", "Θεσσαλονίκη"):
            continue
        try:
            lat, lon = float(r["lat"]), float(r["lon"])
        except ValueError:
            continue
        if r["region"] != "other" and not in_thessaloniki_unit(lat, lon):
            if r["region"] == "unknown" and 34 < lat < 42 and 19 < lon < 30:
                r["region"] = "other"  # somewhere else in Greece
                moved["region other"] += 1
            continue
        if r["region"] == "other":
            continue
        name, (clat, clon) = min(CENTRES.items(), key=lambda c: (c[1][0] - lat) ** 2 + ((c[1][1] - lon) * 0.76) ** 2)
        km = math.hypot(clat - lat, (clon - lon) * 0.76) * 111
        r["region"] = "thessaloniki"
        if km <= 4:
            r["area"] = name
            moved["district"] += 1
        else:
            r["area"] = r["area"] or "Θεσσαλονίκη"
            moved["region only"] += 1
    print("from coordinates:", dict(moved), "; ignored office-point sites:", len(office_like))


def fill_from_agency(out):
    """Region still unknown: an agency whose located listings are almost all in
    Thessaloniki most likely lists this one there too (district stays unknown)."""
    per = {}
    for r in out:
        if r["region"] in ("thessaloniki", "other") and r.get("source_kind") != "portal":
            c = per.setdefault(r["source_domain"], Counter())
            c[r["region"]] += 1
    n = 0
    for r in out:
        c = per.get(r["source_domain"])
        if r["region"] == "unknown" and c and sum(c.values()) >= 10 and c["thessaloniki"] / sum(c.values()) >= 0.9:
            r["region"], r["area"] = "thessaloniki", "Θεσσαλονίκη"
            n += 1
    print("region from agency profile:", n)


def urlunquote(u):
    from urllib.parse import unquote
    return unquote(u)


if __name__ == "__main__":
    main()
