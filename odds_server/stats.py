"""Player stats from Jeff Sackmann's open tennis datasets (ATP + WTA).

The original GitHub repos (JeffSackmann/tennis_atp, tennis_wta) were taken down
in 2026, so by default the files come from a public archive of them on Hugging
Face (a snapshot from mid-2026). Point STATS_ATP_URL / STATS_WTA_URL in .env at
any other copy with the same file names to use fresher data.
Licence: CC BY-NC-SA 4.0 (non-commercial, attribution required). The CSVs are
downloaded to your computer and are not part of this repository.

Two steps:
  1. download(...)     fetch the CSVs into a local folder
  2. build_index(...)  squash them into one small JSON per tour, so the web app
                       loads instantly instead of re-reading millions of rows

Then Stats(index_path) answers questions: find a player by (fuzzy) name, their
profile with current and career-high rank, last N matches and head-to-head.
"""
import csv
import difflib
import json
import os
import re
import time
import unicodedata
import urllib.error
import urllib.request
from datetime import date

ARCHIVE = "https://huggingface.co/datasets/Aneeshers/tennis-sackmann-archive/resolve/main/"
BASE_URLS = {"atp": ARCHIVE + "atp/", "wta": ARCHIVE + "wta/"}
# lower-tier events (qualifying, Challengers / ITF) make "last 10" accurate for players outside the top 100
LOWER_TIER = {"atp": "atp_matches_qual_chall_%d.csv", "wta": "wta_matches_qual_itf_%d.csv"}

ROUND_ORDER = {"Q1": 1, "Q2": 2, "Q3": 3, "Q4": 4, "R128": 10, "R64": 11, "R32": 12, "R16": 13,
               "1R": 10, "2R": 11, "3R": 12, "4R": 13, "RR": 14, "QF": 15, "SF": 16, "BR": 17, "F": 18}


class StatsError(Exception):
    pass


# --------------------------------------------------------------------------- download
def file_plan(tour, since_year, recent_years, decades, this_year=None):
    """List of (filename, required) to download for one tour."""
    this_year = this_year or date.today().year
    files = [("%s_players.csv" % tour, True), ("%s_rankings_current.csv" % tour, False)]
    files += [("%s_rankings_%s.csv" % (tour, d), False) for d in decades]
    for y in range(since_year, this_year + 1):
        files.append(("%s_matches_%d.csv" % (tour, y), y < this_year - 1))
    for y in range(this_year - recent_years + 1, this_year + 1):
        files.append((LOWER_TIER[tour] % y, False))
    return files


def download(tour, data_dir, since_year=2015, recent_years=2, decades=("10s", "20s"),
             base_url=None, log=print, timeout=60):
    """Download the CSVs for one tour. Returns {"ok": [...], "missing": [...]}."""
    base = base_url or BASE_URLS[tour]
    folder = os.path.join(data_dir, tour)
    os.makedirs(folder, exist_ok=True)
    report = {"ok": [], "missing": []}
    for name, required in file_plan(tour, since_year, recent_years, decades):
        url = base + name
        dest = os.path.join(folder, name)
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "odds-server/1.0"})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = resp.read()
            with open(dest + ".part", "wb") as f:
                f.write(data)
            os.replace(dest + ".part", dest)
            report["ok"].append(name)
            log("  got %-40s %6.1f MB" % (name, len(data) / 1e6))
        except urllib.error.HTTPError as e:
            report["missing"].append(name)
            note = "not found" if e.code == 404 else "HTTP %s" % e.code
            log("  skip %-39s (%s%s)" % (name, note, ", keeping old copy" if os.path.exists(dest) else ""))
            if required and not os.path.exists(dest):
                raise StatsError("Could not download %s (HTTP %s). Check STATS_%s_URL in .env." % (name, e.code, tour.upper()))
        except urllib.error.URLError as e:
            raise StatsError("Could not reach %s: %s" % (base, e.reason))
    return report


# --------------------------------------------------------------------------- build index
def _int(v):
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return None


def _read(path):
    with open(path, encoding="utf-8", errors="replace", newline="") as f:
        yield from csv.DictReader(f)


def build_index(tour, data_dir, out_path=None):
    """Combine the downloaded CSVs into one compact JSON index. Returns its path."""
    folder = os.path.join(data_dir, tour)
    if not os.path.isdir(folder):
        raise StatsError("No %s data yet. Run: py update_stats.py" % tour.upper())
    names = sorted(os.listdir(folder))

    players = {}
    p_file = os.path.join(folder, "%s_players.csv" % tour)
    if not os.path.exists(p_file):
        raise StatsError("%s is missing. Run: py update_stats.py" % os.path.basename(p_file))
    for r in _read(p_file):
        pid = r.get("player_id")
        if not pid:
            continue
        name = ("%s %s" % (r.get("name_first", ""), r.get("name_last", ""))).strip()
        players[pid] = {"name": name, "hand": r.get("hand") or "", "dob": _int(r.get("dob")),
                        "ioc": r.get("ioc") or "", "ht": _int(r.get("height"))}

    # rankings: latest week = current rank; best rank ever seen = career high
    latest_date, current, best = 0, {}, {}
    first_rank_date = None
    for n in names:
        if not re.match(r"%s_rankings_.*\.csv$" % tour, n):
            continue
        for r in _read(os.path.join(folder, n)):
            d, rank, pid = _int(r.get("ranking_date")), _int(r.get("rank")), r.get("player")
            if not d or not rank or not pid:
                continue
            first_rank_date = d if first_rank_date is None else min(first_rank_date, d)
            if d > latest_date:
                latest_date, current = d, {}
            if d == latest_date:
                current[pid] = (rank, _int(r.get("points")))
            b = best.get(pid)
            if b is None or rank < b[0] or (rank == b[0] and d < b[1]):
                best[pid] = (rank, d)

    matches, data_through = [], 0
    for n in names:
        if not (re.match(r"%s_matches_\d{4}\.csv$" % tour, n) or re.match(r"%s_matches_qual_.*\.csv$" % tour, n)):
            continue
        for r in _read(os.path.join(folder, n)):
            d, w, l = _int(r.get("tourney_date")), r.get("winner_id"), r.get("loser_id")
            if not d or not w or not l:
                continue
            data_through = max(data_through, d)
            for pid, key in ((w, "winner"), (l, "loser")):
                if pid not in players:
                    players[pid] = {"name": r.get(key + "_name", ""), "hand": r.get(key + "_hand", ""),
                                    "dob": None, "ioc": r.get(key + "_ioc", ""), "ht": None}
            matches.append([d, r.get("tourney_name", ""), r.get("surface", ""), r.get("tourney_level", ""),
                            r.get("round", ""), _int(r.get("match_num")) or 0, w, l, r.get("score", ""),
                            _int(r.get("winner_rank")), _int(r.get("loser_rank"))])
    # results newer than the dataset, read from Wikipedia draw pages by update_stats.py
    wiki_through = None
    wiki_file = os.path.join(data_dir, "%s_wiki_matches.json" % tour)
    if os.path.exists(wiki_file):
        with open(wiki_file, encoding="utf-8") as f:
            wiki = json.load(f)
        added, wiki_through = merge_wiki_matches(players, matches, wiki.get("matches", []))
        data_through = max(data_through, wiki_through or 0)
    matches.sort(key=lambda m: (m[0], ROUND_ORDER.get(m[4], 0), m[5]))

    keep = set(current) | {m[6] for m in matches} | {m[7] for m in matches}
    out_players = {}
    for pid in keep:
        p = players.get(pid)
        if not p:
            continue
        p = dict(p)
        if pid in current:
            p["rank"], p["points"] = current[pid]
        if pid in best:
            p["best"], p["best_date"] = best[pid]
        out_players[pid] = p

    index = {
        "tour": tour,
        "built": time.time(),
        "rankings_date": latest_date or None,
        "rankings_since": first_rank_date,
        "data_through": data_through or None,
        "wiki_through": wiki_through,
        "players": out_players,
        "matches": matches,
    }
    out_path = out_path or os.path.join(data_dir, "%s_index.json" % tour)
    with open(out_path + ".part", "w", encoding="utf-8") as f:
        json.dump(index, f, separators=(",", ":"))
    os.replace(out_path + ".part", out_path)
    return out_path


def dataset_through(tour, data_dir):
    """Latest tournament date in the downloaded CSVs (yyyymmdd), without building the whole index."""
    folder = os.path.join(data_dir, tour)
    files = sorted(n for n in os.listdir(folder) if re.match(r"%s_matches_(qual_\w+_)?\d{4}\.csv$" % tour, n))
    latest_year = max((int(re.search(r"(\d{4})\.csv$", n).group(1)) for n in files), default=None)
    best = 0
    for n in files:
        if latest_year and n.endswith("%d.csv" % latest_year):
            for r in _read(os.path.join(folder, n)):
                best = max(best, _int(r.get("tourney_date")) or 0)
    return best or None


def merge_wiki_matches(players, matches, wiki_matches):
    """Add Wikipedia results to `matches` (in place), skipping ones the dataset already has.

    Names are matched to dataset players; unknown names become new "wiki:" players.
    Returns (number added, latest date added).
    """
    names = NameIndex({pid: p["name"] for pid, p in players.items()})
    pair_dates = {}
    for m in matches:
        pair_dates.setdefault(frozenset((m[6], m[7])), []).append(m[0])

    def pid_for(name):
        pid, _ = names.find(name)
        if pid:
            return pid
        pid = "wiki:" + normalize(name).replace(" ", "_")
        if pid not in players:
            players[pid] = {"name": name, "hand": "", "dob": None, "ioc": "", "ht": None}
            names.add(pid, name)
        return pid

    def days(d):
        s = str(d)
        return date(int(s[:4]), int(s[4:6]), int(s[6:8])).toordinal()

    added, latest, seen = 0, None, set()
    for i, wm in enumerate(wiki_matches):
        w, l = pid_for(wm["winner"]), pid_for(wm["loser"])
        if w == l:
            continue
        key = frozenset((w, l))
        # Duplicate of an archive match: same two players in the same tournament week. Only the
        # archive is checked (pair_dates is never extended with Wikipedia rows), and the window is
        # a few days, because the same players often meet again a couple of weeks later
        # (e.g. Cincinnati 4R and US Open 4R, three weeks apart).
        if any(abs(days(d) - days(wm["date"])) <= 6 for d in pair_dates.get(key, [])):
            continue
        dup = (key, wm["date"], wm["round"])
        if dup in seen:  # listed twice on Wikipedia (e.g. main page and a sub-page)
            continue
        seen.add(dup)
        matches.append([wm["date"], wm["tournament"], wm.get("surface", ""), "wiki", wm["round"], 1000 + i,
                        w, l, wm["score"], None, None])
        added += 1
        latest = max(latest or 0, wm["date"])
    return added, latest


class NameIndex:
    """Match player names despite accents, typos and swapped name order."""

    def __init__(self, names_by_id, prefer=None):
        self.exact, self.sorted_tokens = {}, {}
        self.prefer = prefer or (lambda pids: pids[0])
        for pid, name in names_by_id.items():
            self.add(pid, name)

    def add(self, pid, name):
        n = normalize(name)
        if not n:
            return
        self.exact.setdefault(n, []).append(pid)
        self.sorted_tokens.setdefault(" ".join(sorted(n.split())), []).append(pid)

    def find(self, name):
        """Return (player_id, how) or (None, None). how: exact | reordered | fuzzy."""
        n = normalize(name)
        if not n:
            return None, None
        if n in self.exact:
            return self.prefer(self.exact[n]), "exact"
        key = " ".join(sorted(n.split()))
        if key in self.sorted_tokens:  # e.g. "Shi Han" vs "Han Shi"
            return self.prefer(self.sorted_tokens[key]), "reordered"
        close = difflib.get_close_matches(n, list(self.exact), n=1, cutoff=0.85)
        if close:
            return self.prefer(self.exact[close[0]]), "fuzzy"
        return None, None


# --------------------------------------------------------------------------- queries
def normalize(name):
    """'Leylah Fernández' -> 'leylah fernandez'; drops punctuation, accents and extra spaces."""
    s = unicodedata.normalize("NFKD", name or "")
    s = "".join(c for c in s if not unicodedata.combining(c)).lower()
    s = re.sub(r"[^a-z ]+", " ", s.replace("-", " "))
    return " ".join(s.split())


def _ymd(d):
    if not d:
        return None
    s = str(d)
    return "%s-%s-%s" % (s[:4], s[4:6], s[6:8])


class Stats:
    def __init__(self, index_path):
        with open(index_path, encoding="utf-8") as f:
            self.ix = json.load(f)
        self.players = self.ix["players"]
        self.by_player = {}
        for i, m in enumerate(self.ix["matches"]):
            self.by_player.setdefault(m[6], []).append(i)
            self.by_player.setdefault(m[7], []).append(i)
        self.names = NameIndex({pid: p["name"] for pid, p in self.players.items()}, prefer=self._pick)

    def _pick(self, pids):
        """Several players can share a name; prefer the ranked / most active one."""
        return max(pids, key=lambda p: (self.players[p].get("rank") is not None,
                                        -(self.players[p].get("rank") or 10 ** 6),
                                        len(self.by_player.get(p, []))))

    def find(self, name):
        """Return (player_id, how) or (None, None). how: exact | reordered | fuzzy."""
        return self.names.find(name)

    def _row(self, m, pid):
        won = m[6] == pid
        opp = m[7] if won else m[6]
        return {
            "date": _ymd(m[0]), "tournament": m[1], "surface": m[2], "level": m[3], "round": m[4],
            "opponent": self.players.get(opp, {}).get("name", "?"),
            "opponent_rank": m[10] if won else m[9],
            "result": "W" if won else "L", "score": m[8],
            "source": "wikipedia" if m[3] == "wiki" else "dataset",
        }

    def profile(self, pid, last=10):
        p = self.players[pid]
        dob = p.get("dob")
        age = None
        if dob:
            b, t = str(dob), date.today()
            try:
                age = t.year - int(b[:4]) - ((t.month, t.day) < (int(b[4:6]), int(b[6:8])))
            except ValueError:
                age = None
        recent = [self._row(self.ix["matches"][i], pid) for i in reversed(self.by_player.get(pid, [])[-last:])]
        return {
            "id": pid, "name": p["name"], "country": p.get("ioc"), "age": age,
            "plays": {"R": "Right-handed", "L": "Left-handed"}.get(p.get("hand"), None),
            "height_cm": p.get("ht"),
            "rank": p.get("rank"), "points": p.get("points"),
            "career_high": p.get("best"), "career_high_date": _ymd(p.get("best_date")),
            "last_matches": recent,
            "form": "".join(r["result"] for r in recent),
        }

    def head_to_head(self, a, b):
        meetings = [self.ix["matches"][i] for i in self.by_player.get(a, [])
                    if {self.ix["matches"][i][6], self.ix["matches"][i][7]} == {a, b}]
        rows = [self._row(m, a) for m in reversed(meetings)]
        return {"wins": sum(r["result"] == "W" for r in rows),
                "losses": sum(r["result"] == "L" for r in rows),
                "meetings": rows}

    def matchup(self, name1, name2, last=10):
        out = {"tour": self.ix["tour"], "data_through": _ymd(self.ix.get("data_through")),
               "rankings_date": _ymd(self.ix.get("rankings_date")),
               "rankings_since": _ymd(self.ix.get("rankings_since")),
               "wiki_through": _ymd(self.ix.get("wiki_through")), "players": [], "h2h": None}
        ids = []
        for name in (name1, name2):
            pid, how = self.find(name)
            ids.append(pid)
            out["players"].append(dict(self.profile(pid, last), query=name, match=how) if pid
                                  else {"query": name, "match": None})
        if ids[0] and ids[1]:
            out["h2h"] = self.head_to_head(ids[0], ids[1])
        return out


def tour_from_sport_key(key):
    """'tennis_wta_ningbo_open' -> 'wta'; anything else with 'atp' -> 'atp'."""
    k = (key or "").lower()
    return "wta" if "_wta_" in k or k.startswith("tennis_wta") else "atp" if "atp" in k else None
