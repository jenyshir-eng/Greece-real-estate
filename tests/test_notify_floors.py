"""Run from the repository root: python3 -m unittest discover -s tests"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))
import notify_telegram as nt  # noqa: E402
from floors import floor_code  # noqa: E402

BASE = {"transaction": "sale", "types": ["apartment"], "floor_min": 0, "keep_unknown": True, "keep_unknown_floor": True}


def prop(floor):
    return {"tx": "sale", "region": nt.city.KEY, "region_ok": True, "type": "apartment", "area": "", "nb": "",
            "price": 90000, "m2": 60, "beds": None, "floor": floor}


class Floors(unittest.TestCase):
    def test_field_values(self):
        self.assertEqual([floor_code(s) for s in ("Υπόγειο", "Ημιυπόγειο", "ισόγειο", "Ημιώρ.", "1ος όροφος", "-1", "46")],
                         [-2, -1, 0, 0.5, 1, -2, None])

    def test_title_names_the_basement_when_the_field_is_empty(self):
        members = [{"floor": "", "title": "Ημιυπόγειο διαμέρισμα 60 τ.μ. Καλαμαριά"}, {"floor": "", "title": "Διαμέρισμα 60 τ.μ."}]
        self.assertEqual(nt.floor_level(members), -1)

    def test_floor_field_wins_over_title(self):
        self.assertEqual(nt.floor_level([{"floor": "2", "title": "πάνω από υπόγειο parking"}]), 2)

    def test_filter_drops_basements_keeps_unknown(self):
        self.assertFalse(nt.matches(prop(-1), BASE))
        self.assertFalse(nt.matches(prop(-2), BASE))
        self.assertTrue(nt.matches(prop(0), BASE))
        self.assertTrue(nt.matches(prop(None), BASE))

    def test_unknown_floor_is_labelled(self):
        p = dict(prop(None), url="https://x/1", sites=1, source="Spitogatos")
        self.assertIn("этаж не указан", nt.line(p))


class SendHours(unittest.TestCase):
    def test_only_in_listed_athens_hours(self):
        import datetime
        conf = {"send_hours": [9, 10, 11, 13, 14, 15, 17, 18, 19]}
        at = lambda h: datetime.datetime(2026, 11, 24, h, 30)  # noqa: E731
        self.assertTrue(nt.sending_now(conf, at(9)))
        self.assertTrue(nt.sending_now(conf, at(17)))
        self.assertFalse(nt.sending_now(conf, at(21)))
        self.assertTrue(nt.sending_now({}, at(21)))

    def test_price_limit_drops_dearer_and_unpriced(self):
        f = dict(BASE, price_max=130000)
        self.assertTrue(nt.matches(prop(0), f))
        self.assertFalse(nt.matches(dict(prop(0), price=150000), f))
        self.assertFalse(nt.matches(dict(prop(0), price=None), f))


if __name__ == "__main__":
    unittest.main()
