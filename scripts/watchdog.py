"""Watchdog: did the scheduled update run, save its data and reach Telegram?

Reads what the update runs commit to main (pull first):
  data/listings/update_log.csv  - one line per finished run (scripts/update_report.py)
  data/listings/notify_log.csv  - Telegram delivery per run (scripts/notify_telegram.py)
and checks the public site (radar.jenyshir.com) carries the same data date.

Exit 0: all fine, nothing is sent.
Exit 2: no run was saved after the last scheduled start (10:13 / 18:43 Athens) that began at
        least --grace-hours ago: a warning goes to Telegram; whoever runs this then starts the
        update again (the routine does). A run that is still going (started less than
        --grace-hours ago) is not a failure.
Exit 3: the run is fresh, but something else is wrong (Telegram not delivered, site stale):
        a warning goes to Telegram.

Usage: python3 scripts/watchdog.py [--grace-hours 4]
"""
import argparse
import csv
import datetime
import os
import re
import sys
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import city  # noqa: E402

UPDATE_LOG = "data/listings/update_log.csv"
SCHEDULE = city.SCHEDULE  # the update routines, Europe/Athens
NOTIFY_LOG = "data/listings/notify_log.csv"
SITE = city.SITE_URL.rstrip("/") + "/"
TITLE = "Spiti Radar" + (" · " + city.TELEGRAM_TITLE if city.TELEGRAM_TITLE else "")


def last_row(path):
    if not os.path.exists(path):
        return None
    rows = list(csv.DictReader(open(path, encoding="utf-8")))
    return rows[-1] if rows else None


def when(at):
    return datetime.datetime.strptime(at, "%Y-%m-%dT%H:%MZ")


def last_due_start(now, grace_hours):
    """UTC time of the latest scheduled update start that should have finished by now."""
    from zoneinfo import ZoneInfo
    athens = ZoneInfo("Europe/Athens")
    local = now.replace(tzinfo=datetime.timezone.utc).astimezone(athens)
    starts = [datetime.datetime.combine(local.date() - datetime.timedelta(days=d), datetime.time(h, m), athens)
              for d in (0, 1, 2) for h, m in SCHEDULE]
    due = [t for t in starts if t <= local - datetime.timedelta(hours=grace_hours)]
    return max(due).astimezone(datetime.timezone.utc).replace(tzinfo=None)


def site_date():
    try:
        req = urllib.request.Request(SITE, headers={"User-Agent": "SpitiRadar watchdog"})
        page = urllib.request.urlopen(req, timeout=120).read().decode("utf-8", "replace")
    except Exception as e:
        return None, f"сайт не открылся ({type(e).__name__})"
    m = re.search(r'const ASOF = "(\d\d)\.(\d\d)\.(\d{4})"', page)
    return (f"{m.group(3)}-{m.group(2)}-{m.group(1)}" if m else None), ""


def send(text):
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        print("TELEGRAM_BOT_TOKEN not set: warning not sent", file=sys.stderr)
        return
    import notify_telegram as nt
    ok, err = nt.send(token, nt.chat_id(token), [text])
    print(f"Telegram warning: {'delivered' if ok else 'NOT delivered ' + '; '.join(err)}", file=sys.stderr)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--grace-hours", type=float, default=4, help="how long a run may take before it counts as missing")
    a = ap.parse_args()
    now = datetime.datetime.utcnow()
    run = last_row(UPDATE_LOG)
    due = last_due_start(now, a.grace_hours)
    age = (now - when(run["at"])).total_seconds() / 3600 if run else None
    if run is None or when(run["at"]) < due:
        since = when(run["at"]).strftime("%d.%m %H:%M UTC") if run else "никогда"
        send(f"⚠️ <b>{TITLE} не обновлялся</b> с {since}. Плановый запуск не сохранил данные. "
             f"Запускаю обновление повторно, итог придёт отдельным сообщением.")
        print(f"STALE: last saved run {since}", file=sys.stderr)
        sys.exit(2)
    problems = []
    if run.get("failed_steps"):
        problems.append(f"в последнем запуске не сработали шаги: {run['failed_steps']}")
    note = last_row(NOTIFY_LOG)
    if note and note["delivered"] != note["messages"] and when(note["at"]) >= when(run["at"]):
        problems.append(f"Telegram: доставлено {note['delivered']} из {note['messages']} ({note['errors'][:150]})")
    d, err = site_date()
    if err:
        problems.append(err)
    elif d and d < run["at"][:10]:
        problems.append(f"сайт {SITE} показывает данные за {d}, а последний запуск {run['at'][:10]}: "
                        f"Cloudflare не пересобрал страницу")
    if problems:
        send(f"⚠️ <b>{TITLE}</b>: " + "; ".join(problems))
        print("PROBLEMS: " + "; ".join(problems), file=sys.stderr)
        sys.exit(3)
    print(f"OK: last run {run['at']} ({age:.1f} h ago), {run['new']} new, site date {d}", file=sys.stderr)


if __name__ == "__main__":
    main()
