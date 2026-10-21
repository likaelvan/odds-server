"""Download player data and build the local stats index.

  py update_stats.py                 # ATP and WTA
  py update_stats.py --tour wta      # just one tour
  py update_stats.py --no-wiki       # skip the Wikipedia catch-up
  py update_stats.py --build-only    # rebuild the index from files you already have

Two sources:
  1. Jeff Sackmann's ATP/WTA datasets (archived mid-2026; CC BY-NC-SA 4.0): history,
     head-to-head, career highs.
  2. Wikipedia (MediaWiki API, CC BY-SA 4.0): every tournament draw since that archive,
     so recent form and head-to-head stay current. Run this weekly to stay up to date.
"""
import argparse
import json
import os
import sys
import time
from datetime import date, timedelta

from odds_server.env import load_env, setting
from odds_server.stats import Stats, StatsError, build_index, dataset_through, download

ROOT = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(ROOT, ".data")


def wiki_catch_up(tour, since):
    """Fetch results newer than the dataset from Wikipedia and save them for build_index."""
    from odds_server.wiki import WikiClient, recent_results
    client = WikiClient(os.path.join(ROOT, ".cache", "wiki"))
    results, report = recent_results(client, tour, since)
    with open(os.path.join(DATA, "%s_wiki_matches.json" % tour), "w", encoding="utf-8") as f:
        json.dump({"fetched": time.time(), "since": since, "matches": results, "report": report}, f)
    print("  %d results from Wikipedia" % len(results))


def main():
    load_env(os.path.join(ROOT, ".env"))
    p = argparse.ArgumentParser(description="Download tennis player data and build the stats index.")
    p.add_argument("--tour", choices=["atp", "wta", "both"], default="both")
    p.add_argument("--since", type=int, default=int(setting("STATS_SINCE", "2015") or 2015),
                   help="first season of match results to download (used for head-to-head)")
    p.add_argument("--decades", default=setting("STATS_RANKING_DECADES", "10s,20s"),
                   help="ranking history to download for career-high rank, e.g. 00s,10s,20s")
    p.add_argument("--build-only", action="store_true", help="skip all downloads")
    p.add_argument("--no-wiki", action="store_true", help="skip the Wikipedia catch-up")
    p.add_argument("--skip-archive", action="store_true",
                   help="reuse the archive files you already have (they don't change); only refresh Wikipedia")
    args = p.parse_args()

    tours = ["atp", "wta"] if args.tour == "both" else [args.tour]
    failed = False
    for tour in tours:
        print("\n%s" % tour.upper())
        t0 = time.time()
        try:
            have_archive = os.path.exists(os.path.join(DATA, tour, "%s_players.csv" % tour))
            if not args.build_only and not (args.skip_archive and have_archive):
                download(tour, DATA, since_year=args.since,
                         decades=[d.strip() for d in args.decades.split(",") if d.strip()],
                         base_url=setting("STATS_%s_URL" % tour.upper()) or None)
            if not args.build_only and not args.no_wiki:
                through = dataset_through(tour, DATA)
                if through:
                    d = date(through // 10000, through // 100 % 100, through % 100) - timedelta(days=14)
                    try:
                        wiki_catch_up(tour, int(d.strftime("%Y%m%d")))
                    except Exception as e:  # Wikipedia is a bonus: keep going without it
                        print("  Wikipedia catch-up skipped: %s" % e)
            path = build_index(tour, DATA)
            s = Stats(path)
            info = s.matchup("", "")
            print("  index ready: %d players, %d matches, results through %s (archive rankings from %s) (%.0fs)"
                  % (len(s.players), len(s.ix["matches"]), info["data_through"], info["rankings_date"],
                     time.time() - t0))
        except StatsError as e:
            failed = True
            print("  error: %s" % e)
    if failed:
        sys.exit(1)
    print("\nDone. Restart the app (start.bat) to see player stats.")


if __name__ == "__main__":
    main()
