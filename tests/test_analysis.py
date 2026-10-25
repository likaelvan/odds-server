"""Tests for player profiles, search and head-to-head (Players / Head-to-head tabs)."""
import json
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)

from odds_server.analysis import h2h_page, level_group, player_page, search  # noqa: E402
from odds_server.stats import Stats, build_index  # noqa: E402
from test_stats import make_dataset  # noqa: E402


class AnalysisTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        make_dataset(cls.tmp)
        # one Wikipedia result after the archive, with surface + level from the season page
        with open(os.path.join(cls.tmp, "wta_wiki_matches.json"), "w", encoding="utf-8") as f:
            json.dump({"matches": [
                {"date": 20261019, "tournament": "Japan Open", "round": "F", "winner": "Leylah Fernandez",
                 "loser": "Sorana Cîrstea", "score": "6-4 6-4", "surface": "Hard", "level": "250"},
                {"date": 20261019, "tournament": "Japan Open", "round": "SF", "winner": "Sorana Cîrstea",
                 "loser": "Elise Mertens", "score": "W/O", "surface": "Hard", "level": "250"},
            ]}, f)
        cls.s = Stats(build_index("wta", cls.tmp))

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp)

    def test_level_groups(self):
        self.assertEqual(level_group("atp", "M", "R32"), "1000")
        self.assertEqual(level_group("atp", "A", "R32"), "tour")
        self.assertEqual(level_group("wta", "PM", "R16"), "1000")
        self.assertEqual(level_group("wta", "I", "QF"), "250")
        self.assertEqual(level_group("wta", "35+H", "R32"), "itf")
        self.assertEqual(level_group("wta", "G", "Q2"), "qualifying")
        self.assertEqual(level_group("wta", "250", "F"), "250")   # Wikipedia code

    def test_search(self):
        res = search(self.s, "fern")
        self.assertEqual(res[0]["name"], "Leylah Fernández")
        self.assertEqual(search(self.s, "cirst")[0]["id"], "4")      # accents ignored
        self.assertEqual(search(self.s, "x"), [])                     # too short

    def test_player_page(self):
        p = player_page(self.s, "1")
        self.assertEqual(p["name"], "Leylah Fernández")
        self.assertEqual(p["season"]["year"], 2026)
        self.assertEqual((p["season"]["w"], p["season"]["l"]), (3, 0))   # 2 Ningbo + Japan Open final
        self.assertEqual(p["titles"][0]["tournament"], "Japan Open")
        self.assertEqual(p["titles"][0]["level"], "250")
        self.assertEqual(p["streak"], {"kind": "W", "length": 3})
        self.assertIn({"surface": "Hard", "career": {"w": 11, "l": 1, "pct": 0.917},
                       "last_52_weeks": {"w": 3, "l": 0, "pct": 1.0}}, p["surfaces"])
        self.assertEqual(p["rank_history"][0], {"month": "2022-01", "rank": 13})
        self.assertEqual(p["form_10"][:3], "WWW")

    def test_walkovers_not_counted(self):
        p = player_page(self.s, "4")
        self.assertNotIn("Elise Mertens", [m["opponent"] for m in p["last_matches"] if m["result"] == "W"
                                           and m["score"] != "W/O"])
        overall = p["overall"]
        self.assertEqual(overall["w"] + overall["l"], 11)  # 12 matches, minus one walkover

    def test_h2h_page(self):
        h = h2h_page(self.s, "1", "2")
        self.assertEqual((h["wins"], h["losses"]), (1, 1))
        self.assertEqual(h["by_surface"], [{"surface": "Hard", "wins": 1, "losses": 1}])
        self.assertEqual([p["name"] for p in h["players"]], ["Leylah Fernández", "Elise Mertens"])
        self.assertEqual(h["players"][0]["titles"], 1)


if __name__ == "__main__":
    unittest.main()
