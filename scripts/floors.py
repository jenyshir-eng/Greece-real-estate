"""Floor of a listing as a level (shared by the search page and the Telegram messages)."""
import re


def floor_code(s, title=""):
    """Greek floor -> level: -2 basement (υπόγειο), -1 semi-basement (ημιυπόγειο), 0 ground (ισόγειο),
    0.5 mezzanine / raised ground (ημιόροφος, υπερυψωμένο), 1.. upper floors.
    No floor field: the title is used. Values above 12 are data errors (usually the area) -> None."""
    t = (s or "").strip().lower()
    for text in (t, (title or "").lower()):
        if not text:
            continue
        if re.search(r"ημιυπ|semi.?basement", text):
            return -1
        if re.search(r"υπόγ|υπογει|basement", text):
            return -2
        if re.search(r"ημιόρ|ημιορ|ημιώρ|ημιωρ|mezzanine|υπερυψ|raised", text):
            return 0.5
        if re.search(r"ισόγ|ισογ|ground", text):
            return 0
        if text is t:
            try:
                n = int(float(t.split()[0].rstrip("οςηº")))
            except ValueError:
                continue
            return -2 if n < 0 else (n if n <= 12 else None)
    return None
