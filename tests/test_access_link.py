"""Run from the repository root: python3 -m unittest discover -s tests
The page check (functions/_middleware.js) runs in Node; skipped when node is missing."""
import json
import os
import shutil
import subprocess
import sys
import time
import unittest

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import make_access_link as mal  # noqa: E402

SECRET = "test-secret-0123456789"
# calls onRequest with a fake Pages context and prints status, Location, Set-Cookie
DRIVER = """
import { onRequest } from %s;
const [url, cookie, secret] = JSON.parse(process.argv[1]);
const headers = cookie ? { Cookie: cookie } : {};
const res = await onRequest({ request: new Request(url, { headers }), env: secret ? { ACCESS_SECRET: secret } : {},
  next: async () => new Response("page", { status: 200 }) });
console.log(JSON.stringify([res.status, res.headers.get("Location"), res.headers.get("Set-Cookie")]));
"""


@unittest.skipUnless(shutil.which("node"), "node is not installed")
class Middleware(unittest.TestCase):
    def call(self, url, cookie="", secret=SECRET):
        mod = json.dumps("file://" + os.path.abspath(os.path.join(ROOT, "functions", "_middleware.js")))
        out = subprocess.run(["node", "--input-type=module", "-e", DRIVER % mod, json.dumps([url, cookie, secret])],
                             capture_output=True, text=True, check=True)
        return json.loads(out.stdout)

    def test_valid_key_sets_cookie_and_cleans_url(self):
        key = mal.make_key(SECRET, int(time.time()) + 3600, "anna")
        status, loc, cookie = self.call(f"https://radar.jenyshir.com/?key={key}")
        self.assertEqual((status, loc), (302, "/"))
        self.assertIn(f"sr_access={key};", cookie)
        self.assertEqual(self.call("https://radar.jenyshir.com/", f"sr_access={key}")[0], 200)

    def test_expired_forged_or_missing_key_is_denied(self):
        old = mal.make_key(SECRET, int(time.time()) - 10, "")
        forged = mal.make_key("another-secret-0123456", int(time.time()) + 3600, "")
        self.assertEqual(self.call(f"https://radar.jenyshir.com/?key={old}")[0], 403)
        self.assertEqual(self.call(f"https://radar.jenyshir.com/?key={forged}")[0], 403)
        self.assertEqual(self.call("https://radar.jenyshir.com/", f"sr_access={old}")[0], 403)
        self.assertEqual(self.call("https://radar.jenyshir.com/")[0], 403)

    def test_open_while_secret_not_set(self):
        self.assertEqual(self.call("https://radar.jenyshir.com/", secret="")[0], 200)


class Labels(unittest.TestCase):
    def test_label_rules(self):
        self.assertTrue(mal.label_ok("anna-2"))
        self.assertFalse(mal.label_ok("Анна"))


if __name__ == "__main__":
    unittest.main()
