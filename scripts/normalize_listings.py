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
              "data/listings/listings_remax.csv",   # RE/MAX network result pages (scripts/collect_remax_listings.py)
              "data/listings/listings_xe_profiles.csv",  # XE listings from agency pages (scripts/collect_xe_profiles.py)
              "data/listings/listings_ktimatoemporiki.csv",  # Ktimatoemporiki network (scripts/collect_ktimatoemporiki.py)
              "data/listings/listings_alerts.csv",  # portal alert emails (scripts/ingest_portal_alerts.py)
              "data/listings/listings_telegram.csv"]  # public Telegram channels (scripts/collect_telegram.py)
PORTALS = ("xe.gr", "remax.gr", "spitogatos.gr", "spiti24.gr", "tospitimou.gr", "plot.gr", "indomio.gr", "t.me")
OUT = "data/listings/listings_normalized.csv"
HINTS = "data/listings/district_hints.csv"  # district read from the page (scripts/refine_districts.py)
HISTORY = "data/listings/seen_history.csv"
ALERT_DAYS = 30  # listings known only from portal alerts / Telegram stay this long
import datetime as _dt  # noqa: E402
ALERT_CUTOFF = (_dt.date.today() - _dt.timedelta(days=ALERT_DAYS)).isoformat()  # url -> first_seen, last_seen across collection runs


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
    ("Χαλκηδόνα", r"κουφαλι|koufali|χαλκηδον|chalkidon|κοιμηση θεοτοκου|αγιο\w? αθανασι|agios athanasios|γεφυρα θεσσαλον|\bγεφυρα\b|gefyra"),
    ("Βόλβη", r"βολβη|volvi|ασπροβαλτα|asprovalta|σταυροσ θεσσαλον|νεα απολλωνια|apollonia|ρεντινα|nea madytos|μαδυτοσ"),
    ("Δέλτα", r"μαλγαρα|malgara|νεα μαγνησια|magnisia|αδενδρο|adendro|κυμινα|kymina|νεα χαλκηδονα|σινδοσ|sindos|καλοχωρι|kalochori|χαλαστρα|chalastra|διαβατα|diavata|δελτα"),
    ("Λαγκαδάς", r"λαγκαδα|lagkada|langada|λαγυνα|μυγδονι|mygdoni|\bλητη|\bliti\b|δρυμοσ|drymos|μελισσοχωρι|melissochori|ζαγκλιβερ|zagkliver|ασσηροσ|σοχοσ|κολχικο"),
    ("Πυλαία-Χορτιάτης", r"πυλαια|χορτιατ"),
    ("Θεσσαλονίκη-Ανατολικά", r"βασιλισσησ ολγασ|βασ\. ολγασ|vasilissis olgas|δελφων|παπαναστασιου|papanastasiou|κωνσταντινουπολεωσ|παπαφη|papafi|ευαγγελιστριασ|τουμπα|toumpa|toumba|χαριλαου|charilaou|ανω τουμπα|κατω τουμπα|αναληψη|analipsi|μποτσαρη|νεα παραλια|25ησ μαρτιου|μαρτιου|martiou|ντεπω|depo|κηφισια|βουλγαρη|ιπποκρατειο|φαληρο|faliro|τριανδρια|triandria"),
    ("Θεσσαλονίκη-Κέντρο", r"τσιμισκ|tsimisk|μητροπολεωσ|mitropoleos|εγνατια|egnatia|ερμου|βενιζελου|προξενου κορομηλα|παυλου μελα|αγιασ σοφιασ|ναυαρινου|navarinou|κατουνη|ολυμπου|φιλικησ εταιρειασ|κεντρο θεσσαλον|center of thessalon|thessaloniki center|αριστοτελουσ|καμαρα|kamara|ροτοντα|λαδαδικα|βαρδαρ|vardar|ανω πολη|ano poli|αγια σοφια|αγιοσ δημητριοσ|ιπποδρομιου|λευκοσ πυργοσ|δεθ|πανεπιστημι|σκρα|λαχανοκηπ|ξηροκρηνη|ευαγγελιστρια|συντριβανι|παραλια θεσσαλον"),
    ("Θεσσαλονίκη", r"θεσσαλονικ|θεσ/νικ|thes+alonik|salonic|saloniki"),
]
# finer level: the areas of Jeny Shir's Thessaloniki map (scripts/districts.py)
import os as _os, sys as _sys  # noqa: E401
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import districts  # noqa: E402

# neighbourhood names written by earlier versions of refine_districts.py -> map area id
OLD_NB = {"Βαρδάρης": "vardaris", "Λαδάδικα": "ladadika", "Άνω Πόλη": "anopoli", "Ξηροκρήνη": "xirokrini",
          "Καμάρα - Ροτόντα": "kamara", "Αγία Σοφία": "agiasofia", "Αριστοτέλους": "istoriko",
          "Λευκός Πύργος": "paliaparalia", "Πανεπιστήμια - ΔΕΘ": "kamara", "Άνω Τούμπα": "anotoumpa",
          "Κάτω Τούμπα": "katotoumpa", "Χαριλάου": "charilaou", "Μαρτίου": "martiou", "Ντεπώ": "depo",
          "Ανάληψη - Μπότσαρη": "analipsi", "Νέα Παραλία - Φάληρο": "neaparalia", "Βούλγαρη": "voulgari",
          "Τριανδρία": "triandria", "Παπάφη": "papafi", "Ιπποκράτειο": "faliro", "Αρετσού": "kalamaria",
          "Καραμπουρνάκι": "kalamaria", "Νέα Κρήνη": "kalamaria", "Σταυρούπολη": "stavroupoli",
          "Πολίχνη": "polichni", "Ευκαρπία": "efkarpia", "Νεάπολη": "neapoli", "Συκιές": "sykies",
          "Πεύκα": "pefka", "Εύοσμος": "evosmos", "Κορδελιό": "kordelio", "Αμπελόκηποι": "ampelokipoi",
          "Μενεμένη": "menemeni", "Περαία": "perea", "Νέοι Επιβάτες": "neoiepivates"}


def neighbourhood(text, district):
    """Map area named in text that lies in the district -> (id, its district)."""
    i = districts.by_name(text, district)
    return (i, districts.AREAS[i]["district"]) if i else ("", "")


OTHER_REGIONS = r"χαλκιδικ|halkidik|chalkidik|κασσανδρ|kassandr|kasandr|σιθωνι|sithon|αθην|athens|athina|πειραια|piraeus|πιερια|pieria|κατεριν|katerin|καβαλ|kaval|σερρ|serres|κιλκισ|kilkis|αλεξανδρουπ|alexandroup|βεροια|veria|λαρισ|laris|κρητ|crete|evia|ευβοια|πευκοχωρι|χανιωτη|σανη|sani|ποτιδαι|νεα μουδανια|moudania|αχαρνε|αλιμο|καλαμακι|μικρολιμανο|αριδαια|πολυκαστρο|κεφαλονι|ροδο|θασο|thasos|εξαρχ|αττικ|σοζοπολ|αφυτο|ελανη|πολυχρον|φουρκα|μολα καλυβ|χανιωτ|chanioti|ν\. χαλκιδ|αγια αναστασια ανθεμ|κυπρ|cyprus|nicosia|λευκωσ|limassol|λεμεσ|καλλικρατ|kallikrat|λιτοχωρ|litochor|αλεξανδρει|alexandrei|πετραλων|petralon|κατω πετραλων|φλογητ|flogit|βεροι|ημαθι|imathi|πελλα|pella|γιαννιτσ|giannitsa|εδεσσα|edessa|ναουσα|naousa|κοζαν|kozani|ιωαννιν|ioannin|βολοσ\b|volos|πατρα|patra|θεσσαλια|υψηλομετωπ|ypsilometop|πελοποννησ|κεφαλονι|makrygial|makrigial|μακρυγιαλ|psakoud|ψακουδ|mallorca|μαγιορκ|παλληνη|pallini|ραφηνα|γλυφαδα|μαρουσι|κηφισια αττικ|attik|attica|liosia|λιοσια|\bekali|εκαλη|acharn|\bvoula\b|βουλα\b|vouliagm|βουλιαγμ|syros|συρο\b|συροσ|karditsa|καρδιτσ|amint|αμυνται|marousi|chalandri|χαλανδρι|peristeri|περιστερι|nea smyrni|νεα σμυρνη|glyfada|rafina|\bvari\b|kavala|περιγιαλι καβαλ|thasos|paros|παροσ|naxos|ναξο|mykono|μυκονο|santorin|σαντορ|corfu|κερκυρ|zakynth|ζακυνθ"
# other regional units of Greece and Athens / Piraeus districts that agency sites in Thessaloniki also sell
OTHER_REGIONS += (r"|ρεντη|rentis|νεο φαληρο|παλαιο φαληρο|faliro athin|νικαια|nikaia|κορυδαλλ|κερατσιν|keratsin|περαμα|perama|"
                  r"μοσχατο|ζωγραφου|βυρωνα|ηλιουπολ|ilioupol|χολαργ|παπαγου|νεα ιωνια|μεταμορφωσ αττ|αιγαλε|χαιδαρι|"
                  r"ιλιον|πετρουπολ|μενιδι|μελισσια|βριλησσ|πεντελ|νεα ερυθραια|αγια παρασκευη|γαλατσι|"
                  r"πατησι|κυψελ|κολωνακ|kolonaki|πλακα αθ|μετς|παγκρατ|pagrati|νεοσ κοσμοσ|δαφνη αττ|αμπελοκηποι αθ|"
                  r"ημαθια|imathia|veroia|\bδραμα\b|\bdrama\b|ξανθη\b|xanthi|κομοτην|komotini|ροδοπ|evros|ορεστιαδ|"
                  r"φλωριν|florina|καστορι|kastoria|γρεβεν|grevena|τρικαλ|trikala|πρεβεζ|preveza|θεσπρωτ|ηγουμενιτσ|"
                  r"αιτωλοακαρν|μεσολογγ|αγρινι|agrinio|ευρυταν|καρπενησ|φθιωτ|λαμια|lamia|φωκιδ|βοιωτ|θηβα|λιβαδει|"
                  r"χαλκιδα|chalkida|αργολ|ναυπλι|nafplio|αρκαδ|τριπολ|κορινθ|korinth|λακων|σπαρτ|μεσσην|καλαματ|kalamata|"
                  r"ηλεια|πυργοσ ηλ|αχαια|ηρακλειο κρ|heraklion|χανια|chania|ρεθυμν|rethymn|λασιθ|αγιοσ νικολαοσ κρ|"
                  r"δωδεκανησ|καλυμν|κυκλαδ|λεσβ|μυτιλην|χιοσ\b|σαμοσ\b|λευκαδ|lefkada|ιθακ|αμοργ|τηνοσ\b|ανδροσ\b|"
                  r"σιφνο|μηλοσ\b|σκιαθ|skiathos|σκοπελ|αλοννησ|πηλιο|pilio|θεσπρωτ|ναυπακτ|αμφισσ|δελφοι|αραχοβ|"
                  r"σκυδρα|αλμωπ|αριδαι|κρυα βρυσ|πολυγυρο|ιερισσ|ουρανουπολ|αρναια|νικητη|νεοσ μαρμαρασ|τορωνη|"
                  r"σερρων|σιδηροκαστρ|νιγριτ|ηρακλεια σερρ|πολυκαστρ|γουμενισσ|"
                  r"albania|αλβανι|bulgaria|βουλγαρι|turkey|τουρκι|germany|γερμανι|dubai|ντουμπαι")
_OTHER = re.compile(OTHER_REGIONS)


def is_other(text):
    """Names a place outside the Thessaloniki unit. A name followed by a house number is a street
    of Thessaloniki (Κρήτης 76, Καστοριάς 12), not the region."""
    return any(not re.match(r"[^\W\d]*\.?\s*\d", text[m.end():]) for m in _OTHER.finditer(text or ""))


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
    # an XE alert link (xe.gr/p/<id>) and the same listing read from the agency page: keep the page record
    xe_ids = {m.group(1) for r in rows if r["source_domain"] == "xe.gr"
              for m in [re.search(r"/property/d/[^/]+/([0-9a-f-]{36})", r["url"])] if m}
    rows = [r for r in rows if not (r["source_domain"] == "xe.gr" and
                                    (re.search(r"xe\.gr/p/([0-9a-f-]{36})", r["url"]) or [None, None])[1] in xe_ids)]
    history = load_history()
    hints = {h["url"]: h for h in csv.DictReader(open(HINTS, encoding="utf-8"))} if os.path.exists(HINTS) else {}
    # one street address with a house number repeated on many listings of a site = the agency's office
    loc_count, site_count = Counter((r["source_domain"], r["location"]) for r in rows), Counter(r["source_domain"] for r in rows)
    office_address = {k for k, n in loc_count.items() if k[1] and re.search(r"\d", k[1]) and n >= 5 and n / site_count[k[0]] >= 0.2}
    out, seen_url, seen_key = [], set(), set()
    drop = Counter()
    for r in rows:
        title, url = r["title"], r["url"]
        t = plain(title)
        u = plain(urlunquote(url))
        if NOT_LISTING.search(t) or re.search(r"/listings/(areas/)?n/?\d+|/blog/|/news/|/print/|/insights?/|/articles?/|-guide-", u):
            drop["not a listing"] += 1
            continue
        if (FOREIGN.search(title) and r["source_domain"] != "t.me") or re.search(r"/(ru|bg|sr|tr|zh|de|he|it|fr|ro)/|[?&](language|lang)=(de|bg|ru|sr|tr|it|fr|ro|zh|he)\b", u):
            drop["translated duplicate"] += 1
            continue
        # portals (alert emails) and Telegram cannot be re-checked: after ALERT_DAYS the listing is
        # most likely sold or withdrawn, so it leaves the search
        if (r.get("date_source") == "portal alert" or r["source_domain"] == "t.me") and r.get("date_published") \
                and r["date_published"] < ALERT_CUTOFF:
            drop["old portal alert"] += 1
            continue
        # keep the query (e.g. ?dios_code=218938 identifies the listing), drop fragments and tracking
        key_url = re.sub(r"#.*$", "", url.lower())
        key_url = re.sub(r"([?&])(utm_\w+|fbclid|gclid|lang|sr)=[^&]*&?", r"\1", key_url).rstrip("?&/")
        if key_url in seen_url:
            drop["duplicate url"] += 1
            continue
        seen_url.add(key_url)

        if (r["source_domain"], r["location"]) in office_address or \
                re.search(r"\b2\d{9}\b|\b69\d{8}\b|@|info\b|τηλ\.?|tel\b", r["location"] or "", re.I):
            r = dict(r, location="")  # agency address / phone in the location field
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
        if price and area and tx == "sale" and price / area < 250 and not re.search(r"οικοπεδ|αγροτεμ|\bplot|\bland\b|agric|parcel|εκταση", t + " " + u):
            price = None  # e.g. 4.000 EUR for 115 m2: a monthly or wrong figure, not a sale price

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
        area_name, region, how = "", "unknown", ""
        hit = next((n for n, pat in specific if re.search(pat, own)), "")
        if is_other(own) and not hit:
            region, how = "other", "listing"
        elif hit and not is_other(own):
            area_name, region, how = hit, "thessaloniki", "listing"
        elif is_other(own):
            region, how = "other", "listing"
        elif re.search(r"θεσσαλονικ|thessalonik", own):
            area_name, region, how = "Θεσσαλονίκη", "thessaloniki", "listing"
        else:
            # the location field: a named place of another region beats a bare "Θεσσαλονίκη"
            # (that is often the agency's own address next to the property's place)
            hit = next((n for n, pat in specific if re.search(pat, loc)), "")
            if hit and not is_other(loc):
                area_name, region, how = hit, "thessaloniki", "listing"
            elif is_other(loc):
                region, how = "other", "listing"
            elif re.search(r"θεσσαλονικ|thessalonik", loc):
                area_name, region, how = "Θεσσαλονίκη", "thessaloniki", "location"

        h = hints.get(url)
        if h and h["region"] and area_name in ("", "Θεσσαλονίκη") and region != "other":
            if h["region"] == "other":
                # the page names another region; only the listing's own title / link outweighs it
                if how != "listing":
                    region, area_name, how = "other", "", "page"
            else:
                region, area_name, how = "thessaloniki", h["area"] or area_name or "Θεσσαλονίκη", "page"
        nb = ""
        if region == "thessaloniki":
            nb, parent = neighbourhood(own, area_name)
            if not nb:
                nb, parent = neighbourhood(loc, area_name)
            if not nb and h and h.get("neighbourhood") and h["area"] == area_name:
                nb = OLD_NB.get(h["neighbourhood"], h["neighbourhood"])
                nb = nb if nb in districts.AREAS and districts.AREAS[nb]["district"] == area_name else ""
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
            # where the region comes from: listing (its title, link or place field), location (a bare
            # "Θεσσαλονίκη" in the place field), page (read again by refine_districts.py),
            # coordinates, agency (guessed from the agency's other listings)
            "region_how": how,
            "lat": r["lat"], "lon": r["lon"], "image": r["image"],
            "listing_date": ldate, "listing_date_kind": lkind, "first_seen": h["first_seen"],
            "scraped_at": r["scraped_at"],
            # last time the listing was read on its source with this price (empty: portals via alerts,
            # Telegram, and agency pages not re-read since the check began)
            "checked_at": r.get("checked_at", ""),
        })

    fill_from_coordinates(out)
    fill_from_agency(out)
    fill_map_point(out)

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


def office_point_sites(out):
    """Sites that give most of their listings the same point: that is their office, not the property."""
    by_site = {}
    for r in out:
        if r["lat"] and r["lon"]:
            by_site.setdefault(r["source_domain"], []).append((r["lat"], r["lon"]))
    return {d for d, pts in by_site.items() if len(pts) >= 5 and Counter(pts).most_common(1)[0][1] / len(pts) > 0.5}


def fill_map_point(out):
    """One point per listing for the map, with how precise it is (geo):
    site = the listing's own coordinates (some sites, e.g. RE/MAX, already blur them),
    area = centre of its area on Jeny Shir's map, district = centre of the coarse district.
    lat/lon stay as the site gave them."""
    office_like = office_point_sites(out)
    n = Counter()
    for r in out:
        r["map_lat"] = r["map_lon"] = r["geo"] = ""
        try:
            lat, lon = float(r["lat"]), float(r["lon"])
            own = r["source_domain"] not in office_like and 34 < lat < 42 and 19 < lon < 30
        except ValueError:
            own = False
        centre = (districts.AREAS.get(r["neighbourhood"]) or {}).get("centre")
        if own:
            r["map_lat"], r["map_lon"], r["geo"] = f"{lat:.5f}", f"{lon:.5f}", "site"
        elif centre:
            r["map_lat"], r["map_lon"], r["geo"] = f"{centre[0]:.5f}", f"{centre[1]:.5f}", "area"
        elif r["region"] == "thessaloniki" and r["area"] in CENTRES:
            c = CENTRES[r["area"]]
            r["map_lat"], r["map_lon"], r["geo"] = f"{c[0]:.5f}", f"{c[1]:.5f}", "district"
        n[r["geo"] or "none"] += 1
    print("map point:", dict(n))


def fill_from_coordinates(out):
    """Listings with coordinates but no district: nearest district centre (within ~4 km).
    Sites that give every listing the same point (their office) are ignored."""
    import math
    office_like = office_point_sites(out)
    moved = Counter()
    for r in out:
        if not (r["lat"] and r["lon"]) or r["source_domain"] in office_like or r["neighbourhood"]:
            continue
        try:
            lat, lon = float(r["lat"]), float(r["lon"])
        except ValueError:
            continue
        if r["region"] != "other" and not in_thessaloniki_unit(lat, lon):
            generic = r["region"] == "unknown" or (r["area"] in ("", "Θεσσαλονίκη") and r["region_how"] != "listing")
            if generic and 34 < lat < 42 and 19 < lon < 30:
                r["region"], r["area"], r["region_how"] = "other", "", "coordinates"  # somewhere else in Greece
                moved["region other"] += 1
            continue
        if r["region"] == "other":
            continue
        inside = districts.by_point(lat, lon)
        if inside and r["area"] in ("", "Θεσσαλονίκη", districts.AREAS[inside]["district"]):
            r["region"], r["area"], r["neighbourhood"] = "thessaloniki", districts.AREAS[inside]["district"], inside
            r["region_how"] = r["region_how"] or "coordinates"
            moved["map area"] += 1
            continue
        if r["area"] not in ("", "Θεσσαλονίκη"):
            continue  # the listing's text names another district: keep it
        name, (clat, clon) = min(CENTRES.items(), key=lambda c: (c[1][0] - lat) ** 2 + ((c[1][1] - lon) * 0.76) ** 2)
        km = math.hypot(clat - lat, (clon - lon) * 0.76) * 111
        r["region"] = "thessaloniki"
        r["region_how"] = r["region_how"] or "coordinates"
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
            r["region"], r["area"], r["region_how"] = "thessaloniki", "Θεσσαλονίκη", "agency"
            n += 1
    print("region from agency profile:", n)


def urlunquote(u):
    from urllib.parse import unquote
    return unquote(u)


if __name__ == "__main__":
    main()
