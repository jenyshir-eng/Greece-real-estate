"""Thessaloniki neighbourhoods from Jeny Shir's neighbourhood map
(https://jenyshir.com/ru/maps/thessaloniki/): boundaries, names and price benchmarks.

data/sources/thessaloniki_districts.geojson holds one polygon per map area (central
ones from the Municipality of Thessaloniki open data); each has the coarse Spiti Radar
district it belongs to and the map's average sale price and rent per m2.
"""
import json
import os
import re

import sys  # noqa: E402
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import city  # noqa: E402

# the city's map (data/sources of the current city folder); a city without one has no map areas
FILE = city.GEOJSON
_data = json.load(open(FILE, encoding="utf-8")) if os.path.exists(FILE) else {"features": [], "areas_without_polygon": []}
AREAS = {f["properties"]["id"]: f["properties"] for f in _data["features"] if "gr" in f["properties"]}
AREAS.update({p["id"]: p for p in _data["areas_without_polygon"]})

# names in listings (accent-free lowercase, final sigma as σ) -> map area id.
# Order matters: specific names before the ones they contain.
PATTERNS = [
    ("vardaris", r"βαρδαρ|vardar|πλατεια δημοκρατιασ"),
    ("lachanokipoi", r"λαχανοκηπ|lachanokip|\bφιξ\b|fix\b"),
    ("stathmos", r"σιδηροδρομικ|σταθμοσ|γιαννιτσων|δενδροποταμ|dendropotam|stathmos"),
    ("ladadika", r"λαδαδικ|ladadik"),
    ("paliaparalia", r"παλια παραλια|palia paralia|λεωφ\w*\.? νικησ|leof\w* nikis|λευκοσ πυργοσ|λευκου πυργου|white tower"),
    ("istoriko", r"αριστοτελουσ|aristotelous|ιστορικο κεντρο|historic cent"),
    ("agiasofia", r"αγια σοφια|αγιασ σοφιασ|agia sofia|ροτοντα|rotonda"),
    ("kamara", r"καμαρα|kamara|συντριβανι|sintrivani|syntrivani|πανεπιστημι|\bαπθ\b|\bδεθ\b"),
    ("anopoli", r"ανω πολη|ano poli|ακροπολη|επταπυργι|καστρα\b|kastra\b"),
    ("evangelistria", r"ευαγγελιστρι|evangelistri"),
    ("saranta", r"40 εκκλησιεσ|σαραντα εκκλησιεσ|saranta ekklisies"),
    ("agdimitrios", r"αγιοσ δημητριοσ|αγιου δημητριου|agios dimitrios"),
    ("dioikitirio", r"διοικητηρι|dioikitiri"),
    ("panagiafaneromeni", r"παναγια φανερωμενη|panagia faneromeni|π\.? ?φανερωμενη"),
    ("xirokrini", r"ξηροκρην|xirokrin"),
    ("triandria", r"τριανδρια|triandria"),
    ("neaparalia", r"νεα παραλια|nea paralia"),
    ("analipsi", r"αναληψη|analipsi|μποτσαρη|botsari"),
    ("depo", r"ντεπω|\bdepo\b"),
    ("faliro", r"φαληρο|faliro|ιπποκρατει|ippokratei"),
    ("charilaou", r"χαριλαου|charilaou|xarilaou"),
    ("katotoumpa", r"κατω τουμπα|kato toump|kato toumb"),
    ("anotoumpa", r"ανω τουμπα|ano toump|ano toumb"),
    ("neaelvetia", r"νεα ελβετια|nea elvetia|ν\.? ?ελβετια"),
    ("martiou", r"25ησ μαρτιου|μαρτιου|martiou"),
    ("voulgari", r"βουλγαρη|voulgari|κηφισια θεσσ|kifisia thess"),
    ("papafi", r"παπαφη|papafi"),
    ("malakopi", r"μαλακοπη|malakopi"),
    ("kalamaria", r"καλαμαρι|kalamari|αρετσου|aretsou|καραμπουρνακι|karampournaki|νεα κρηνη|nea krini"),
    ("pylaia", r"πυλαια|pylaia|pylea"),
    ("panorama", r"πανοραμα|panorama"),
    ("chortiatis", r"χορτιατ|chortiat|ασβεστοχωρι|asvestochori|εξοχη|φιλυρο"),
    ("perea", r"περαια|peraia|perea"),
    ("neoiepivates", r"νεοι επιβατεσ|neoi epivates|νεων επιβατων"),
    ("thermi", r"θερμη\b|thermi\b"),
    ("sykies", r"συκιε|sykie"),
    ("neapoli", r"νεαπολ|neapol"),
    ("pefka", r"\bπευκα\b|\bpefka\b|ρετζικι|retziki"),
    ("agpavlos", r"αγιοσ παυλοσ|agios pavlos"),
    ("stavroupoli", r"σταυρουπολ|stavroupol"),
    ("polichni", r"πολιχνη|polichni|polixni"),
    ("efkarpia", r"ευκαρπια|efkarpia"),
    ("kallithea", r"καλλιθεα ωραιοκαστρ|kallithea oraiokastr|καλλιθεα θεσσαλον"),
    ("oraiokastro", r"ωραιοκαστρ|oraiokastr|oreokastr"),
    ("mygdonia", r"μυγδονι|mygdoni|\bλητη|\bliti\b|δρυμοσ|drymos|μελισσοχωρι"),
    ("lagkadas", r"λαγκαδα|lagkada|langada"),
    ("evosmos", r"ευοσμ|evosm"),
    ("kordelio", r"κορδελι|kordeli|ελευθεριο|eleftherio"),
    ("menemeni", r"μενεμεν|menemen"),
    ("ampelokipoi", r"αμπελοκηπ|ampelokip"),
    ("echedoros", r"σινδοσ|sindos|καλοχωρι|kalochori|εχεδωρ"),
    ("chalastra", r"χαλαστρα|chalastra"),
    ("axios", r"κυμινα|kymina|μαλγαρα|malgara|αξιοσ\b"),
]
_compiled = [(i, re.compile(p)) for i, p in PATTERNS if i in AREAS]  # only areas of this city's map


def by_name(text, district=""):
    """First map area named in text that lies in the district (or any, for a generic one)."""
    for i, pat in _compiled:
        if pat.search(text) and (district in ("", city.GENERIC) or AREAS[i]["district"] == district):
            return i
    return ""


def _inside(lon, lat, ring):
    n, inside, j = len(ring), False, len(ring) - 1
    for k in range(n):
        xi, yi = ring[k][0], ring[k][1]
        xj, yj = ring[j][0], ring[j][1]
        if (yi > lat) != (yj > lat) and lon < (xj - xi) * (lat - yi) / ((yj - yi) or 1e-12) + xi:
            inside = not inside
        j = k
    return inside


def _in_geometry(lon, lat, g):
    polys = g["coordinates"] if g["type"] == "MultiPolygon" else [g["coordinates"]]
    for rings in polys:
        if rings and _inside(lon, lat, rings[0]) and not any(_inside(lon, lat, h) for h in rings[1:]):
            return True
    return False


def _size(g):
    polys = g["coordinates"] if g["type"] == "MultiPolygon" else [g["coordinates"]]
    return sum(abs(sum(x1 * y2 - x2 * y1 for (x1, y1, *_), (x2, y2, *_) in zip(r[0], r[0][1:] + r[0][:1]))) for r in polys if r)


def by_point(lat, lon):
    """Map area containing the point. Where areas overlap, the map's own areas win over the
    municipal ones (as drawn on the map, e.g. Vardaris over Xirokrini), then the smallest."""
    hits = [f for f in _data["features"] if _in_geometry(lon, lat, f["geometry"])]
    hits.sort(key=lambda f: (bool(f["properties"].get("official")), _size(f["geometry"])))
    for f in hits:
        p = f["properties"]
        if "split" in p:  # shared coastal polygon: nearest centre
            return min(p["split"], key=lambda i: (AREAS[i]["centre"][0] - lat) ** 2 + (AREAS[i]["centre"][1] - lon) ** 2)
        return p["id"]
    return ""
