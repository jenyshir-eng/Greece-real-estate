"""Run from the repository root: python3 -m unittest discover -s tests
--skip-domains / --out-dir of collect_listings.py: the GitHub run drops the cloud sites, the cloud run
writes only its own folder."""
import csv
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))
import collect_listings as cl  # noqa: E402

REG = ["name", "domain", "website", "final_url", "site_status", "robots_ok", "has_listings"]
FIELDS = ["source_domain", "agency", "url", "title", "scraped_at"]


def fake_collect(row, *a, **k):
    d = row["domain"]
    return ([{"source_domain": d, "agency": d, "url": f"https://{d}/p/2", "title": "new", "scraped_at": "2026-11-21T00:00:00Z"}],
            {"domain": d, "listing_urls": 1, "parsed": 1, "error": ""})


def write(path, fields, rows):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


class CloudSplit(unittest.TestCase):
    def run_main(self, tmp, argv):
        cwd = os.getcwd()
        os.chdir(tmp)
        try:
            with mock.patch.object(cl, "collect_site", fake_collect), mock.patch.object(sys, "argv", ["x"] + argv), \
                    mock.patch.object(cl, "OUT", "data/listings/listings.csv"), \
                    mock.patch.object(cl, "REPORT", "data/listings/collect_report.csv"), \
                    mock.patch.object(cl, "NOT_LISTINGS", "data/listings/not_listings.txt"), \
                    mock.patch.object(cl, "REMOVED", "data/listings/removed.csv"), \
                    mock.patch.object(cl, "REGISTRY", "reg.csv"):
                cl.main()
        finally:
            os.chdir(cwd)

    def setup(self, tmp):
        write(os.path.join(tmp, "reg.csv"), REG, [{"name": d, "domain": d, "website": f"https://{d}", "final_url": f"https://{d}",
                                                   "site_status": "ok", "robots_ok": "", "has_listings": "yes"} for d in ("a.gr", "b.gr")])
        write(os.path.join(tmp, "data/listings/listings.csv"), FIELDS,
              [{"source_domain": d, "agency": d, "url": f"https://{d}/p/1", "title": "old", "scraped_at": "2026-11-20T00:00:00Z"}
               for d in ("a.gr", "b.gr")])
        open(os.path.join(tmp, "cloud.txt"), "w").write("# comment\nb.gr\n")

    def test_github_run_skips_and_drops_cloud_sites(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.setup(tmp)
            self.run_main(tmp, ["--incremental", "--skip-domains", "cloud.txt"])
            rows = list(csv.DictReader(open(os.path.join(tmp, "data/listings/listings.csv"))))
            self.assertEqual({r["source_domain"] for r in rows}, {"a.gr"})

    def test_cloud_run_writes_only_its_folder(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.setup(tmp)
            before = open(os.path.join(tmp, "data/listings/listings.csv")).read()
            self.run_main(tmp, ["--incremental", "--domains", "cloud.txt", "--out-dir", "data/cloud"])
            self.assertEqual(open(os.path.join(tmp, "data/listings/listings.csv")).read(), before)
            rows = list(csv.DictReader(open(os.path.join(tmp, "data/cloud/listings.csv"))))
            self.assertEqual({r["source_domain"] for r in rows}, {"b.gr"})
            self.assertTrue(os.path.exists(os.path.join(tmp, "data/cloud/collect_report.csv")))


if __name__ == "__main__":
    unittest.main()
