"""Run from the repository root: python3 -m unittest discover -s tests"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))
import collect_servicers as cs  # noqa: E402

NOW = "2026-10-13T10:00:00Z"
SITE = "https://marketplace.altamiraproperties.gr"


def listing(**kw):
    x = {"id": "26280", "acquired": False, "status": "public", "commercialization": "auction",
         "coordinates": [40.5882, 22.9513], "price": 111000, "size": 76, "type": "apartment",
         "title": [{"locale": "en", "value": "Apartment, 76 sqm"}, {"locale": "el", "value": "Διαμέρισμα, 76 τ.μ., Περαία"}],
         "region": [{"locale": "el", "value": "Θεσσαλονίκη - Περιφέρεια"}],
         "created_at": 1789994258, "updated_at": 1791353824, "auction_date": 1802210400, "auction_round": 1,
         "auction_date_to_be_announced": False, "images": [{"sizes": {"lg": "https://img/lg.jpg"}}]}
    x.update(kw)
    return x


class RowFrom(unittest.TestCase):
    def test_auction_listing(self):
        r = cs.row_from(listing(), "altamiraproperties.gr", "Altamira (doValue)", SITE, "auction", NOW)
        self.assertEqual(r["url"], SITE + "/listings/26280")
        self.assertEqual(r["title"], "Διαμέρισμα, 76 τ.μ., Περαία")
        self.assertEqual((r["segment"], r["auction_date"], r["auction_round"]), ("auction", "2027-02-10", 1))
        self.assertEqual((r["price_eur"], r["area_m2"], r["type"], r["image"]), (111000, 76, "apartment", "https://img/lg.jpg"))
        self.assertEqual((r["date_published"], r["checked_at"]), ("2026-09-21", "2026-10-13"))

    def test_bank_sale_has_no_auction_fields(self):
        r = cs.row_from(listing(type="detachedHouse"), "intrum.gr", "Intrum", SITE, "bank", NOW)
        self.assertEqual((r["segment"], r["auction_date"], r["auction_round"], r["type"]), ("bank", "", "", "house"))

    def test_hidden_price_and_unannounced_date(self):
        r = cs.row_from(listing(price_upon_request=True, auction_date_to_be_announced=True),
                        "altamiraproperties.gr", "A", SITE, "auction", NOW)
        self.assertEqual((r["price_eur"], r["auction_date"]), ("", ""))

    def test_sold_or_outside_region_is_skipped(self):
        self.assertIsNone(cs.row_from(listing(acquired=True), "d", "n", SITE, "auction", NOW))
        self.assertIsNone(cs.row_from(listing(coordinates=[37.97, 23.72]), "d", "n", SITE, "auction", NOW))

    def test_search_url_filters_by_box(self):
        u = cs.search_url("https://api.x", "sale", [40.4, 41.1, 22.5, 23.8], 2)
        self.assertIn("commercialization%3A%3Dsale%26%26coordinates%3A+%2841.10000%2C+23.80000", u)
        self.assertIn("page=2", u)


if __name__ == "__main__":
    unittest.main()
