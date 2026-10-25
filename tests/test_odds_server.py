"""Run with:  py -m unittest discover tests"""
import json
import os
import shutil
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from odds_server import odds_api  # noqa: E402
from odds_server.core import analyse, effective, normalize_event, allocate  # noqa: E402

with open(os.path.join(HERE, "sample_odds.json"), encoding="utf-8") as f:
    SAMPLE = json.load(f)


class CoreTests(unittest.TestCase):
    def test_effective_fee(self):
        self.assertAlmostEqual(effective(2.0, 5), 1.95)
        self.assertEqual(effective(2.0), 2.0)

    def test_normalize_matches_names_and_skips_other_markets(self):
        m = normalize_event(SAMPLE[0])
        self.assertEqual(m["players"], ["Player Alpha", "Player Beta"])
        self.assertEqual([b["name"] for b in m["books"]], ["Book A", "Book B"])  # Book C has no h2h
        self.assertEqual(m["books"][1]["odds"], [1.80, 2.05])  # reordered to home/away

    def test_gap_found(self):
        a = analyse(normalize_event(SAMPLE[0])["books"])
        self.assertTrue(a["gap"])
        self.assertEqual(a["best"][0]["book"], "Book A")
        self.assertEqual(a["best"][1]["book"], "Book B")
        self.assertAlmostEqual(a["margin"], 0.0373, places=3)

    def test_no_gap(self):
        a = analyse(normalize_event(SAMPLE[1])["books"])
        self.assertFalse(a["gap"])
        self.assertLess(a["margin"], 0)

    def test_allocate_equal_returns(self):
        a = analyse(normalize_event(SAMPLE[0])["books"])
        amounts, returns, surplus = allocate(a["best"], 1000)
        self.assertAlmostEqual(sum(amounts), 1000, delta=0.02)
        self.assertAlmostEqual(returns[0], returns[1], delta=0.05)
        self.assertAlmostEqual(surplus, 37.3, delta=0.2)
        amounts, _, _ = allocate(a["best"], 1000, round_to=10)
        self.assertTrue(all(x % 10 == 0 for x in amounts))

    def test_missing_side(self):
        self.assertFalse(analyse([{"name": "X", "odds": [2.0, None]}])["ok"])


class FakeAPI(BaseHTTPRequestHandler):
    calls = 0
    used = 0

    def log_message(self, *a):
        pass

    def do_GET(self):
        last = "0"
        if "apiKey=bad" in self.path:
            body, code = {"message": "API key is not valid"}, 401
        elif self.path.startswith("/v4/sports?"):
            body, code = [{"key": "tennis_atp_sample", "group": "Tennis", "title": "ATP Sample", "active": True},
                          {"key": "soccer_epl", "group": "Soccer", "title": "EPL", "active": True}], 200
        else:
            FakeAPI.calls += 1
            FakeAPI.used += 2
            body, code, last = SAMPLE, 200, "2"
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("x-requests-remaining", str(500 - FakeAPI.used))
        self.send_header("x-requests-used", str(FakeAPI.used))
        self.send_header("x-requests-last", last)
        self.end_headers()
        self.wfile.write(data)


class ClientTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), FakeAPI)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.orig = odds_api.BASE_URL
        odds_api.BASE_URL = "http://127.0.0.1:%d/v4" % cls.srv.server_port

    @classmethod
    def tearDownClass(cls):
        odds_api.BASE_URL = cls.orig
        cls.srv.shutdown()

    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_tournaments_filters_tennis(self):
        api = odds_api.OddsAPI("good", cache_dir=self.tmp)
        self.assertEqual([t["key"] for t in api.tennis_tournaments()], ["tennis_atp_sample"])
        self.assertEqual(api.remaining + api.used, 500)

    def test_odds_and_cache(self):
        api = odds_api.OddsAPI("good", cache_dir=self.tmp, cache_minutes=10)
        before = FakeAPI.calls
        d1 = api.tennis_odds("tennis_atp_sample")
        d2 = api.tennis_odds("tennis_atp_sample")
        self.assertFalse(d1["from_cache"])
        self.assertTrue(d2["from_cache"])
        self.assertEqual(FakeAPI.calls - before, 1)
        self.assertTrue(d1["matches"][0]["analysis"]["gap"])
        api.tennis_odds("tennis_atp_sample", force=True)
        self.assertEqual(FakeAPI.calls - before, 2)

    def test_credit_tracking_persists(self):
        api = odds_api.OddsAPI("good", cache_dir=self.tmp)
        api.tennis_odds("tennis_atp_sample", "eu,uk")
        api.tennis_odds("tennis_atp_sample", "eu,uk")  # cached: free, not logged
        c = api.credit_status("eu,uk")
        self.assertTrue(c["known"])
        self.assertEqual(c["total"], 500)
        self.assertEqual(len(c["log"]), 1)
        self.assertEqual(c["log"][0]["cost"], 2)
        self.assertEqual(c["loads_left"], c["remaining"] // 2)
        again = odds_api.OddsAPI("good", cache_dir=self.tmp).credit_status("eu,uk,us")
        self.assertEqual(again["remaining"], c["remaining"])  # survives restart
        self.assertEqual(again["per_load"], 3)

    def test_credits_unknown_before_first_call(self):
        c = odds_api.OddsAPI("good", cache_dir=self.tmp).credit_status()
        self.assertFalse(c["known"])

    def test_bad_key_message(self):
        api = odds_api.OddsAPI("bad", cache_dir=self.tmp)
        with self.assertRaises(odds_api.OddsAPIError) as cm:
            api.tennis_tournaments()
        self.assertIn("401", str(cm.exception))

    def test_requires_key(self):
        with self.assertRaises(odds_api.OddsAPIError):
            odds_api.OddsAPI("", cache_dir=self.tmp)


if __name__ == "__main__":
    unittest.main()


class RetryTests(unittest.TestCase):
    def test_retries_dropped_connection_then_succeeds(self):
        from unittest import mock
        tmp = tempfile.mkdtemp()
        try:
            api = odds_api.OddsAPI("good", cache_dir=tmp)
            ok = mock.MagicMock()
            ok.__enter__.return_value.read.return_value = b"[]"
            ok.__enter__.return_value.headers = {}
            calls = [ConnectionResetError(10054, "forcibly closed"), ok]
            with mock.patch.object(odds_api.urllib.request, "urlopen", side_effect=calls), \
                    mock.patch.object(odds_api.time, "sleep"):
                self.assertEqual(api.tennis_tournaments(), [])
        finally:
            shutil.rmtree(tmp)

    def test_gives_clear_message_after_retries(self):
        from unittest import mock
        tmp = tempfile.mkdtemp()
        try:
            api = odds_api.OddsAPI("good", cache_dir=tmp)
            with mock.patch.object(odds_api.urllib.request, "urlopen",
                                   side_effect=ConnectionResetError(10054, "forcibly closed")), \
                    mock.patch.object(odds_api.time, "sleep"):
                with self.assertRaises(odds_api.OddsAPIError) as cm:
                    api.tennis_tournaments()
            self.assertIn("after 3 tries", str(cm.exception))
        finally:
            shutil.rmtree(tmp)
