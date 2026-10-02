"""Telegram message after each update: new properties and price drops that match the saved
filters, and a short report of the run (new / removed listings, price moves, source errors).

Filters: data/sources/notify_filters.json (list of named filters, see the file).
Bot:     environment variable TELEGRAM_BOT_TOKEN (from @BotFather; never in the repo).
Chat:    TELEGRAM_CHAT_ID, or found automatically from the last /start sent to the bot
         and remembered in data/listings/notify_chat.json.
State:   data/listings/notified.txt - listing URLs already sent (one property is sent once,
         even when it is on several sites). The first run only records what exists today.
         data/listings/notified_drops.txt - "url<TAB>price" of price drops already sent.
Delivery: every message is checked (Telegram answers ok + message_id); data/listings/notify_log.csv
         keeps one line per run. State files change only when every message was delivered.
Size:    Telegram takes at most 4096 characters per message; messages are packed by whole
         listings up to LIMIT, an oversized single piece is cut as plain text.

Usage: python3 scripts/notify_telegram.py [--dry-run]
"""
import argparse
import csv
import datetime
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import city  # noqa: E402
import districts  # noqa: E402

LISTINGS = "data/listings/listings_normalized.csv"
FILTERS = "data/sources/notify_filters.json"
CHAT_FILE = "data/listings/notify_chat.json"  # committed with the daily data
STATE = "data/listings/notified.txt"
DROP_STATE = "data/listings/notified_drops.txt"
HISTORY = "data/listings/price_history.csv"
REPORT = "data/listings/update_report.json"
LOG = "data/listings/notify_log.csv"
SEARCH_URL = city.SITE_URL
TITLE = "Spiti Radar" + (" · " + city.TELEGRAM_TITLE if city.TELEGRAM_TITLE else "")  # which city the message is about
MAX_ITEMS = 25
LIMIT = 3900          # characters per message (Telegram: 4096), counted in UTF-16 units like Telegram
DROP_DAYS = 3         # price drops newer than this are sent
DROP_MIN, DROP_MAX = 0.01, 0.5  # smaller is noise, larger is a parsing slip
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
if city.AREA_RU is not None:
    DISTRICT_RU = city.AREA_RU
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
    return {"url": r["url"], "urls": {m["url"] for m in members}, "members": members, "tx": r["transaction"], "type": first("type"),
            "price": min(prices) if prices else None, "m2": num(first("area_m2")), "region": r["region"],
            "area": area, "nb": nb, "floor": floor_level(first("floor")),
            # the region is confirmed when a listing of the group names the place itself (title, link,
            # place field, the page read again, its map point), not only guessed from the agency
            "region_ok": any(m.get("region_how") in ("listing", "page", "coordinates") or
                             m.get("area") not in ("", city.GENERIC) for m in members), "beds": num(first("bedrooms")),
            "sites": len(members), "source": PORTAL.get(r["source_domain"], r["agency"])}


def matches(p, f):
    if f.get("transaction") and p["tx"] != f["transaction"]:
        return False
    if f.get("region", city.KEY) and p["region"] != f.get("region", city.KEY):
        return False
    if f.get("region", city.KEY) and not p["region_ok"] and not f.get("keep_unconfirmed_region"):
        return False  # e.g. a Veria flat of a Thessaloniki agency whose page we could not place yet
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
            keep = f.get("keep_unknown", True)
            if key.startswith("floor"):
                keep = f.get("keep_unknown_floor", keep)
            if not keep or key.startswith("price"):
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
    return {-2: "подвал", -1: "полуподвал", 0: "цокольный (ισόγειο)", 0.5: "полуэтаж"}.get(n, f"{n}-й эт." if n is not None else "")


def line(p):
    place = districts.AREAS[p["nb"]]["ru"] if p["nb"] in districts.AREAS else DISTRICT_RU.get(p["area"], p["area"] or city.NAME_RU)
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
    try:
        with urllib.request.urlopen(f"https://api.telegram.org/bot{token}/{method}", data=data, timeout=30) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        # Telegram explains refusals in the body: {"ok": false, "error_code": 400, "description": "..."}
        try:
            return json.loads(e.read().decode())
        except ValueError:
            return {"ok": False, "error_code": e.code, "description": str(e)}


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


def tg_len(s):
    """Length as Telegram counts it (UTF-16 code units: an emoji counts 2)."""
    return len(s.encode("utf-16-le")) // 2


def plain_cut(s, limit):
    """An oversized piece: tags removed, cut to the limit without breaking an &entity;."""
    t = re.sub(r"<[^>]+>", "", s)
    while tg_len(t) > limit - 1:
        t = t[:-max(1, (tg_len(t) - limit + 1) // 2)]
        t = re.sub(r"&[a-z#0-9]*$", "", t)
    return t + "…"


def pack(blocks, limit=LIMIT):
    """blocks: [(title, [piece, ...])]. Pieces are whole HTML fragments (one listing each) and are
    never split between messages; a block continued in the next message repeats its title.
    Every message is at most `limit` characters."""
    msgs, cur = [], ""
    for title, pieces in blocks:
        for i, piece in enumerate([title] + pieces if title else pieces):
            if tg_len(piece) > limit:
                piece = plain_cut(piece, limit)
            sep = "" if not cur else ("\n\n" if i == 0 else "\n")
            if tg_len(cur + sep + piece) <= limit:
                cur += sep + piece
                continue
            if cur:
                msgs.append(cur)
            cont = f"{title} (продолжение)" if title and i > 0 else ""
            cur = cont + "\n" + piece if cont and tg_len(cont + "\n" + piece) <= limit else piece
    if cur:
        msgs.append(cur)
    return msgs


def send(token, chat, msgs):
    """Sends each message, checks Telegram's answer. Returns (delivered, errors)."""
    delivered, errors = 0, []
    for text in msgs:
        for attempt in range(3):
            r = api(token, "sendMessage", chat_id=chat, text=text, parse_mode="HTML", disable_web_page_preview="true")
            if r.get("ok"):
                delivered += 1
                break
            desc = r.get("description", "")
            if r.get("error_code") == 429:  # too many requests: wait as told
                time.sleep(min(60, (r.get("parameters") or {}).get("retry_after", 5)))
                continue
            if r.get("error_code") == 400 and "parse" in desc.lower():
                text = re.sub(r"<[^>]+>", "", text)  # bad markup: send the words without it
                r2 = api(token, "sendMessage", chat_id=chat, text=text, disable_web_page_preview="true")
                if r2.get("ok"):
                    delivered += 1
                    break
                desc = r2.get("description", desc)
            errors.append(f"{r.get('error_code')}: {desc}"[:200])
            break
        else:
            errors.append("429: still too many requests")
        time.sleep(0.5)
    return delivered, errors


def log_delivery(n_msgs, delivered, errors, note):
    new = not os.path.exists(LOG)
    with open(LOG, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if new:
            w.writerow(["at", "messages", "delivered", "errors", "note"])
        w.writerow([datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%MZ"), n_msgs, delivered, " | ".join(errors), note])


def load_history():
    hist = {}
    if os.path.exists(HISTORY):
        for r in csv.DictReader(open(HISTORY, encoding="utf-8")):
            hist.setdefault(r["url"], []).append((r["date"], int(r["price_eur"])))
    return hist


def price_drop(p, hist, since):
    """The latest recent price drop among the property's listings: (url, old, new, date) or None."""
    best = None
    for m in p["members"]:
        h = hist.get(m["url"]) or []
        if len(h) < 2 or h[-1][0] < since:
            continue
        old, new = h[-2][1], h[-1][1]
        if DROP_MIN <= (old - new) / old <= DROP_MAX and (best is None or new < best[2]):
            best = (m["url"], old, new, h[-1][0])
    return best


def money(v, tx):
    return f"{int(v):,}".replace(",", " ") + (" €/мес" if tx == "rent" else " €")


def drop_line(p, d):
    url, old, new, _ = d
    pct = round((old - new) / old * 100, 1)
    m = next(m for m in p["members"] if m["url"] == url)
    q = dict(p, url=url, price=new, source=PORTAL.get(m["source_domain"], m["agency"]))  # the link is the dropped one
    text = line(q).replace(f"<b>{money(new, p['tx'])}</b>",
                           f"<b>{money(new, p['tx'])}</b> (было {money(old, p['tx'])}, −{str(pct).replace('.', ',')}%)", 1)
    return text


def report_text():
    """Short report of the last update run, from update_report.json."""
    if not os.path.exists(REPORT):
        return ""
    r = json.load(open(REPORT, encoding="utf-8"))
    t = r["totals"]
    fmt = lambda n: f"{n:,}".replace(",", " ")
    at = r["at"]
    lines = [f"📊 <b>Обновление {at[8:10]}.{at[5:7]} {at[11:16]} UTC</b>: в базе {fmt(t['listings'])} объявлений",
             f"новых {fmt(t['new'])}, снято {fmt(t['removed'])}, подешевели {fmt(t['down'])}, подорожали {fmt(t['up'])}, "
             f"перепроверено сегодня {fmt(t['checked'])}"]
    names = {"alerts": "письма порталов", "telegram": "Telegram-каналы", "remax": "RE/MAX", "ktimatoemporiki": "Ktimatoemporiki", "xe": "XE (страницы агентств)",
             "agencies": "сайты агентств", "normalize": "обработка", "districts": "уточнение районов",
             "normalize2": "обработка", "group": "склейка дублей"}
    if t["failed_steps"]:
        lines.append("⚠️ Не сработали: " + ", ".join(dict.fromkeys(names.get(s, s) for s in t["failed_steps"])))
    errs = [s[0] for s in r["sources"] if s[7]]
    if errs:
        lines.append(f"⚠️ Не ответили {len(errs)} {'сайт' if len(errs) == 1 else 'сайтов'}: " + ", ".join(errs[:6]) +
                     ("…" if len(errs) > 6 else ""))
    mins = round(sum(s[1] for s in r["steps"]) / 60)
    if mins:
        lines.append(f"Сбор занял {mins} мин. Подробно — вкладка «Источники».")
    return "\n".join(html_escape(x).replace("&lt;b&gt;", "<b>").replace("&lt;/b&gt;", "</b>") for x in lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="print the messages, send nothing, change nothing")
    a = ap.parse_args()
    filters = [f for f in json.load(open(FILTERS, encoding="utf-8"))["filters"] if f.get("enabled", True)]
    sent = set(open(STATE, encoding="utf-8").read().split()) if os.path.exists(STATE) else None
    drops_sent = set(open(DROP_STATE, encoding="utf-8").read().splitlines()) if os.path.exists(DROP_STATE) else set()
    props = [summary(m) for m in properties()]
    all_urls = {u for p in props for u in p["urls"]}
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if sent is None and not a.dry_run:
        # first run: remember everything that exists today, send nothing old, say hello
        chat = chat_id(token) if token else None
        if not chat:
            print("first run: bot token or chat missing, nothing recorded yet", file=sys.stderr)
            return
        names = "\n".join("• " + html_escape(f["name"]) for f in filters)
        ok, errors = send(token, chat, [f"✅ <b>{TITLE}</b>: рассылка подключена.\nПосле каждого сбора пришлю новые объекты "
                                        f"и снижения цен по условиям:\n{names}"])
        log_delivery(1, ok, errors, "hello")
        if ok:
            open(STATE, "w", encoding="utf-8").write("\n".join(sorted(all_urls)) + "\n")
        print(f"first run: {len(all_urls)} listings recorded, hello {'sent' if ok else 'NOT sent: ' + '; '.join(errors)}",
              file=sys.stderr)
        return
    new = [p for p in props if not (p["urls"] & (sent or set()))]
    hist = load_history()
    since = (datetime.date.today() - datetime.timedelta(days=DROP_DAYS)).isoformat()
    new_ids = {id(p) for p in new}
    blocks, new_drops, n_new, n_drop = [(f"🏠 <b>{TITLE}</b>: новое с прошлого обновления", [])], set(), 0, 0
    for f in filters:
        hits = sorted((p for p in new if matches(p, f)), key=lambda p: p["price"] or 1e12)
        if hits:
            n_new += len(hits)
            blocks.append((f"<b>{html_escape(f['name'])}</b>: {len(hits)} новых",
                           [line(p) for p in hits[:MAX_ITEMS]] +
                           ([f"…и ещё {len(hits) - MAX_ITEMS} — в поиске"] if len(hits) > MAX_ITEMS else [])))
        drops = []
        for p in props:
            if id(p) in new_ids or not matches(p, f):
                continue
            d = price_drop(p, hist, since)
            if d and f"{d[0]}\t{d[2]}" not in drops_sent:
                drops.append((p, d))
        if drops:
            n_drop += len(drops)
            drops.sort(key=lambda x: (x[1][2] - x[1][1]) / x[1][1])  # the biggest drop first
            new_drops |= {f"{d[0]}\t{d[2]}" for _, d in drops}
            blocks.append((f"📉 <b>{html_escape(f['name'])}</b>: снизили цену {len(drops)}",
                           [drop_line(p, d) for p, d in drops[:MAX_ITEMS]] +
                           ([f"…и ещё {len(drops) - MAX_ITEMS}"] if len(drops) > MAX_ITEMS else [])))
    if len(blocks) == 1:
        blocks = []
    rep = report_text()
    if rep:
        blocks.append(("", [rep]))
    blocks.append(("", [f"<a href=\"{SEARCH_URL}\">Открыть поиск</a>"]))
    msgs = pack(blocks)
    if a.dry_run:
        for i, m in enumerate(msgs, 1):
            print(f"--- message {i}/{len(msgs)}, {tg_len(m)} characters ---\n{m}")
        print(f"({n_new} new, {n_drop} price drops for the filters; {len(new)} new properties overall)")
        return
    if not token:
        print("TELEGRAM_BOT_TOKEN not set: nothing sent", file=sys.stderr)
        return
    chat = chat_id(token)
    if not chat:
        print("no chat yet: open the bot in Telegram and press Start", file=sys.stderr)
        return
    delivered, errors = send(token, chat, msgs)
    log_delivery(len(msgs), delivered, errors, f"{n_new} new, {n_drop} drops")
    if delivered < len(msgs):
        # nothing is marked as sent: the next run sends it again
        print(f"Telegram: {delivered}/{len(msgs)} messages delivered; errors: {'; '.join(errors)}", file=sys.stderr)
        sys.exit(1)
    open(STATE, "w", encoding="utf-8").write("\n".join(sorted(all_urls | (sent or set()))) + "\n")
    if new_drops:
        open(DROP_STATE, "w", encoding="utf-8").write("\n".join(sorted(drops_sent | new_drops)) + "\n")
    print(f"Telegram: {delivered}/{len(msgs)} messages delivered; {n_new} new, {n_drop} price drops for the filters; "
          f"{len(new)} new properties overall", file=sys.stderr)


if __name__ == "__main__":
    main()
