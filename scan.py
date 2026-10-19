"""Scan tennis matches for pricing gaps between bookmakers, from the terminal.

Examples:
  py scan.py --list                      # active tournaments (free, no credits)
  py scan.py                             # scan every active tournament
  py scan.py -t tennis_atp_paris         # scan one tournament
  py scan.py --amount 2000 --top 20
"""
import argparse
import os
import sys
from datetime import datetime, timezone

from odds_server.core import allocate
from odds_server.env import load_env, setting
from odds_server.odds_api import OddsAPI, OddsAPIError

ROOT = os.path.dirname(os.path.abspath(__file__))


def local_time(iso):
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        return dt.astimezone().strftime("%a %d %b %H:%M")
    except Exception:
        return iso or ""


def main():
    load_env(os.path.join(ROOT, ".env"))
    p = argparse.ArgumentParser(description="Compare tennis match-winner odds across bookmakers.")
    p.add_argument("--list", action="store_true", help="only list active tournaments (free)")
    p.add_argument("-t", "--tournament", action="append", help="tournament key; repeat for several")
    p.add_argument("--regions", default=setting("ODDS_REGIONS", "eu,uk"),
                   help="bookmaker regions: us, uk, eu, au (each costs 1 credit per tournament)")
    p.add_argument("--amount", type=float, default=1000, help="total units for the equal-return allocation")
    p.add_argument("--round", type=float, default=10, help="round allocations to this many units")
    p.add_argument("--top", type=int, default=15, help="how many matches to show")
    p.add_argument("--refresh", action="store_true", help="ignore the cache and fetch fresh odds")
    args = p.parse_args()

    try:
        api = OddsAPI(setting("ODDS_API_KEY"), cache_dir=os.path.join(ROOT, ".cache"),
                      cache_minutes=setting("CACHE_MINUTES", "10"))
        tours = api.tennis_tournaments()
    except OddsAPIError as e:
        sys.exit("Error: %s" % e)

    if args.list:
        if not tours:
            print("No tennis tournaments are active right now.")
        for t in tours:
            print("%-32s %s" % (t["key"], t["title"]))
        return

    keys = args.tournament or [t["key"] for t in tours]
    if not keys:
        sys.exit("No tennis tournaments are active right now.")
    cost = len(keys) * len(args.regions.split(","))
    print("Scanning %d tournament(s) in regions %s (up to %d credits, less if cached)...\n"
          % (len(keys), args.regions, cost))

    matches = []
    for key in keys:
        try:
            data = api.tennis_odds(key, args.regions, force=args.refresh)
            matches.extend(data["matches"])
        except OddsAPIError as e:
            print("  %s: %s" % (key, e))

    rated = [m for m in matches if m["analysis"]["ok"]]
    rated.sort(key=lambda m: m["analysis"]["margin"], reverse=True)
    gaps = [m for m in rated if m["analysis"]["gap"]]
    print("%d matches with odds, %d with a pricing gap.\n" % (len(rated), len(gaps)))

    for m in rated[: args.top]:
        a = m["analysis"]
        b0, b1 = a["best"]
        tag = "GAP +%.2f%%" % (a["margin"] * 100) if a["gap"] else "margin %.2f%%" % (a["margin"] * 100)
        print("%-14s %s v %s  [%s, %s, %d books]" % (
            tag, m["players"][0], m["players"][1], m["tournament"], local_time(m["commence"]), len(m["books"])))
        print("               best: %s %.2f @ %s | %s %.2f @ %s" % (
            m["players"][0], b0["odds"], b0["book"], m["players"][1], b1["odds"], b1["book"]))
        if a["gap"]:
            amounts, _, surplus = allocate(a["best"], args.amount, args.round)
            print("               equal-return allocation: %.0f on %s, %.0f on %s -> surplus +%.2f"
                  % (amounts[0], m["players"][0], amounts[1], m["players"][1], surplus))
        print()

    c = api.credit_status(args.regions)
    if c["known"]:
        print("Credits: %d used, %d left of %d (%.0f%% left, about %d more tournament loads at %d per load)"
              % (c["used"], c["remaining"], c["total"], c["pct_left"] * 100, c["loads_left"], c["per_load"]))
    print("Prices can change quickly; treat this as a snapshot.")


if __name__ == "__main__":
    main()
