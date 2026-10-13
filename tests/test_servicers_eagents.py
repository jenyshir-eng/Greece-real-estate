"""Run from the repository root: python3 -m unittest discover -s tests"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))
import servicers_eagents as ea  # noqa: E402

# trimmed cards as the two sites serve them
REINVEST = '''<div class="listing-style1" data-property-id="1417234"><div class="list-thumb">
<img loading="lazy" alt="photo" src="https://cdn/fol1417234/a.jpeg"></div>
<div class="list-content"> <div class="list-price"> <span>77.000 €</span> </div>
<a href="properties/1417234"><h6 class="list-title color2"> <span>Παραλία Νέας Κίου,</span> <span>&nbsp;</span> </h6>
<p class=""> Διαμέρισμα
 <span>104 m<sup>2</sup></span> </p></a>
<i class="icon fa-light fa-bed-front color1"></i> <span class="fs16 color8">2</span></div></div>'''
REAUCTION = '''<div class="listing-style1" data-property-id="2640255"><div class="list-content">
<h6 class="list-title secversion"> <span>Φιλιππιάδα</span> <span>&nbsp;</span> <br> Μονοκατοικία
<span class="clight">&nbsp;|&nbsp;</span> <span>Ψιλή κυριότητα</span> <span>(50%)</span> </h6>
<div class="list-meta"> 90,68 <span>m<sup>2</sup></span></div>
<div class="list-price"><div><span class="pr10"> 58.000 € </span></div>
<span class="pr10" title="Ημερομηνία Δημοπρασίας"> <i class="x"></i> 22-04-2027 </span>
<span class="yellow" title="Λήξη Συμμετοχών"> 17-04-2027 </span> 1ος γύρος</div></div></div>'''
NOW = "2026-10-13T10:00:00Z"
inside = lambda lat, lon: True  # noqa: E731


class Cards(unittest.TestCase):
    def test_reinvest_card(self):
        c = ea.parse_cards(REINVEST)[0]
        self.assertEqual((c["id"], c["place"], c["type_gr"], c["area"], c["price"], c["bedrooms"]),
                         ("1417234", "Παραλία Νέας Κίου", "Διαμέρισμα", 104, 77000, "2"))
        r = ea.row_from(c, (40.6, 22.9), ea.SITES[0], NOW, inside)
        self.assertEqual((r["url"], r["segment"], r["type"], r["auction_date"]),
                         ("https://www.reinvest.gr/el/properties/1417234", "bank", "apartment", ""))

    def test_reauction_card_with_share(self):
        c = ea.parse_cards(REAUCTION)[0]
        self.assertEqual((c["type_gr"], c["area"], c["price"], c["auction_date"], c["round"], c["share"]),
                         ("Μονοκατοικία", 90.68, 58000, "2027-04-22", "1", "50"))
        r = ea.row_from(c, (40.6, 22.9), ea.SITES[1], NOW, inside)
        self.assertEqual((r["segment"], r["type"], r["auction_date"], r["auction_round"]), ("auction", "house", "2027-04-22", "1"))
        self.assertIn("μερίδιο 50%", r["title"])

    def test_no_point_or_outside_is_skipped(self):
        c = ea.parse_cards(REINVEST)[0]
        self.assertIsNone(ea.row_from(c, None, ea.SITES[0], NOW, inside))
        self.assertIsNone(ea.row_from(c, (37.9, 23.7), ea.SITES[0], NOW, lambda la, lo: False))


if __name__ == "__main__":
    unittest.main()
