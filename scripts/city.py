"""The city a Spiti Radar run is for.

Every script works on the data folder of the current directory (data/listings, data/sources).
Thessaloniki lives at the repository root; other cities have their own folder with the same
layout (cities/athens: data/ of its own, scripts/ and web/ link to the shared ones), so the same
code serves both: run the pipeline from the city's folder.

data/sources/city.json describes the city; anything it leaves out falls back to Thessaloniki.
"""
import json
import os
import re

_FILE = "data/sources/city.json"
_cfg = json.load(open(_FILE, encoding="utf-8")) if os.path.exists(_FILE) else {}

KEY = _cfg.get("key", "thessaloniki")            # region value of listings in this city
NAME_RU = _cfg.get("name_ru", "Салоники")
NAME_RU_GEN = _cfg.get("name_ru_gen", "Салоник")  # "агентств Салоник"
GENERIC = _cfg.get("generic", "Θεσσαλονίκη")     # district value when only the city is known
GENERIC_RE = _cfg.get("generic_re", r"θεσσαλονικ|thessalonik")
REGISTRY = _cfg.get("registry", "data/sources/agencies_thessaloniki.csv")
AGENCY_LISTINGS = _cfg.get("agency_listings", "data/listings/listings_thessaloniki.csv")
GEOJSON = _cfg.get("geojson", "data/sources/thessaloniki_districts.geojson")
SITE_URL = _cfg.get("site_url", "https://radar.jenyshir.com")
MAP_URL = _cfg.get("map_url", "https://jenyshir.com/ru/maps/thessaloniki/")
SCHEDULE = [tuple(x) for x in _cfg.get("schedule", [[10, 13], [18, 43]])]  # update starts, Europe/Athens
REMAX_AREAS = _cfg.get("remax_areas", ["108", "109"])
XE_POSTAL = tuple(_cfg.get("xe_postal_prefixes", ["54", "55", "56", "570", "571", "572"]))
VRISKO_AREAS = _cfg.get("vrisko_areas", [
    "thessalonikis", "thessaloniki", "kalamaria", "pylaia", "thermi", "neapoli", "evosmos", "stavroupoli", "peraia",
    "oraiokastro", "panorama", "sykies", "ampelokipoi", "polichni", "epanomi", "michaniona", "chalastra", "sindos",
    "lagkadas"])
KTIMATO_PLACE = _cfg.get("ktimato_place")          # None: the Thessaloniki pattern in the collector
KTIMATO_REGIONS = tuple(_cfg.get("ktimato_regions", ["thessaloniki", "halkidiki", "chalkidiki"]))
TELEGRAM_TITLE = _cfg.get("telegram_title", "")    # prefix of the Telegram messages ("Афины")
# [[name, pattern], ...] districts of the city, most specific first (None: the Thessaloniki list in normalize)
AREAS = [tuple(a) for a in _cfg["areas"]] if "areas" in _cfg else None
OTHER_REGIONS = _cfg.get("other_regions")           # None: the Thessaloniki list in normalize
CENTRES = {k: tuple(v) for k, v in _cfg["centres"].items()} if "centres" in _cfg else None
AREA_RU = _cfg.get("area_ru")                       # for the page and Telegram (None: Thessaloniki tables)
AREA_WORDS = _cfg.get("area_words")
BOX = _cfg.get("box")                               # [lat_min, lat_max, lon_min, lon_max] of the region
MAP_BOX = _cfg.get("map_box")                       # city view of the map tab
EXAMPLES = _cfg.get("examples")


def in_unit(lat, lon):
    """Inside the region the city covers (rough outline)."""
    if BOX is None:
        if not (40.40 <= lat <= 41.10 and 22.50 <= lon <= 23.80):
            return False
        return lon <= 23.20 or lat >= 40.55  # the south-east corner is Halkidiki
    la0, la1, lo0, lo1 = BOX
    return la0 <= lat <= la1 and lo0 <= lon <= lo1 and not any(
        a <= lat <= b and c <= lon <= d for a, b, c, d in _cfg.get("box_exclude", []))


def generic_in(text):
    return bool(re.search(GENERIC_RE, text or ""))
