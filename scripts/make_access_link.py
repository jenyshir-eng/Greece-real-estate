"""Make time-limited links to the Spiti Radar sites (checked by functions/_middleware.js).

The link works for --hours from now, for everyone who has it, and then stops by itself.
The secret is the ACCESS_SECRET environment variable, the same value as in the Cloudflare Pages
projects. With --telegram the links go to the owner's chat (TELEGRAM_BOT_TOKEN,
data/listings/notify_chat.json) instead of the console, so they never appear in a public CI log.

Usage: ACCESS_SECRET=... python3 scripts/make_access_link.py [--hours 24] [--label anna] [--telegram]
"""
import argparse
import base64
import datetime
import hashlib
import hmac
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
import zoneinfo

SITES = [("Салоники", "https://radar.jenyshir.com/"), ("Афины", "https://athens.jenyshir.com/")]
CHAT_FILE = "data/listings/notify_chat.json"
MAX_HOURS = 24 * 366 * 5


def make_key(secret, expires, label=""):
    msg = f"{expires}.{label}".encode()
    sig = base64.urlsafe_b64encode(hmac.new(secret.encode(), msg, hashlib.sha256).digest()).rstrip(b"=").decode()
    return f"{expires}.{label}.{sig}"


def label_ok(label):
    return bool(re.fullmatch(r"[a-z0-9-]{0,40}", label))


def send_telegram(token, chat, text):
    data = urllib.parse.urlencode({"chat_id": chat, "text": text, "disable_web_page_preview": "true"}).encode()
    with urllib.request.urlopen(f"https://api.telegram.org/bot{token}/sendMessage", data=data, timeout=30) as r:
        if not json.load(r).get("ok"):
            raise RuntimeError("Telegram did not accept the message")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--hours", type=float, default=24)
    ap.add_argument("--label", default="", help="who the link is for: latin letters, digits, '-'")
    ap.add_argument("--telegram", action="store_true", help="send to the owner's Telegram chat, print nothing secret")
    a = ap.parse_args()
    secret = os.environ.get("ACCESS_SECRET", "")
    if len(secret) < 16:
        sys.exit("ACCESS_SECRET is not set or shorter than 16 characters")
    label = a.label.strip().lower()
    if not label_ok(label):
        sys.exit("label: up to 40 latin letters, digits or '-'")
    if not 0 < a.hours <= MAX_HOURS:
        sys.exit(f"hours: from 0 to {MAX_HOURS}")
    expires = int(time.time() + a.hours * 3600)
    key = make_key(secret, expires, label)
    until = datetime.datetime.fromtimestamp(expires, zoneinfo.ZoneInfo("Europe/Athens"))
    text = (f"Spiti Radar: ссылки{' для ' + label if label else ''}, действуют до "
            f"{until:%d.%m.%Y %H:%M} по Афинам\n\n"
            + "\n".join(f"{name}: {base}?key={key}" for name, base in SITES))
    if a.telegram:
        token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
        if not token:
            sys.exit("TELEGRAM_BOT_TOKEN is not set")
        send_telegram(token, json.load(open(CHAT_FILE))["chat_id"], text)
        print(f"links sent to Telegram, valid until {until:%Y-%m-%d %H:%M} Athens")
    else:
        print(text)


if __name__ == "__main__":
    main()
