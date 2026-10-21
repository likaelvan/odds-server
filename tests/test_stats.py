"""Tests for player stats, using a tiny fake dataset in Sackmann's CSV format."""
import csv
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from odds_server.stats import Stats, build_index, file_plan, normalize, tour_from_sport_key  # noqa: E402

MATCH_COLS = ["tourney_id", "tourney_name", "surface", "draw_size", "tourney_level", "tourney_date", "match_num",
              "winner_id", "winner_seed", "winner_entry", "winner_name", "winner_hand", "winner_ht", "winner_ioc",
              "winner_age", "loser_id", "loser_seed", "loser_entry", "loser_name", "loser_hand", "loser_ht",
              "loser_ioc", "loser_age", "score", "best_of", "round", "minutes", "winner_rank",
              "winner_rank_points", "loser_rank", "loser_rank_points"]


def write(path, cols, rows):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(cols)
        w.writerows(rows)


def match(date, tname, rnd, num, w, wn, l, ln, score, wr=None, lr=None, surface="Hard"):
    row = dict.fromkeys(MATCH_COLS, "")
    row.update(tourney_name=tname, surface=surface, tourney_level="A", tourney_date=date, match_num=num,
               winner_id=w, winner_name=wn, loser_id=l, loser_name=ln, score=score, round=rnd,
               winner_rank=wr or "", loser_rank=lr or "")
    return [row[c] for c in MATCH_COLS]


def make_dataset(root):
    d = os.path.join(root, "wta")
    os.makedirs(d)
    write(os.path.join(d, "wta_players.csv"),
          ["player_id", "name_first", "name_last", "hand", "dob", "ioc", "height", "wikidata_id"],
          [["1", "Leylah", "Fernández", "L", "20020906", "CAN", "168", ""],
           ["2", "Elise", "Mertens", "R", "19951117.0", "BEL", "181", ""],
           ["3", "Han", "Shi", "R", "20030101", "CHN", "", ""],
           ["4", "Sorana", "Cirstea", "R", "19900407", "ROU", "176", ""]])
    write(os.path.join(d, "wta_rankings_20s.csv"), ["ranking_date", "rank", "player", "points"],
          [["20210104", "12", "2", "3000"], ["20220110", "13", "1", "2500"], ["20220110", "21", "2", "1900"],
           ["20250106", "30", "1", "1500"]])
    write(os.path.join(d, "wta_rankings_current.csv"), ["ranking_date", "rank", "player", "points"],
          [["20261012", "25", "1", "1700"], ["20261012", "40", "2", "1200"], ["20261012", "90", "3", "600"]])
    rows = [match(20250101 + i * 100, "Event %d" % i, "R32", i, "1", "Leylah Fernandez", "4", "Sorana Cirstea",
                  "6-3 6-4", 30, 70) for i in range(8)]
    rows.append(match(20250901, "US Open", "R16", 1, "2", "Elise Mertens", "1", "Leylah Fernandez", "6-4 7-5", 35, 28))
    write(os.path.join(d, "wta_matches_2025.csv"), MATCH_COLS, rows)
    write(os.path.join(d, "wta_matches_2026.csv"), MATCH_COLS, [
        match(20261012, "Ningbo", "R32", 1, "1", "Leylah Fernandez", "3", "Han Shi", "6-2 6-2", 25, 90),
        match(20261012, "Ningbo", "R16", 2, "1", "Leylah Fernandez", "2", "Elise Mertens", "7-6(5) 6-4", 25, 40),
        match(20261012, "Ningbo", "QF", 3, "3", "Han Shi", "4", "Sorana Cirstea", "6-1 RET", 90, 70)])
    write(os.path.join(d, "wta_matches_qual_itf_2026.csv"), MATCH_COLS, [
        match(20260601, "ITF Test", "R16", 1, "3", "Han Shi", "4", "Sorana Cirstea", "6-0 6-0", 120, 80, "Clay")])


class StatsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        make_dataset(cls.tmp)
        cls.s = Stats(build_index("wta", cls.tmp))

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp)

    def test_normalize(self):
        self.assertEqual(normalize("Leylah Fernández"), "leylah fernandez")
        self.assertEqual(normalize("  Jo-Wilfried  Tsonga "), "jo wilfried tsonga")

    def test_find_variants(self):
        self.assertEqual(self.s.find("Leylah Fernandez"), ("1", "exact"))
        self.assertEqual(self.s.find("Shi Han"), ("3", "reordered"))   # name order swapped
        self.assertEqual(self.s.find("Elise Mertenz")[0], "2")         # small typo
        self.assertEqual(self.s.find("Nobody Atall"), (None, None))

    def test_ranks(self):
        p = self.s.profile("1")
        self.assertEqual((p["rank"], p["points"]), (25, 1700))
        self.assertEqual((p["career_high"], p["career_high_date"]), (13, "2022-01-10"))
        self.assertEqual(p["plays"], "Left-handed")
        m = self.s.profile("2")
        self.assertEqual(m["career_high"], 12)  # earliest best, from older ranking week

    def test_last_matches_newest_first(self):
        p = self.s.profile("1", last=10)
        self.assertEqual(len(p["last_matches"]), 10)
        self.assertEqual(p["last_matches"][0]["round"], "R16")   # later round same week comes first
        self.assertEqual(p["last_matches"][0]["opponent"], "Elise Mertens")
        self.assertEqual(p["form"][:3], "WWL")

    def test_lower_tier_matches_included(self):
        p = self.s.profile("3")
        self.assertIn("ITF Test", [m["tournament"] for m in p["last_matches"]])

    def test_head_to_head(self):
        h = self.s.head_to_head("1", "2")
        self.assertEqual((h["wins"], h["losses"]), (1, 1))
        self.assertEqual(h["meetings"][0]["tournament"], "Ningbo")

    def test_matchup_handles_unknown_player(self):
        out = self.s.matchup("Leylah Fernandez", "Mystery Player")
        self.assertEqual(out["players"][1]["match"], None)
        self.assertIsNone(out["h2h"])
        self.assertEqual(out["data_through"], "2026-10-12")

    def test_helpers(self):
        self.assertEqual(tour_from_sport_key("tennis_wta_ningbo_open"), "wta")
        self.assertEqual(tour_from_sport_key("tennis_atp_paris_masters"), "atp")
        plan = dict(file_plan("atp", 2024, 2, ["20s"], this_year=2026))
        self.assertTrue(plan["atp_players.csv"])
        self.assertTrue(plan["atp_matches_2024.csv"])          # older seasons must exist
        self.assertFalse(plan["atp_matches_2026.csv"])         # current season may not exist yet
        self.assertIn("atp_matches_qual_chall_2025.csv", plan)


if __name__ == "__main__":
    unittest.main()
