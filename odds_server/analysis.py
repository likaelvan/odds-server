"""Player profiles and head-to-head analysis, built on the Stats index.

Everything here is computed from the match list in the index (archive + Wikipedia):
records by season / last 52 weeks / surface / tournament level, titles and finals,
recent form and streaks, and ranking history. Pure functions, no network.
"""
import re
from datetime import date, timedelta

from .stats import _ymd, normalize

# ---------------------------------------------------------------- categories
LEVELS = [  # (key, label) in display order
    ("slam", "Grand Slam"), ("finals", "Tour Finals"), ("1000", "1000"), ("500", "500"), ("250", "250"),
    ("tour", "Tour 250/500"), ("challenger", "Challenger / 125"), ("itf", "ITF"), ("team", "Team events"),
    ("qualifying", "Qualifying"), ("other", "Other"),
]
LEVEL_LABEL = dict(LEVELS)
SURFACES = ["Hard", "Clay", "Grass", "Carpet"]


def level_group(tour, code, rnd):
    """Map the archive's / Wikipedia's tournament codes to one display category.

    Archive ATP: G, M (1000), A (250 and 500 together), F, D (Davis Cup), C (Challenger).
    Archive WTA: G, PM (1000), P (500), I (250), F, D (BJK Cup), C (WTA 125), 15/35/50/75/100 (ITF).
    Wikipedia: G, F, 1000, 500, 250, 125. Qualifying rounds (Q1..) are their own category."""
    if re.match(r"Q\d", rnd or ""):  # Q1, Q2, Q3 (not QF!)
        return "qualifying"
    c = (code or "").upper()
    if c == "G":
        return "slam"
    if c == "F":
        return "finals"
    if c in ("M", "PM", "1000"):
        return "1000"
    if c in ("P", "500"):
        return "500"
    if c in ("I", "250"):
        return "250"
    if c == "A":
        return "tour"
    if c in ("C", "125"):
        return "challenger"
    if c == "D":
        return "team"
    if c[:2].isdigit():  # "15", "35+H", "100" ...
        return "itf"
    return "other"


def _surface(s):
    s = (s or "").strip().capitalize()
    return s if s in SURFACES else ""


def _played(m):
    """Walkovers aren't matches played; leave them out of records."""
    return "W/O" not in (m[8] or "").upper()


def _to_date(d):
    s = str(d)
    return date(int(s[:4]), int(s[4:6]), int(s[6:8]))


class _Rec:
    def __init__(self):
        self.w = self.l = 0

    def add(self, won):
        if won:
            self.w += 1
        else:
            self.l += 1

    def out(self):
        n = self.w + self.l
        return {"w": self.w, "l": self.l, "pct": round(self.w / n, 3) if n else None}


# ---------------------------------------------------------------- search
def search(st, query, limit=10):
    """Players whose name matches `query` (accents/case ignored), best known first."""
    q = normalize(query)
    if len(q) < 2:
        return []
    out = []
    for pid, p in st.players.items():
        n = normalize(p.get("name", ""))
        if not n:
            continue
        tokens = n.split()
        if n.startswith(q) or any(t.startswith(q) for t in tokens):
            score = 0
        elif q in n:
            score = 1
        else:
            continue
        idx = st.by_player.get(pid, [])
        last = st.ix["matches"][idx[-1]][0] if idx else 0
        out.append((score, p.get("rank") or 10 ** 6, -last, p["name"], pid, last))
    out.sort()
    return [{"id": pid, "name": name, "country": st.players[pid].get("ioc") or "",
             "rank": st.players[pid].get("rank"), "last_match": _ymd(last) if last else None}
            for _, _, _, name, pid, last in out[:limit]]


# ---------------------------------------------------------------- profile
def player_page(st, pid, recent=20):
    """Everything the Players tab shows for one player."""
    tour = st.ix["tour"]
    p = st.players[pid]
    base = st.profile(pid, last=recent)
    matches = [st.ix["matches"][i] for i in st.by_player.get(pid, [])]
    through = st.ix.get("data_through")
    end = _to_date(through) if through else date.today()
    year_start = date(end.year, 1, 1)
    since_52 = end - timedelta(weeks=52)

    season, last52, overall = _Rec(), _Rec(), _Rec()
    by_surface = {s: {"career": _Rec(), "52w": _Rec()} for s in SURFACES}
    by_level = {k: {"career": _Rec(), "52w": _Rec()} for k, _ in LEVELS}
    titles, finals = [], []
    for m in matches:
        if not _played(m):
            continue
        won = m[6] == pid
        d = _to_date(m[0])
        surf = _surface(m[2])
        lvl = level_group(tour, m[3], m[4])
        recent52 = d >= since_52
        overall.add(won)
        if d >= year_start:
            season.add(won)
        if recent52:
            last52.add(won)
        if surf:
            by_surface[surf]["career"].add(won)
            if recent52:
                by_surface[surf]["52w"].add(won)
        by_level[lvl]["career"].add(won)
        if recent52:
            by_level[lvl]["52w"].add(won)
        if m[4] == "F" and lvl != "qualifying":
            entry = {"date": _ymd(m[0]), "tournament": m[1], "surface": surf, "level": LEVEL_LABEL[lvl],
                     "opponent": st.players.get(m[7] if won else m[6], {}).get("name", "?"), "score": m[8]}
            (titles if won else finals).append(entry)

    # streak: consecutive identical results, newest first (walkovers skipped)
    played = [m for m in matches if _played(m)]
    streak_kind, streak = None, 0
    for m in reversed(played):
        r = "W" if m[6] == pid else "L"
        if streak_kind is None:
            streak_kind = r
        if r != streak_kind:
            break
        streak += 1

    hist = p.get("rh") or []
    history = [{"month": "%d-%02d" % (hist[i] // 100, hist[i] % 100), "rank": hist[i + 1]}
               for i in range(0, len(hist), 2)]

    first = matches[0][0] if matches else None
    return dict(
        base,
        tour=tour,
        data_from=_ymd(first),
        data_through=_ymd(through),
        rankings_date=_ymd(st.ix.get("rankings_date")),
        season={"year": end.year, **season.out()},
        last_52_weeks=last52.out(),
        overall=overall.out(),
        surfaces=[{"surface": s, "career": by_surface[s]["career"].out(), "last_52_weeks": by_surface[s]["52w"].out()}
                  for s in SURFACES if by_surface[s]["career"].w + by_surface[s]["career"].l],
        levels=[{"level": label, "career": by_level[k]["career"].out(), "last_52_weeks": by_level[k]["52w"].out()}
                for k, label in LEVELS if by_level[k]["career"].w + by_level[k]["career"].l],
        titles=list(reversed(titles)),
        finals_lost=list(reversed(finals)),
        streak={"kind": streak_kind, "length": streak} if streak else None,
        form_10="".join(r["result"] for r in base["last_matches"][:10]),
        form_20="".join(r["result"] for r in base["last_matches"][:20]),
        rank_history=history,
    )


# ---------------------------------------------------------------- head-to-head
def h2h_page(st, a, b):
    """Head-to-head record (overall + by surface), every meeting, and both players' key numbers."""
    h = st.head_to_head(a, b)
    surf = {}
    for r in h["meetings"]:
        if "W/O" in (r["score"] or "").upper():
            continue
        s = _surface(r["surface"]) or "Unknown"
        rec = surf.setdefault(s, [0, 0])
        rec[0 if r["result"] == "W" else 1] += 1
    pa, pb = player_page(st, a, recent=10), player_page(st, b, recent=10)

    def summary(p):
        return {k: p.get(k) for k in ("id", "name", "country", "age", "plays", "height_cm", "rank", "points",
                                      "career_high", "career_high_date", "season", "last_52_weeks", "surfaces",
                                      "form_10", "streak")} | {"titles": len(p["titles"]), "finals": len(p["titles"]) + len(p["finals_lost"])}
    return {
        "tour": st.ix["tour"],
        "data_from": min(filter(None, [pa["data_from"], pb["data_from"]]), default=None),
        "data_through": _ymd(st.ix.get("data_through")),
        "wins": h["wins"], "losses": h["losses"],
        "by_surface": [{"surface": s, "wins": w, "losses": l} for s, (w, l) in sorted(surf.items())],
        "meetings": h["meetings"],
        "players": [summary(pa), summary(pb)],
    }

