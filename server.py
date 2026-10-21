"""odds-server local web app: serves the odds comparison page and proxies The Odds API.

Run:  py server.py        (then it opens http://127.0.0.1:8765 in your browser)
Your API key stays on your computer in .env; the page never sees it.
"""
import argparse
import json
import os
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from odds_server.env import load_env, setting
from odds_server.odds_api import OddsAPI, OddsAPIError
from odds_server.stats import Stats, StatsError
from odds_server.wiki import WikiClient, WikiError, add_live_rankings

ROOT = os.path.dirname(os.path.abspath(__file__))
WEB = os.path.join(ROOT, "web")
PAGES = {"/": "index.html", "/index.html": "index.html",
         "/offline.html": "odds-server-offline.html"}

load_env(os.path.join(ROOT, ".env"))
_api = None
_lock = threading.Lock()
_stats = {}  # tour -> (index mtime, Stats)
DATA = os.path.join(ROOT, ".data")
_wiki = WikiClient(os.path.join(ROOT, ".cache", "wiki"))
_wiki_lock = threading.Lock()


def get_stats(tour):
    """Load (or reload after update_stats.py) the player index for a tour."""
    path = os.path.join(DATA, "%s_index.json" % tour)
    if not os.path.exists(path):
        raise StatsError("No %s player data yet. Run: py update_stats.py" % tour.upper())
    mtime = os.path.getmtime(path)
    cached = _stats.get(tour)
    if not cached or cached[0] != mtime:
        _stats[tour] = (mtime, Stats(path))
    return _stats[tour][1]


def get_api():
    global _api
    if _api is None:
        _api = OddsAPI(setting("ODDS_API_KEY"), cache_dir=os.path.join(ROOT, ".cache"),
                       cache_minutes=setting("CACHE_MINUTES", "10"))
    return _api


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass  # keep the console quiet

    def _send(self, code, body, ctype="application/json; charset=utf-8"):
        data = body if isinstance(body, bytes) else json.dumps(body).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        url = urlparse(self.path)
        q = parse_qs(url.query)
        if url.path in PAGES:
            with open(os.path.join(WEB, PAGES[url.path]), "rb") as f:
                return self._send(200, f.read(), "text/html; charset=utf-8")
        try:
            if url.path == "/api/stats-status":
                out = {}
                for tour in ("atp", "wta"):
                    try:
                        with _lock:
                            st = get_stats(tour)
                        info = st.matchup("", "")
                        out[tour] = {"ready": True, "data_through": info["data_through"],
                                     "rankings_date": info["rankings_date"]}
                    except (StatsError, OSError, ValueError) as e:
                        out[tour] = {"ready": False, "error": str(e)}
                return self._send(200, out)
            if url.path == "/api/matchup":
                tour = (q.get("tour") or [""])[0].lower()
                if tour not in ("atp", "wta"):
                    return self._send(400, {"error": "Pick ATP or WTA."})
                p1, p2 = (q.get("p1") or [""])[0], (q.get("p2") or [""])[0]
                try:
                    with _lock:
                        out = get_stats(tour).matchup(p1, p2)
                except StatsError as e:
                    return self._send(404, {"error": str(e)})
                if setting("LIVE_RANKS", "1") != "0":
                    with _wiki_lock:  # current rank / career high from Wikipedia (cached for a day)
                        try:
                            add_live_rankings(out, _wiki)
                        except WikiError as e:
                            out["live_error"] = str(e)
                return self._send(200, out)
            regions = setting("ODDS_REGIONS", "eu,uk")
            if url.path == "/api/status":
                if not setting("ODDS_API_KEY"):
                    return self._send(200, {"key_set": False, "regions": regions})
                with _lock:
                    return self._send(200, {"key_set": True, "regions": regions,
                                            "credits": get_api().credit_status(regions)})
            if url.path == "/api/credits":
                with _lock:
                    api = get_api()
                    if (q.get("refresh") or ["0"])[0] == "1":
                        api.refresh_credits()
                    return self._send(200, {"credits": api.credit_status(regions)})
            if url.path == "/api/tournaments":
                with _lock:
                    api = get_api()
                    return self._send(200, {"tournaments": api.tennis_tournaments(),
                                            "credits": api.credit_status(regions)})
            if url.path == "/api/odds":
                sport = (q.get("sport") or [""])[0]
                if not sport:
                    return self._send(400, {"error": "Pick a tournament first."})
                force = (q.get("refresh") or ["0"])[0] == "1"
                with _lock:
                    api = get_api()
                    data = api.tennis_odds(sport, regions, force=force)
                    data = dict(data, credits=api.credit_status(regions))
                return self._send(200, data)
        except OddsAPIError as e:
            return self._send(502, {"error": str(e)})
        except Exception as e:  # unexpected: report instead of crashing
            return self._send(500, {"error": "Server error: %s" % e})
        self._send(404, {"error": "Not found"})


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--port", type=int, default=int(setting("PORT", "8765") or 8765))
    p.add_argument("--no-browser", action="store_true")
    args = p.parse_args()
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    url = "http://127.0.0.1:%d" % args.port
    print("odds-server running at %s  (press Ctrl+C to stop)" % url)
    if not setting("ODDS_API_KEY"):
        print("No API key yet: the calculator works, but API import is off. See README.md.")
    if not args.no_browser:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
