"""Draw pages come in several shapes on Wikipedia; make sure we read all of them and flag gaps."""
import os
import sys
import unittest
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)

from odds_server import wiki  # noqa: E402
from test_wiki import FakeClient  # noqa: E402

BIG = "2026 Big Open – Women's singles"
SECTION = BIG + " (Section 1)"

FINALS = """==Draw==
===Finals===
{{4TeamBracket-Tennis3
| RD1=Semifinals
| RD2=Final
| RD1-team1='''[[Ann A]]'''
| RD1-score1-1=6
| RD1-score1-2=6
| RD1-team2=[[Bea B]]
| RD1-score2-1=1
| RD1-score2-2=2
| RD1-team3='''[[Cat C]]'''
| RD1-score3-1=6
| RD1-score3-2=6
| RD1-team4=[[Dee D]]
| RD1-score4-1=3
| RD1-score4-2=4
| RD2-team1='''[[Ann A]]'''
| RD2-score1-1=6
| RD2-score1-2=6
| RD2-team2=[[Cat C]]
| RD2-score2-1=0
| RD2-score2-2=0
}}
"""
SLAM_MAIN = FINALS + "===Top half===\n{{:" + SECTION + "}}\n"
SLAM_SECTION = """{{8TeamBracket-Compact-Tennis3
| RD1=Quarterfinals
| RD1-team01='''[[Ann A]]'''
| RD1-score01-1=6
| RD1-score01-2=6
| RD1-team02=[[Eve E]]
| RD1-score02-1=0
| RD1-score02-2=1
}}"""
MAIN_PAGE = """'''2026 Small Open''' was a tournament.
==Singles==
{{4TeamBracket-Tennis3
| RD1=Semifinals
| RD1-team1='''[[Ann A]]'''
| RD1-score1-1=6
| RD1-score1-2=6
| RD1-team2=[[Bea B]]
| RD1-score2-1=1
| RD1-score2-2=2
}}
==Doubles==
{{4TeamBracket-Tennis3
| RD1=Semifinals
| RD1-team1='''[[Ann A]]<br>[[Cat C]]'''
| RD1-score1-1=6
| RD1-team2=[[Bea B]]<br>[[Dee D]]
| RD1-score2-1=1
}}"""


class DrawShapeTests(unittest.TestCase):
    def test_follows_transcluded_sections(self):
        c = FakeClient({BIG: SLAM_MAIN, SECTION: SLAM_SECTION})
        ms, notes = wiki.collect_draw(c, BIG)
        self.assertEqual(len(ms), 4)
        self.assertIn(("QF", "Ann A", "Eve E"), [(m["round"], m["winner"], m["loser"]) for m in ms])
        self.assertTrue(any("Section 1" in n for n in notes))

    def test_follows_plain_links_to_own_subpages(self):
        main = FINALS + "===Top half===\nSee [[" + SECTION + "|Section 1]] and [[" + BIG + " qualifying|qualifying]].\n"
        c = FakeClient({BIG: main, SECTION: SLAM_SECTION})
        ms, _ = wiki.collect_draw(c, BIG)
        self.assertEqual(len([m for m in ms if m["stage"] == "main"]), 4)
        self.assertIn(BIG + " qualifying", c.asked)   # the linked qualifying page is read for Q matches

    def test_redirect_to_main_page_reads_only_singles(self):
        c = FakeClient({"2026 Small Open": MAIN_PAGE})
        c.redirects = {"2026 Small Open – Singles": ("2026 Small Open", "Singles")}
        ms, _ = wiki.collect_draw(c, "2026 Small Open – Singles")
        self.assertEqual([(m["winner"], m["loser"]) for m in ms], [("Ann A", "Bea B")])

    def test_redirect_without_section_still_skips_doubles(self):
        c = FakeClient({"2026 Small Open": MAIN_PAGE})
        c.redirects = {"2026 Small Open – Singles": ("2026 Small Open", None)}
        ms, _ = wiki.collect_draw(c, "2026 Small Open – Singles")
        self.assertEqual(len(ms), 1)

    def test_doubles_cells_are_ignored(self):
        self.assertEqual(wiki.parse_draw(wiki.section_text(MAIN_PAGE, "Doubles")), [])

    def test_coverage(self):
        full = wiki.parse_draw(FINALS)
        self.assertEqual(wiki.coverage(full), "complete")   # 4 players, 3 matches, final played
        self.assertEqual(wiki.coverage(full[:2]), "partial")
        self.assertEqual(wiki.coverage([]), "empty")

    def test_report_flags_gaps(self):
        season = ("=== June ===\n| 8 Jun\n| [[" + BIG + "|S]]\n| [[2026 Empty Open – Singles|S]]\n"
                  "=== October ===\n| 19 Oct\n| [[2026 Live Open – Singles|S]]\n")
        c = FakeClient({"2026 WTA Tour": season, BIG: SLAM_MAIN, SECTION: SLAM_SECTION,
                        "2026 Empty Open – Singles": "Stub page, draw to come.",
                        "2026 Live Open – Singles": SLAM_SECTION})
        results, report = wiki.recent_results(c, "wta", 20260601, today=date(2026, 10, 21), log=lambda *a: None)
        status = {r["title"]: r["status"] for r in report}
        self.assertEqual(status["2026 Empty Open – Singles"], "empty")
        self.assertEqual(status[BIG], "partial")                       # the other quarterfinals are missing
        self.assertEqual(status["2026 Live Open – Singles"], "in progress")
        self.assertEqual(len(results), 5)


if __name__ == "__main__":
    unittest.main()


# Real-world shapes seen on the 2026 season pages
SEASON_REAL = """'''The 2026 tour'''... [[2026 Big Open – Women's singles|won]] the title.<ref>{{cite web|date=16 September 2026}}</ref>
== Schedule ==
===January===
{| class="wikitable"
|- style="vertical-align:top"
| rowspan="2" |Dec 29
| rowspan="2" |[[2026 ASB Classic|ASB]]<br/>Hard – $283,347 – 32S/24Q/16D<br/>[[2026 ASB Classic – Women's singles|Singles]]
|}
===June===
{|class=wikitable
|- style="vertical-align:top"
|rowspan=4|8 Jun||style="background:#fff;" rowspan=2|[[2026 BOSS Open|Stuttgart Open]]<br />ATP 250<br />Grass – €757,320 – 28S/16Q/16D<br />[[2026 BOSS Open – Singles|Singles]] – [[2026 BOSS Open – Doubles|Doubles]] || {{flagicon|USA}} [[Ben Shelton]] <br /> 6–4
|- style="vertical-align:top"
| rowspan="3"|May 25<br/>Jun 1
|style="background:#F3E6D7;" rowspan="3"|[[2026 Big Open|Big]]<br/>Clay – 128S/64D<br/>[[2026 Big Open – Women's singles|Singles]]
|}
== Statistical information ==
[[2026 Other Open – Singles|x]] 1 Jan
"""

DRAW_WITH_QUALIFYING = FINALS + """==Qualifying==
===Seeds===
===First qualifier===
{{4TeamBracket-Tennis3
| RD1=First round
| RD2=Qualifying competition
| RD1-team1='''[[Qual A]]'''
| RD1-score1-1=6
| RD1-score1-2=6
| RD1-team2=[[Qual B]]
| RD1-score2-1=1
| RD1-score2-2=1
}}
==References==
"""


WILDCARD_BRACKET = """{{4TeamBracket-Tennis3
| RD1-team1='''[[Wc A]]'''
| RD1-score1-1=6
| RD1-team2=[[Wc B]]
| RD1-score2-1=0
}}
"""


class RealShapeTests(unittest.TestCase):
    def test_schedule_rows(self):
        pages = wiki.season_draw_pages(FakeClient({"2026 WTA Tour": SEASON_REAL}), "wta", 2026)
        self.assertEqual(pages, [
            ("2026 ASB Classic – Women's singles", 20251229, 32, "Hard", ""),   # season starts in December
            ("2026 BOSS Open – Singles", 20260608, 28, "Grass", "250"),        # "8 Jun" week, ATP 250 on grass
            ("2026 Big Open – Women's singles", 20260525, 128, "Clay", ""),    # "May 25", not the intro's date
        ])

    def test_qualifying_matches_are_labelled_and_kept_apart(self):
        ms, _ = wiki.collect_draw(FakeClient({"T – Singles": DRAW_WITH_QUALIFYING}), "T – Singles")
        main = [m for m in ms if m["stage"] == "main"]
        quali = [m for m in ms if m["stage"] == "qualifying"]
        self.assertEqual(len(main), 3)
        self.assertEqual([(m["round"], m["winner"], m["loser"]) for m in quali], [("Q1", "Qual A", "Qual B")])
        self.assertEqual(wiki.coverage(main, 4), "complete")   # qualifying doesn't upset the main-draw check

    def test_separate_qualifying_page(self):
        main_page = FINALS + "{{main|" + BIG + " qualifying}}"
        q_page = ("==Draw==\n===First qualifier===\n" + DRAW_WITH_QUALIFYING.split("===First qualifier===")[1]
                  + "==Qualifying wild card challenge==\n" + WILDCARD_BRACKET)
        c = FakeClient({BIG: main_page, BIG + " qualifying": q_page})
        ms, notes = wiki.collect_draw(c, BIG)
        quali = [m for m in ms if m["stage"] == "qualifying"]
        self.assertEqual([m["winner"] for m in quali], ["Qual A"])   # wild-card play-off left out
        self.assertTrue(any("qualifying from" in n for n in notes))

    def test_coverage_uses_draw_size(self):
        full = wiki.parse_draw(FINALS)
        self.assertEqual(wiki.coverage(full, 4), "complete")
        self.assertEqual(wiki.coverage(full[:2], 4), "partial")   # no final yet
