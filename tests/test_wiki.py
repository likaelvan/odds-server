"""Tests for the Wikipedia parsers, using small wikitext samples in Wikipedia's formats."""
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from odds_server import wiki  # noqa: E402
from odds_server.stats import Stats, build_index  # noqa: E402
from test_stats import make_dataset  # noqa: E402

INFOBOX = """{{Short description|Canadian tennis player}}
{{Infobox tennis biography
| name = Leylah Fernandez
| country = {{CAN}}
| plays = Left-handed (two-handed backhand)
| highestsinglesranking = No. 13 (22 August 2022)
| currentsinglesranking = No. 24 (13 October 2026)<ref>{{cite web|title=Rankings|url=https://example.org}}</ref>
}}
'''Leylah Annie Fernandez''' is a Canadian professional tennis player."""

DRAW = """==Draw==
{{Tennis tournament draw key}}
===Finals===
{{4TeamBracket-Tennis3
| RD1=Semifinals
| RD2=Final
| RD1-seed1=1
| RD1-team1={{flagicon|CAN}} '''[[Leylah Fernandez]]'''
| RD1-score1-1=7<sup>7</sup>
| RD1-score1-2=6
| RD1-seed2=
| RD1-team2={{flagicon|BEL}} [[Elise Mertens|E Mertens]]
| RD1-score2-1=6<sup>5</sup>
| RD1-score2-2=4
| RD1-team3={{flagicon|ROU}} '''[[Sorana Cîrstea]]'''
| RD1-score3-1=6
| RD1-score3-2=2
| RD1-team4={{flagicon|CHN}} [[Shi Han (tennis)|H Shi]]
| RD1-score4-1=1
| RD1-score4-2=0<sup>r</sup>
| RD2-team1={{flagicon|CAN}} [[Leylah Fernandez]]
| RD2-score1-1=3
| RD2-score1-2=6
| RD2-score1-3=4
| RD2-team2={{flagicon|ROU}} '''[[Sorana Cîrstea]]'''
| RD2-score2-1=6
| RD2-score2-2=3
| RD2-score2-3=6
}}
===Top half===
{{8TeamBracket-Compact-Tennis3
| RD1=First round
| RD1-team01={{flagicon|CAN}} '''[[Leylah Fernandez|L Fernandez]]'''
| RD1-score01-1=6
| RD1-score01-2=6
| RD1-team02=Bye
| RD1-team03={{flagicon|USA}} [[New Player]]
| RD1-score03-1=w/o
| RD1-team04={{flagicon|BEL}} '''[[Elise Mertens|E Mertens]]'''
}}"""

SEASON = """== Schedule ==
=== June ===
{| class="wikitable"
|-
| rowspan="2" | 1 Jun
| [[2026 French Open – Women's singles|Singles]]
|-
=== October ===
{| class="wikitable"
|-
| rowspan="2" | 12 Oct
| [[2026 Ningbo Open|Ningbo Open]]<br>[[2026 Ningbo Open – Singles|Singles]] – [[2026 Ningbo Open – Doubles|Doubles]]
| [[2026 Ningbo Open – Singles qualifying|Qualifying]]
|-
| [[2026 Japan Women's Open – Singles|Singles]]
|}"""


class FakeClient:
    def __init__(self, pages):
        self.p = pages
        self.asked = []

    def pages_full(self, titles, max_age_hours=24):
        """redirects: {title: (target title, section)} to mimic Wikipedia redirects."""
        self.asked += titles
        out = {}
        for t in titles:
            target, frag = getattr(self, "redirects", {}).get(t, (t, None))
            out[t] = {"title": target, "text": self.p.get(target), "fragment": frag}
        return out

    def pages(self, titles, max_age_hours=24):
        return {t: p["text"] for t, p in self.pages_full(titles, max_age_hours).items()}


class WikiParsingTests(unittest.TestCase):
    def test_infobox(self):
        info = wiki.parse_infobox(INFOBOX)
        self.assertEqual(info, {"rank": 24, "rank_date": 20261013, "best": 13, "best_date": 20220822})
        self.assertIsNone(wiki.parse_infobox("{{Infobox football biography|name=X}}"))

    def test_rank_formats(self):
        self.assertEqual(wiki._rank_and_date("No. 1 (October 9, 2023)"), (1, 20231009))
        self.assertEqual(wiki._rank_and_date("No. 5 ({{dts|2024|6|10}})"), (5, 20240610))

    def test_draw(self):
        ms = wiki.parse_draw(DRAW)
        by = {(m["round"], m["winner"]): m for m in ms}
        sf = by[("SF", "Leylah Fernandez")]
        self.assertEqual((sf["loser"], sf["score"]), ("Elise Mertens", "7-6(5) 6-4"))
        ret = by[("SF", "Sorana Cîrstea")]
        self.assertEqual((ret["loser"], ret["score"]), ("Shi Han", "6-1 2-0 RET"))
        final = by[("F", "Sorana Cîrstea")]
        self.assertEqual(final["score"], "6-3 3-6 6-4")
        wo = by[("1R", "Elise Mertens")]
        self.assertEqual(wo["score"], "W/O")
        self.assertNotIn("Bye", [m["loser"] for m in ms])
        self.assertEqual(len(ms), 4)

    def test_season_pages(self):
        c = FakeClient({"2026 WTA Tour": SEASON})
        pages = wiki.season_draw_pages(c, "wta", 2026)
        self.assertEqual(pages, [("2026 French Open – Women's singles", 20260601, None),
                                 ("2026 Ningbo Open – Singles", 20261012, None),
                                 ("2026 Japan Women's Open – Singles", 20261012, None)])

    def test_live_rankings(self):
        c = FakeClient({"Leylah Fernández": None, "Leylah Fernandez": INFOBOX})
        out = {"rankings_date": "2026-06-08", "players": [
            {"match": "exact", "name": "Leylah Fernández", "query": "Leylah Fernandez", "rank": 30,
             "points": 1500, "career_high": 15, "career_high_date": "2022-01-10"},
            {"match": None, "query": "Unknown"}]}
        wiki.add_live_rankings(out, c)
        p = out["players"][0]
        self.assertEqual((p["rank"], p["rank_date"], p["rank_source"], p["points"]), (24, "2026-10-13", "wikipedia", None))
        self.assertEqual((p["career_high"], p["career_high_date"]), (13, "2022-08-22"))


class MergeTests(unittest.TestCase):
    def test_wiki_results_merge_into_index(self):
        import json
        tmp = tempfile.mkdtemp()
        try:
            make_dataset(tmp)
            results = [dict(m, date=20261012, tournament="Ningbo Open", source="x") for m in wiki.parse_draw(DRAW)]
            # a duplicate of a dataset match (same pair, same week) must be skipped
            results.append({"round": "R16", "winner": "Leylah Fernandez", "loser": "Elise Mertens",
                            "score": "7-6(5) 6-4", "date": 20261012, "tournament": "Ningbo", "source": "x"})
            with open(os.path.join(tmp, "wta_wiki_matches.json"), "w", encoding="utf-8") as f:
                json.dump({"matches": results}, f)
            s = Stats(build_index("wta", tmp))
            fer = s.profile("1")
            self.assertEqual(fer["last_matches"][0]["result"], "L")            # lost the final
            self.assertEqual(fer["last_matches"][0]["source"], "wikipedia")
            self.assertEqual(fer["last_matches"][0]["round"], "F")
            h2h = s.head_to_head("1", "2")
            self.assertEqual(h2h["wins"], 1)    # Ningbo SF from Wikipedia deduped against dataset R16 same week
            self.assertEqual(s.find("New Player")[0], "wiki:new_player")
        finally:
            shutil.rmtree(tmp)


if __name__ == "__main__":
    unittest.main()
