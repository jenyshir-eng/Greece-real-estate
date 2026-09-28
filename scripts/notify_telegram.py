"""Morning Telegram message: new properties that match saved filters.

Filters: data/sources/notify_filters.json (list of named filters, see the file).
Bot:     environment variable TELEGRAM_BOT_TOKEN (from @BotFather; never in the repo).
Chat:    TELEGRAM_CHAT_ID, or found automatically from the last /start sent to the bot
         and remembered in data/sources/notify_chat.json.
State:   data/listings/notified.txt - listing URLs already sent (one property is sent once,
         even when it is on several sites). The first run only records what exists today.

Usage: python3 scripts/notify_telegram.py [--dry-run]
"""
import argparse
import csv
import json
import os
import re
import sys
import urllib.parse
import urllib.request
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import districts  # noqa: E402

LISTINGS = "data/listings/listings_normalized.csv"
FILTERS = "data/sources/notify_filters.json"
CHAT_FILE = "data/sources/notify_chat.json"
STATE = "data/listings/notified.txt"
SEARCH_URL = "https://claude.ai/artifact/2dfMzvjzzr22jEgLE1HnhG"
MAX_ITEMS = 25
TYPE_RU = {"apartment": "квартира", "studio": "студия", "maisonette": "мезонет", "house": "дом", "land": "участок",
           "store": "магазин", "office": "офис", "warehouse": "склад", "building": "здание", "hotel": "гостиница",
           "parking": "парковка", "": "объект"}
DISTRICT_RU = {"Καλαμαριά": "Каламария", "Πυλαία": "Пилея", "Πανόραμα": "Панорама", "Θέρμη": "Терми",
               "Χορτιάτης": "Хортиатис", "Θερμαϊκός": "Термаикос", "Νεάπολη-Συκιές": "Неаполи и Сикиес",
               "Παύλος Μελάς": "Павлос Мелас", "Κορδελιό-Εύοσμος": "Корделио и Эвосмос",
               "Αμπελόκηποι-Μενεμένη": "Амбелокипи и Менемени", "Ωραιόκαστρο": "Ореокастро", "Δέλτα": "Дельта",
               "Λαγκαδάς": "Лангадас", "Χαλκηδόνα": "Халкидона", "Βόλβη": "Волви",
               "Θεσσαλονίκη-Ανατολικά": "Салоники, восток", "Θεσσαλονίκη-Κέντρο": "Салоники, центр",
               "Θεσσαλονίκη": "Салоники"}
PORTAL = {"xe.gr": "XE", "spitogatos.gr": "Spitogatos", "spiti24.gr": "Spiti24", "tospitimou.gr": "Tospitimou",
          "plot.gr": "Plot", "indomio.gr": "Indomio", "t.me": "Telegram"}


def floor_level(s):
    t = (s or "").lower()
    if re.search(r"ημιυπ", t):
        return -1
    if re.search(r"υπόγ|υπογ|basement", t):
        return -2
    if re.search(r"ημιόρ|ημιορ|ημιώρ|υπερυψ", t):
        return 0.5
    if re.search(r"ισόγ|ισογ|ground", t):
        return 0
    m = re.match(r"-?\d+", t.strip())
    if not m:
        return None
    n = int(m.group(0))
    return -2 if n < 0 else (n if n <= 12 else None)


def num(x):
    try:
        return float(x) if x not in ("", None) else None
    except ValueError:
        return None


def properties():
    groups = defaultdict(list)
    for r in csv.DictReader(open(LISTINGS, encoding="utf-8")):
        groups[r.get("property_id") or r["url"]].append(r)
    for members in groups.values():
        # main link: agency site first, then the newest dated listing
        members.sort(key=lambda r: (r.get("source_kind") != "portal", r.get("listing_date", "")), reverse=True)
        yield members


def summary(members):
    r = members[0]
    first = lambda k: next((m[k] for m in members if m.get(k)), "")
    prices = [num(m["price_eur"]) for m in members if num(m["price_eur"])]
    nb = first("neighbourhood")
    area = districts.AREAS[nb]["district"] if nb in districts.AREAS else first("area")
    return {"url": r["url"], "urls": {m["url"] for m in members}, "tx": r["transaction"], "type": first("type"),
            "price": min(prices) if prices else None, "m2": num(first("area_m2")), "region": r["region"],
            "area": area, "nb": nb, "floor": floor_level(first("floor")), "beds": num(first("bedrooms")),
            "sites": len(members), "source": PORTAL.get(r["source_domain"], r["agency"])}


def matches(p, f):
    if f.get("transaction") and p["tx"] != f["transaction"]:
        return False
    if f.get("region", "thessaloniki") and p["region"] != f.get("region", "thessaloniki"):
        return False
    if f.get("types") and p["type"] not in f["types"]:
        return False
    places = f.get("areas") or []
    if places and not (p["area"] in places or p["nb"] in places):
        return False
    for key, val, lo in (("price_min", p["price"], True), ("price_max", p["price"], False),
                         ("m2_min", p["m2"], True), ("m2_max", p["m2"], False),
                         ("bedrooms_min", p["beds"], True), ("floor_min", p["floor"], True), ("floor_max", p["floor"], False)):
        if f.get(key) is None:
            continue
        if val is None:
            if not f.get("keep_unknown", True) or key.startswith("price"):
                return False
            continue
        if (lo and val < f[key]) or (not lo and val > f[key]):
            return False
    return True


def vs_market(p):
    a = districts.AREAS.get(p["nb"])
    if not a or not p["price"] or not p["m2"] or p["type"] not in ("apartment", "studio", "maisonette"):
        return ""
    ref = a.get("sale") if p["tx"] == "sale" else a.get("rent") if p["tx"] == "rent" else None
    if not ref:
        return ""
    pct = round((p["price"] / p["m2"] / ref - 1) * 100)
    return "" if abs(pct) < 10 or abs(pct) > 60 else f" ({'+' if pct > 0 else '−'}{abs(pct)}% к средней по району)"


def floor_ru(n):
    return {-2: "подвал", -1: "полуподвал", 0: "ισόγειο", 0.5: "полуэтаж"}.get(n, f"{n}-й эт." if n is not None else "")


def line(p):
    place = districts.AREAS[p["nb"]]["ru"] if p["nb"] in districts.AREAS else DISTRICT_RU.get(p["area"], p["area"] or "Салоники")
    bits = [f"{TYPE_RU.get(p['type'], 'объект')} {int(p['m2'])} м²" if p["m2"] else TYPE_RU.get(p["type"], "объект"),
            floor_ru(p["floor"])]
    price = f"{int(p['price']):,}".replace(",", " ") + (" €/мес" if p["tx"] == "rent" else " €") if p["price"] else "цена по запросу"
    extra = f", на {p['sites']} сайтах" if p["sites"] > 1 else ""
    return (f"• <b>{html_escape(place)}</b>, {', '.join(b for b in bits if b)} — <b>{price}</b>{vs_market(p)}{extra}\n"
            f"  <a href=\"{html_escape(p['url'])}\">{html_escape(p['source'] or 'объявление')}</a>")


def html_escape(s):
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def api(token, method, **params):
    data = urllib.parse.urlencode(params).encode()
    with urllib.request.urlopen(f"https://api.telegram.org/bot{token}/{method}", data=data, timeout=30) as r:
        return json.loads(r.read().decode())


def chat_id(token):
    if os.environ.get("TELEGRAM_CHAT_ID"):
        return os.environ["TELEGRAM_CHAT_ID"]
    if os.path.exists(CHAT_FILE):
        return json.load(open(CHAT_FILE))["chat_id"]
    # the owner pressed Start in the bot: take that chat and remember it
    upd = api(token, "getUpdates").get("result", [])
    chats = [u["message"]["chat"]["id"] for u in upd if "message" in u and u["message"].get("chat", {}).get("type") == "private"]
    if not chats:
        return None
    json.dump({"chat_id": chats[-1]}, open(CHAT_FILE, "w"))
    return chats[-1]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="print the message, send nothing, change nothing")
    a = ap.parse_args()
    filters = [f for f in json.load(open(FILTERS, encoding="utf-8"))["filters"] if f.get("enabled", True)]
    sent = set(open(STATE, encoding="utf-8").read().split()) if os.path.exists(STATE) else None
    props = [summary(m) for m in properties()]
    all_urls = {u for p in props for u in p["urls"]}
    if sent is None and not a.dry_run:
        # first run: remember everything that exists today, send nothing old, say hello
        token = os.environ.get("TELEGRAM_BOT_TOKEN")
        chat = chat_id(token) if token else None
        if not chat:
            print("first run: bot token or chat missing, nothing recorded yet", file=sys.stderr)
            return
        names = "\n".join("• " + html_escape(f["name"]) for f in filters)
        api(token, "sendMessage", chat_id=chat, parse_mode="HTML", disable_web_page_preview="true",
            text=f"✅ <b>Spiti Radar</b>: рассылка подключена.\nКаждое утро после сбора пришлю новые объекты по условиям:\n{names}")
        open(STATE, "w", encoding="utf-8").write("\n".join(sorted(all_urls)) + "\n")
        print(f"first run: {len(all_urls)} listings recorded, hello sent", file=sys.stderr)
        return
    new = [p for p in props if not (p["urls"] & (sent or set()))]
    parts = []
    for f in filters:
        hits = sorted((p for p in new if matches(p, f)), key=lambda p: p["price"] or 1e12)
        if not hits:
            continue
        parts.append(f"<b>{html_escape(f['name'])}</b>: {len(hits)} новых\n" +
                     "\n".join(line(p) for p in hits[:MAX_ITEMS]) +
                     (f"\n…и ещё {len(hits) - MAX_ITEMS} — в поиске" if len(hits) > MAX_ITEMS else ""))
    text = ("🏠 <b>Spiti Radar</b>: новое за сутки\n\n" + "\n\n".join(parts) +
            f"\n\n<a href=\"{SEARCH_URL}\">Открыть поиск</a>") if parts else ""
    if a.dry_run:
        print(text or f"(nothing new for the filters; {len(new)} new properties overall)")
        return
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        print("TELEGRAM_BOT_TOKEN not set: nothing sent", file=sys.stderr)
        return
    chat = chat_id(token)
    if not chat:
        print("no chat yet: open the bot in Telegram and press Start", file=sys.stderr)
        return
    if text:
        # Telegram limit is 4096 characters per message
        chunk = ""
        for block in text.split("\n\n"):
            if len(chunk) + len(block) > 3800:
                api(token, "sendMessage", chat_id=chat, text=chunk, parse_mode="HTML", disable_web_page_preview="true")
                chunk = ""
            chunk += ("\n\n" if chunk else "") + block
        if chunk:
            api(token, "sendMessage", chat_id=chat, text=chunk, parse_mode="HTML", disable_web_page_preview="true")
    open(STATE, "w", encoding="utf-8").write("\n".join(sorted(all_urls | (sent or set()))) + "\n")
    print(f"sent: {sum(1 for _ in parts)} filter blocks; {len(new)} new properties overall", file=sys.stderr)


if __name__ == "__main__":
    main()
