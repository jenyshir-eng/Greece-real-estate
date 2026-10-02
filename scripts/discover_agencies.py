"""Weekly search for new agencies and a second look at sites that did not work.

1. Directories: vrisko.gr (Thessaloniki areas) and xe.gr agency profiles (postal codes of the
   Thessaloniki prefecture), with the existing collectors.
2. Agencies not yet in data/sources/agencies_thessaloniki.csv (matched by site domain,
   directory link, or name) are added; their sites are checked (reachable, robots.txt,
   listings), so working ones enter the daily collection the same day.
3. Registry sites that were blocked / unreachable / erroring are checked again: sites come
   back, change hosting or drop their bot wall.
   New agencies without a site in the directory: a site is looked for by domain guessing from
   the transliterated name (name.gr, namerealestate.gr, ...); a guess counts only when the page
   names the agency and looks like a real estate site.
4. data/sources/discovery_log.csv gets one line per run; the summary goes to Telegram.

Usage: python3 scripts/discover_agencies.py [--no-directories] [--no-recheck] [--dry-run]
"""
import argparse
import csv
import datetime
import os
import re
import subprocess
import sys
import tempfile
import urllib.parse
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from check_agency_sites import check  # noqa: E402
from normalize_listings import plain  # noqa: E402

import city  # noqa: E402

REGISTRY = city.REGISTRY
LOG = "data/sources/discovery_log.csv"
VRISKO_AREAS = city.VRISKO_AREAS
RECHECK = ("unreachable", "error", "bot_check", "http_")
NAME_NOISE = r"\b(μεσιτικο|μεσιτικα|γραφειο|γραφεια|κτηματομεσιτικο|κτηματομεσιτικη|real|estate|realestate|properties|" \
             r"property|ακινητα|ακινητων|συμβουλοι|ικε|επε|οε|εε|ae|ike|ltd|group|the)\b"


def name_key(s):
    s = plain(re.sub(r"\(.*?\)", " ", s or ""))
    s = re.sub(NAME_NOISE, " ", re.sub(r"[^\w\s]", " ", s))
    return " ".join(s.split())


def domain(url):
    host = urllib.parse.urlparse(url if "//" in (url or "") else "https://" + (url or "")).netloc.lower()
    return host.removeprefix("www.")


GREEK = dict(zip("αβγδεζηθικλμνξοπρσςτυφχψω", ["a", "v", "g", "d", "e", "z", "i", "th", "i", "k", "l", "m", "n", "x", "o",
                                                   "p", "r", "s", "s", "t", "y", "f", "ch", "ps", "o"]))
REAL_ESTATE = re.compile(r"ακίνητ|ακινητ|μεσιτ|real estate|properties|πώληση|ενοικίαση|πωληση|ενοικιαση", re.I)


def latin(s):
    return "".join(GREEK.get(c, c) for c in plain(s))


def site_guesses(name):
    words = [w for w in re.findall(r"[a-z0-9]+", latin(re.sub(r"\(.*?\)", " ", name)))
             if len(w) > 1 and not re.fullmatch(NAME_NOISE.replace("\\b", "").strip("()"), w)]
    words = [w for w in words if w not in ("mesitiko", "grafeio", "real", "estate", "ike", "oe", "ee", "epe", "ae")]
    if not words:
        return []
    joined, first = "".join(words[:3]), words[0]
    stems = [joined, "-".join(words[:3]), first]
    # Greek ου is written "ou" in most domains (papadopoulos), υ alone "y" or "i"
    stems = list(dict.fromkeys(x for st in stems for x in (st.replace("oy", "ou"), st)))
    out = []
    for st in stems:
        if len(st) < 4:
            continue
        for tpl in ("{}.gr", "{}.com", "{}realestate.gr", "{}-realestate.gr", "{}.com.gr", "{}estate.gr"):
            out.append("https://" + tpl.format(st))
    return list(dict.fromkeys(out))[:14]


def find_site(row):
    """First guessed domain that answers, names the agency and is about real estate."""
    import urllib.request
    key = [w for w in latin(name_key(row["name"])).split() if len(w) >= 4] + \
          [w for w in name_key(row["name"]).split() if len(w) >= 4]
    if not key:
        return ""
    for url in site_guesses(row["name"]):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 SpitiRadar/0.1 (+https://spitiradar.gr/opt-out)"})
            page = urllib.request.urlopen(req, timeout=12).read(400_000).decode("utf-8", "replace")
        except Exception:
            continue
        low = plain(page)
        if REAL_ESTATE.search(page) and any(k in low or k in latin(page[:200000]) for k in key):
            return url
    return ""


def run(cmd):
    print("+", " ".join(cmd), file=sys.stderr)
    return subprocess.run(cmd, stderr=sys.stderr).returncode == 0


def directories(tmp):
    """-> list of candidate dicts: name, website, street, locality, postal_code, lat, lon, vrisko_url, xe_url, found_via."""
    out = []
    vr = os.path.join(tmp, "vrisko.csv")
    if run([sys.executable, "scripts/collect_vrisko_agencies.py", vr] + VRISKO_AREAS) and os.path.exists(vr):
        for r in csv.DictReader(open(vr, encoding="utf-8")):
            out.append(dict(r, found_via="vrisko.gr (weekly)"))
    xe = os.path.join(tmp, "xe.csv")
    if run([sys.executable, "scripts/collect_xe_agencies.py", xe] + list(city.XE_POSTAL)) and os.path.exists(xe):
        for r in csv.DictReader(open(xe, encoding="utf-8")):
            out.append({"name": r["name"], "website": "", "street": r["address"], "postal_code": r["postal_code"],
                        "xe_url": r["xe_url"], "found_via": "xe.gr (weekly)"})
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-directories", action="store_true", help="skip the directories (recheck only)")
    ap.add_argument("--no-recheck", action="store_true", help="skip the second look at broken sites")
    ap.add_argument("--dry-run", action="store_true", help="change nothing, send nothing")
    a = ap.parse_args()
    reg = list(csv.DictReader(open(REGISTRY, encoding="utf-8")))
    fields = list(reg[0].keys())
    known_dom = {d for r in reg for d in (r["domain"], domain(r["website"]), domain(r["final_url"])) if d}
    known_url = {u for r in reg for u in (r.get("vrisko_url"), r.get("xe_url")) if u}
    known_name = {name_key(r["name"]) for r in reg if name_key(r["name"])}

    added, became_ok, stats = [], [], {}
    if not a.no_directories:
        with tempfile.TemporaryDirectory() as tmp:
            cands = directories(tmp)
        stats["directory_entries"] = len(cands)
        seen = set()
        by_name = {name_key(r["name"]): r for r in reg if name_key(r["name"])}
        by_dom = {domain(r["website"] or r["final_url"]): r for r in reg if r["website"] or r["final_url"]}
        for c in cands:
            d, k = domain(c.get("website", "")), name_key(c.get("name", ""))
            # a known agency: remember its XE page (its XE listings are collected daily from there)
            known = by_dom.get(d) if d else None
            known = known or by_name.get(k)
            if known is not None and c.get("xe_url") and not known.get("xe_url"):
                known["xe_url"] = c["xe_url"]
                stats["xe_linked"] = stats.get("xe_linked", 0) + 1
            if not k or (d and d in known_dom) or c.get("vrisko_url") in known_url or c.get("xe_url") in known_url \
                    or k in known_name or k in seen:
                continue
            seen.add(k)
            row = {f: "" for f in fields}
            row.update({k2: v for k2, v in c.items() if k2 in fields})
            row.update(type="independent", domain=d, website=c.get("website", ""))
            added.append(row)
        print(f"{len(cands)} directory entries, {len(added)} new agencies", file=sys.stderr)
        with ThreadPoolExecutor(8) as ex:
            guesses = list(ex.map(lambda r: "" if r["website"] else find_site(r), added))
        for row, url in zip(added, guesses):
            if url and domain(url) not in known_dom:
                row.update(website=url, domain=domain(url), found_via=row["found_via"] + "; site by domain guess")
        print(f"sites found by domain guess: {sum(1 for g in guesses if g)}", file=sys.stderr)

    todo = added + ([] if a.no_recheck else [r for r in reg if r["site_status"].startswith(RECHECK)])
    with ThreadPoolExecutor(6) as ex:
        results = list(ex.map(check, todo))
    for row, res in zip(todo, results):
        was = row["site_status"]
        row.update(res)
        if row not in added and not was.startswith("ok") and res["site_status"] == "ok" and res["has_listings"] == "yes":
            became_ok.append(row)
    reg += added
    new_sites = [r for r in added if r["site_status"] == "ok" and r["has_listings"] == "yes"]
    stats.update(added=len(added), added_with_site=sum(1 for r in added if r["website"]),
                 added_collectable=len(new_sites), rechecked=len(todo) - len(added), came_back=len(became_ok))
    print(stats, file=sys.stderr)
    if a.dry_run:
        for r in new_sites + became_ok:
            print("would collect:", r["name"], r["website"] or r["final_url"])
        for r in added:
            print("new:", r["name"], "|", r["street"], r["postal_code"], "|", r["website"], r["site_status"], r["has_listings"])
        return
    with open(REGISTRY + ".tmp", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(reg)
    os.replace(REGISTRY + ".tmp", REGISTRY)
    new_log = not os.path.exists(LOG)
    with open(LOG, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if new_log:
            w.writerow(["date", "directory_entries", "added", "added_with_site", "added_collectable", "rechecked",
                        "came_back", "names"])
        w.writerow([datetime.date.today().isoformat(), stats.get("directory_entries", ""), stats["added"],
                    stats["added_with_site"], stats["added_collectable"], stats["rechecked"], stats["came_back"],
                    "; ".join(r["name"] for r in new_sites + became_ok)[:1000]])
    telegram(stats, new_sites, became_ok, [r for r in added if r not in new_sites])


def telegram(stats, new_sites, came_back, others):
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        print("TELEGRAM_BOT_TOKEN not set: summary not sent", file=sys.stderr)
        return
    import notify_telegram as nt
    esc = nt.html_escape
    lines = [f"🔎 <b>Spiti Radar{' · ' + city.TELEGRAM_TITLE if city.TELEGRAM_TITLE else ''}</b>: еженедельный поиск агентств",
             f"В справочниках vrisko.gr и xe.gr: {stats.get('directory_entries', '—')} записей, новых агентств {stats['added']}."]
    pieces = [f"• {esc(r['name'])} — <a href=\"{esc(r['final_url'] or r['website'])}\">сайт</a>" for r in new_sites]
    blocks = [("\n".join(lines), [])]
    if pieces:
        blocks.append((f"<b>Новые сайты с объявлениями ({len(pieces)})</b> — с завтрашнего сбора в поиске:", pieces))
    if came_back:
        blocks.append((f"<b>Снова работают ({len(came_back)})</b>:",
                       [f"• {esc(r['name'])} — <a href=\"{esc(r['final_url'] or r['website'])}\">сайт</a>" for r in came_back]))
    if others:
        no_site = sum(1 for r in others if not r["website"])
        blocks.append(("", [f"Ещё {len(others)} новых агентств без рабочего сайта с объявлениями "
                            f"({no_site} без сайта); их объекты видны через порталы."]))
    blocks.append(("", [f"Повторно проверено закрытых и не открывавшихся сайтов: {stats['rechecked']}."]))
    ok, err = nt.send(token, nt.chat_id(token), nt.pack(blocks))
    print(f"Telegram: {ok} delivered {err or ''}", file=sys.stderr)


if __name__ == "__main__":
    main()
