"""Fresh tennis data from Wikipedia, via the official MediaWiki API.

Wikipedia allows automated reading through its API as long as clients identify
themselves (User-Agent), go slowly and cache. Content is CC BY-SA 4.0.

What we read:
  * Player pages: the "Infobox tennis biography" holds current and career-high
    singles ranking (kept up to date weekly by editors).
  * Season pages ("2026 WTA Tour", "2026 ATP Tour"): the schedule links to every
    tournament's singles draw page.
  * Draw pages ("2026 Ningbo Open – Singles"): bracket templates with every result.

Parsing uses mwparserfromhell (pip install -r requirements.txt).
"""
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date

API = "https://en.wikipedia.org/w/api.php"
USER_AGENT = "odds-server/1.0 (personal tennis stats project; https://github.com/likaelvan/odds-server)"
MONTHS = {m: i for i, m in enumerate(["january", "february", "march", "april", "may", "june", "july", "august",
                                       "september", "october", "november", "december"], 1)}
MON3 = {k[:3]: v for k, v in MONTHS.items()}


class WikiError(Exception):
    pass


def _mw():
    try:
        import mwparserfromhell
        return mwparserfromhell
    except ImportError:
        raise WikiError("Missing package mwparserfromhell. Run setup.bat (or: pip install -r requirements.txt).")


# --------------------------------------------------------------------------- client
class WikiClient:
    """Polite MediaWiki API client: identifies itself, waits between calls, caches to disk."""

    def __init__(self, cache_dir, min_interval=1.0, timeout=30):
        self.cache_dir = cache_dir
        self.min_interval = min_interval
        self.timeout = timeout
        self._last = 0.0
        os.makedirs(cache_dir, exist_ok=True)

    def _get(self, params):
        params = dict(params, format="json", formatversion="2", maxlag="5")
        url = API + "?" + urllib.parse.urlencode(params)
        for attempt in range(4):
            wait = self.min_interval - (time.time() - self._last)
            if wait > 0:
                time.sleep(wait)
            self._last = time.time()
            try:
                req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept-Encoding": "identity"})
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
            except urllib.error.HTTPError as e:
                if e.code in (429, 503) and attempt < 3:
                    time.sleep(5 * (attempt + 1))
                    continue
                raise WikiError("Wikipedia API error %s" % e.code)
            except (urllib.error.URLError, ConnectionError, TimeoutError, OSError) as e:
                if attempt < 3:  # dropped / reset connection: wait and retry
                    time.sleep(3 * (attempt + 1))
                    continue
                raise WikiError("Could not reach Wikipedia: %s" % getattr(e, "reason", e))
            if data.get("error", {}).get("code") == "maxlag" and attempt < 3:
                time.sleep(5)
                continue
            if "error" in data:
                raise WikiError("Wikipedia API: %s" % data["error"].get("info", data["error"]))
            return data
        raise WikiError("Wikipedia is busy, try again later")

    def _cache_file(self, title):
        safe = re.sub(r"[^\w\-]+", "_", title)[:150]
        return os.path.join(self.cache_dir, safe + ".json")

    def pages(self, titles, max_age_hours=24):
        """{requested title: wikitext or None}. Follows redirects; batches of 20; disk cache."""
        return {t: p["text"] for t, p in self.pages_full(titles, max_age_hours).items()}

    def pages_full(self, titles, max_age_hours=24):
        """{requested title: {"title": final title, "text": wikitext or None, "fragment": section or None}}.

        A redirect like "2026 X – Singles" -> "2026 X#Singles" keeps its section name in "fragment",
        so callers can read just that part of the page."""
        out, todo = {}, []
        for t in titles:
            f = self._cache_file(t)
            if os.path.exists(f) and time.time() - os.path.getmtime(f) < max_age_hours * 3600:
                with open(f, encoding="utf-8") as fh:
                    c = json.load(fh)
                out[t] = {"title": c.get("title", t), "text": c.get("text"), "fragment": c.get("fragment")}
            else:
                todo.append(t)
        for i in range(0, len(todo), 20):
            batch = todo[i:i + 20]
            data = self._get({"action": "query", "prop": "revisions", "rvprop": "content", "rvslots": "main",
                              "redirects": "1", "titles": "|".join(batch)})
            q = data.get("query", {})
            alias, frag = {}, {}
            for key in ("normalized", "redirects"):
                for r in q.get(key, []):
                    alias[r["from"]] = r["to"]
                    if r.get("tofragment"):
                        frag[r["from"]] = r["tofragment"]
            texts = {}
            for p in q.get("pages", []):
                revs = p.get("revisions")
                texts[p["title"]] = revs[0]["slots"]["main"]["content"] if revs else None
            for t in batch:
                final, fragment = t, None
                while final in alias:
                    fragment = frag.get(final, fragment)
                    final = alias[final]
                entry = {"title": final, "text": texts.get(final), "fragment": fragment}
                out[t] = entry
                with open(self._cache_file(t), "w", encoding="utf-8") as fh:
                    json.dump(entry, fh)
        return out


# --------------------------------------------------------------------------- player infobox
def _rank_and_date(value):
    """'No. 13 (22 August 2022)' -> (13, 20220822). Tolerates templates and refs."""
    v = re.sub(r"<ref[^>]*/>|<ref.*?</ref>", "", value or "", flags=re.S)
    m = re.search(r"No\.?\s*(\d+)", v) or re.search(r"\b(\d{1,4})\b", v)
    if not m:
        return None, None
    rank = int(m.group(1))
    d = None
    dm = re.search(r"(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})", v) or None
    if dm and dm.group(2)[:3].lower() in MON3:
        d = int(dm.group(3)) * 10000 + MON3[dm.group(2)[:3].lower()] * 100 + int(dm.group(1))
    else:
        dm = re.search(r"([A-Za-z]+)\s+(\d{1,2}),?\s+(\d{4})", v)
        if dm and dm.group(1)[:3].lower() in MON3:
            d = int(dm.group(3)) * 10000 + MON3[dm.group(1)[:3].lower()] * 100 + int(dm.group(2))
        else:
            dts = re.search(r"\{\{\s*(?:dts|start date|date)\s*\|\s*(\d{4})\s*\|\s*(\d{1,2})\s*\|\s*(\d{1,2})", v, re.I)
            if dts:
                d = int(dts.group(1)) * 10000 + int(dts.group(2)) * 100 + int(dts.group(3))
    return rank, d


def parse_infobox(text):
    """Current and career-high singles ranking from a player's page, or None if not a tennis bio."""
    if not text:
        return None
    mw = _mw()
    code = mw.parse(text)
    for tpl in code.filter_templates(recursive=False):
        if "tennis biography" not in str(tpl.name).lower():
            continue

        def field(*names):
            for n in names:
                if tpl.has(n):
                    return str(tpl.get(n).value).strip()
            return ""
        cur, cur_d = _rank_and_date(field("currentsinglesranking", "currentranking"))
        best, best_d = _rank_and_date(field("highestsinglesranking", "highestranking"))
        return {"rank": cur, "rank_date": cur_d, "best": best, "best_date": best_d}
    return None


def player_ranking(client, names, max_age_hours=24):
    """Find a player's Wikipedia page (trying each name, then 'Name (tennis)') and read the rankings."""
    candidates = []
    for n in names:
        for t in (n, "%s (tennis)" % n):
            if n and t not in candidates:
                candidates.append(t)
    texts = client.pages(candidates, max_age_hours=max_age_hours)
    for t in candidates:
        info = parse_infobox(texts.get(t))
        if info and (info["rank"] or info["best"]):
            info["title"] = t
            return info
    return None


def _ymd(d):
    s = str(d) if d else ""
    return "%s-%s-%s" % (s[:4], s[4:6], s[6:8]) if len(s) == 8 else None


def add_live_rankings(matchup, client, max_age_hours=24):
    """Overwrite dataset ranks in a Stats.matchup() result with Wikipedia's current ones, when found."""
    for p in matchup.get("players", []):
        if not p.get("match"):
            continue
        p["rank_source"], p["rank_date"] = "dataset", matchup.get("rankings_date")
        try:
            info = player_ranking(client, [p["name"], p.get("query")], max_age_hours=max_age_hours)
        except WikiError as e:
            matchup["live_error"] = str(e)
            continue
        if not info:
            continue
        if info["rank"]:
            p["rank"], p["points"] = info["rank"], None
            p["rank_date"], p["rank_source"] = _ymd(info["rank_date"]), "wikipedia"
        if info["best"] and (not p.get("career_high") or info["best"] <= p["career_high"]):
            p["career_high"] = info["best"]
            p["career_high_date"] = _ymd(info["best_date"]) or p.get("career_high_date")
        p["wiki_title"] = info["title"]
    return matchup


# --------------------------------------------------------------------------- season + draws
def season_draw_pages(client, tour, year, max_age_hours=24):
    """[(draw page title, approx date yyyymmdd, draw size or None)] in calendar order.

    Read from the "Schedule" section of the season article only (the intro and statistics
    sections link to the same draws with unrelated dates). Each schedule row has the week
    ("8 Jun") and the draw sizes ("28S/16Q/16D")."""
    title = "%d %s Tour" % (year, tour.upper())
    text = client.pages([title], max_age_hours=max_age_hours).get(title)
    if not text:
        raise WikiError("Couldn't read the Wikipedia page '%s'." % title)
    text = section_text(text, "Schedule") or text
    link = re.compile(r"\[\[(%d [^\[\]|]*? – (?:Men's |Women's )?[Ss]ingles)(?:\|[^\]]*)?\]\]" % year)
    month, row_day, out, seen = 1, None, [], set()
    for line in text.split("\n"):
        h = re.match(r"^=+\s*([A-Za-z]+)\s*=+\s*$", line.strip())
        if h and h.group(1).lower() in MONTHS:
            month, row_day = MONTHS[h.group(1).lower()], None
        # the "Week" cell starts a row: "|rowspan=4|8 Jun" (ATP) or '| rowspan="2" |Oct 12' (WTA)
        dm = re.match(r"^\|\s*(?:[^|\[\]{}]*\|)?\s*(?:(\d{1,2})\s+([A-Z][a-z]{2})|([A-Z][a-z]{2})[a-z]*\.?\s+(\d{1,2}))\b", line)
        if dm:
            mon = (dm.group(2) or dm.group(3)).lower()
            if mon in MON3:
                row_day = (MON3[mon], int(dm.group(1) or dm.group(4)))
        for m in link.finditer(line):
            t = m.group(1)
            if t in seen or "qualifying" in t.lower() or "wheelchair" in t.lower():
                continue
            seen.add(t)
            mon, day = row_day or (month, 1)
            y = year - 1 if mon == 12 and month == 1 else year  # season can start in late December
            size = re.findall(r"\b(\d{2,3})S\b", line[:m.start()])
            out.append((t, y * 10000 + mon * 100 + day, int(size[-1]) if size else None))
    return out


ROUND_CODES = [("semifinal", "SF"), ("semi-final", "SF"), ("quarterfinal", "QF"), ("quarter-final", "QF"), ("final", "F"), ("fourth round", "4R"),
               ("third round", "3R"), ("second round", "2R"), ("first round", "1R"), ("round of 16", "R16"),
               ("round of 32", "R32"), ("round of 64", "R64"), ("round of 128", "R128")]
ROUND_SORT = {"1R": 1, "R128": 1, "2R": 2, "R64": 2, "3R": 3, "R32": 3, "4R": 4, "R16": 4, "QF": 5, "SF": 6, "F": 7}


def _round_code(label):
    l = label.lower()
    for key, code in ROUND_CODES:
        if key in l:
            return code
    return label.strip()[:6] or "?"


def _player(cell):
    """'{{flagicon|POL}} '''[[Iga Świątek|I Świątek]]''' (Q)' -> ('Iga Świątek', bold?).

    A cell with two player links is a doubles team, which we don't want: returns (None, False)."""
    links = [l for l in re.findall(r"\[\[([^\]|#]+)", cell or "") if not re.match(r"(?i)(file|image):", l)]
    if len(links) != 1:
        return None, False
    m = re.search(r"\[\[([^\]|#]+)", cell)
    name = re.sub(r"\s*\((?:tennis|tennis player)\)$", "", m.group(1).strip())
    return name, "'''" in cell


def _games(cell):
    """'7<sup>5</sup>' -> (7, 5); '6' -> (6, None); retirement/walkover markers handled by caller."""
    c = re.sub(r"<ref.*?</ref>|<ref[^>]*/>", "", cell or "", flags=re.S)
    m = re.match(r"\s*(?:''')?\s*(\d+)\s*(?:''')?\s*(?:<sup>\s*(\d+)\s*</sup>)?", c)
    if not m:
        return None, None
    return int(m.group(1)), (int(m.group(2)) if m.group(2) else None)


def parse_draw(text, qualifying=False):
    """All singles results in the brackets of `text`: [{'round','winner','loser','score','stage'}].

    Qualifying brackets name their rounds "First round" ... "Qualifying competition", so with
    qualifying=True rounds are labelled by position instead: Q1, Q2, Q3."""
    mw = _mw()
    out = []
    for tpl in mw.parse(text or "").filter_templates():
        if "bracket" not in str(tpl.name).lower():
            continue
        params = {str(p.name).strip(): str(p.value).strip() for p in tpl.params}
        rounds = sorted({int(m.group(1)) for k in params for m in [re.match(r"RD(\d+)-team\d+$", k)] if m})
        for r in rounds:
            label = "Q%d" % r if qualifying else _round_code(params.get("RD%d" % r, "Round %d" % r))
            nums = sorted({int(m.group(1)) for k in params for m in [re.match(r"RD%d-team(\d+)$" % r, k)] if m})
            for a in nums:
                if a % 2 == 0 or a + 1 not in nums:
                    continue
                ka, kb = "RD%d-team%02d" % (r, a), "RD%d-team%02d" % (r, a + 1)
                if ka not in params:
                    ka, kb = "RD%d-team%d" % (r, a), "RD%d-team%d" % (r, a + 1)
                pa, bold_a = _player(params.get(ka))
                pb, bold_b = _player(params.get(kb))
                if not pa or not pb:
                    continue  # bye or empty slot
                fmt = "%02d" if ("RD%d-score%02d-1" % (r, a)) in params else "%d"

                def cells(n):
                    return [params.get(("RD%d-score" + fmt + "-%d") % (r, n, s), "") for s in range(1, 6)]
                ca, cb = cells(a), cells(a + 1)
                raw = " ".join(ca + cb).lower()
                walkover = "w/o" in raw or "walkover" in raw
                retired = bool(re.search(r"\br\b|ret|<sup>r</sup>|\(r\)", raw))
                sets, won_a, won_b = [], 0, 0
                for x, y in zip(ca, cb):
                    ga, ta = _games(x)
                    gb, tb = _games(y)
                    if ga is None or gb is None:
                        continue
                    sets.append((ga, gb, ta, tb))
                    won_a += ga > gb
                    won_b += gb > ga
                if bold_a != bold_b:
                    a_won = bold_a
                elif won_a != won_b and not retired and not walkover:
                    a_won = won_a > won_b
                else:
                    continue  # can't tell who advanced (unplayed or ambiguous)
                parts = []
                for ga, gb, ta, tb in sets:
                    w, l = (ga, gb) if a_won else (gb, ga)
                    tbs = [t for t in (ta, tb) if t is not None]
                    parts.append("%d-%d%s" % (w, l, "(%d)" % min(tbs) if tbs and {w, l} == {6, 7} else ""))
                score = "W/O" if walkover and not parts else " ".join(parts) + (" RET" if retired else "")
                winner, loser = (pa, pb) if a_won else (pb, pa)
                out.append({"round": label, "winner": winner, "loser": loser, "score": score.strip(),
                            "stage": "qualifying" if qualifying else "main"})
    # the "Finals" bracket repeats nothing, but split draws can list the same match twice; dedupe
    seen, unique = set(), []
    for m in out:
        k = (m["round"], m["winner"], m["loser"])
        if k not in seen:
            seen.add(k)
            unique.append(m)
    return unique


def tournament_name(draw_title):
    """'2026 Ningbo Open – Singles' -> 'Ningbo Open'."""
    t = re.sub(r"^\d{4}\s+", "", draw_title)
    return re.sub(r"\s+–\s+(?:Men's |Women's )?[Ss]ingles$", "", t)


def section_text(text, heading):
    """The part of a page under `heading` (including its subsections), or "" if there's no such heading."""
    want = normalize_heading(heading)
    lines, out, level = (text or "").split("\n"), [], None
    for line in lines:
        h = re.match(r"^(=+)\s*(.*?)\s*=+\s*$", line)
        if h:
            if level is not None and len(h.group(1)) <= level:
                break
            if level is None and normalize_heading(h.group(2)) == want:
                level = len(h.group(1))
                continue
        if level is not None:
            out.append(line)
    return "\n".join(out)


def without_sections(text, words):
    """Drop every section whose heading contains one of `words` (e.g. the qualifying draw)."""
    out, skip_level = [], None
    for line in (text or "").split("\n"):
        h = re.match(r"^(=+)\s*(.*?)\s*=+\s*$", line)
        if h:
            lvl = len(h.group(1))
            if skip_level is not None and lvl <= skip_level:
                skip_level = None
            if skip_level is None and any(w in normalize_heading(h.group(2)) for w in words):
                skip_level = lvl
                continue
        if skip_level is None:
            out.append(line)
    return "\n".join(out)


def only_sections(text, words):
    """Just the sections (with their subsections) whose heading contains one of `words`."""
    out, keep_level = [], None
    for line in (text or "").split("\n"):
        h = re.match(r"^(=+)\s*(.*?)\s*=+\s*$", line)
        if h:
            lvl = len(h.group(1))
            if keep_level is not None and lvl <= keep_level:
                keep_level = None
            if keep_level is None and any(w in normalize_heading(h.group(2)) for w in words):
                keep_level = lvl
        if keep_level is not None:
            out.append(line)
    return "\n".join(out)


def normalize_heading(h):
    return re.sub(r"[^a-z0-9]+", " ", re.sub(r"\[\[(?:[^|\]]*\|)?([^\]]*)\]\]", r"\1", h or "").lower()).strip()


def _linked_draw_pages(text, own_title):
    """Other pages a draw page pulls its brackets from: transclusions ({{:Page}}) and
    'main article' hatnotes pointing at singles draws (e.g. Grand Slam sections on sub-pages)."""
    mw = _mw()
    found = []
    for tpl in mw.parse(text or "").filter_templates(recursive=False):
        name = str(tpl.name).strip()
        if name.startswith(":"):
            found.append(name[1:].strip())
        elif name.lower() in ("main", "main article", "see also", "further", "details"):
            found += [str(p.value).strip() for p in tpl.params if not str(p.name).strip().startswith("l")]
    # plain links to this draw's own sub-pages, e.g. "[[2026 US Open – Women's singles (Section 1)|Section 1]]"
    for link in re.findall(r"\[\[([^\]|#]+)", text or ""):
        link = link.strip()
        if link.startswith(own_title) and link != own_title:
            found.append(link)
    return [t for t in dict.fromkeys(found) if t and t != own_title and "singles" in t.lower()
            and "doubles" not in t.lower() and "qualifying" not in t.lower()]


def collect_draw(client, title, max_age_hours=12, depth=2):
    """All singles results for one tournament, following redirects and sub-pages. Returns (matches, notes)."""
    notes = []
    p = client.pages_full([title], max_age_hours=max_age_hours).get(title) or {}
    text = p.get("text")
    if not text:
        return [], ["page missing"]
    if p.get("fragment"):
        part = section_text(text, p["fragment"])
        notes.append("redirects to %s#%s" % (p["title"], p["fragment"]))
        text = part or ""
    elif "singles" not in p.get("title", title).lower():
        # redirected to the tournament's main page: only read its Singles section, never the doubles
        notes.append("redirects to %s" % p.get("title"))
        text = section_text(text, "Singles")
    own = p.get("title", title)
    draw = section_text(text, "Draw")
    matches = parse_draw(without_sections(draw or text, ("qualif", "lucky loser")))
    # qualifying: sections on this page, or (Grand Slams) a separate "… qualifying" page
    quali = parse_draw(without_sections(only_sections(text, ("qualif",)), ("wild card",)), qualifying=True)
    q_page = own + " qualifying"
    if depth > 0 and not quali and q_page in text:  # linked or named in a "main article" note
        qp = client.pages_full([q_page], max_age_hours=max_age_hours).get(q_page) or {}
        quali = parse_draw(without_sections(qp.get("text") or "", ("wild card",)), qualifying=True)
        if quali:
            notes.append("qualifying from %s" % q_page)
    matches += quali
    if depth > 0:
        for sub in _linked_draw_pages(text, p.get("title", title)):
            more, _ = collect_draw(client, sub, max_age_hours, depth - 1)
            if more:
                notes.append("+%d from %s" % (sum(m["stage"] == "main" for m in more), sub))
                matches += more
    seen, unique = set(), []
    for m in matches:
        k = (m["round"], m["winner"], m["loser"])
        if k not in seen:
            seen.add(k)
            unique.append(m)
    return unique, notes


def coverage(matches, draw_size=None):
    """How complete a knockout draw looks: "complete", "partial" or "empty".

    With the draw size from the season page ("28S"), a full draw has exactly size-1 matches
    (byes are simply missing matches on both sides). Without it, fall back to structure checks:
    a final was played, every player but the champion lost once, and rounds add up."""
    if not matches:
        return "empty"
    has_final = any(m["round"] == "F" for m in matches)
    if draw_size and has_final and len(matches) >= draw_size - 1:
        return "complete"
    players = {m["winner"] for m in matches} | {m["loser"] for m in matches}
    if not has_final or len(matches) != len(players) - 1:
        return "partial"
    by_round = {}
    for m in matches:
        by_round.setdefault(ROUND_SORT.get(m["round"], 0), []).append(m)
    order = sorted(r for r in by_round if r)
    if len(order) >= 2 and len(by_round[order[0]]) < len(by_round[order[1]]):
        return "partial"
    for i in range(2, len(order)):
        winners_before = {m["winner"] for m in by_round[order[i - 1]]}
        for m in by_round[order[i]]:
            if m["winner"] not in winners_before or m["loser"] not in winners_before:
                return "partial"
    return "complete"


def recent_results(client, tour, since, today=None, log=print):
    """Results from every singles draw on Wikipedia with an approximate date >= since (yyyymmdd).

    Returns (results, report). The report lists every tournament with its match count and
    whether its draw looks complete, so gaps on Wikipedia are visible rather than silent."""
    today = today or date.today()
    today_i = int(today.strftime("%Y%m%d"))
    events = []
    for year in sorted({since // 10000, today.year}):
        events += [e for e in season_draw_pages(client, tour, year) if since <= e[1] <= today_i]
    log("  %d tournaments on Wikipedia since %s" % (len(events), str(since)))
    client.pages_full([e[0] for e in events], max_age_hours=12)  # one batched fetch; collect_draw reads the cache
    results, report = [], []
    for title, d, size in events:
        ms, notes = collect_draw(client, title)
        main = [m for m in ms if m["stage"] == "main"]
        n_q = len(ms) - len(main)
        status = coverage(main, size)
        finished = date.fromordinal(date(d // 10000, d // 100 % 100, d % 100).toordinal() + 14) < today
        if status == "partial" and not finished:
            status = "in progress"
        for m in ms:
            results.append(dict(m, date=d, tournament=tournament_name(title), source=title))
        report.append({"title": title, "date": d, "draw": size, "matches": len(main), "qualifying": n_q,
                       "status": status, "notes": notes})
        flag = {"complete": "", "in progress": "  (in progress)", "partial": "  ! some results missing",
                "empty": "  ! no draw found"}[status]
        of = "/%d" % (size - 1) if size else ""
        q = " +%d qualifying" % n_q if n_q else ""
        log("    %-50s %3d%s main%s%s%s" % (title[:50], len(main), of, q, flag, ("  [" + "; ".join(notes) + "]") if notes else ""))
    bad = [r for r in report if r["status"] in ("partial", "empty")]
    if bad:
        log("  %d of %d tournaments have gaps on Wikipedia (listed with '!' above)." % (len(bad), len(report)))
    return results, report
