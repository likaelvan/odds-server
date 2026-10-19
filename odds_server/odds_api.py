"""Client for The Odds API v4 (https://the-odds-api.com), standard library only.

Credit cost: listing sports is free. Each odds request costs
(number of regions) x (number of markets) credits. We only use the "h2h"
(match winner) market, so one tournament in two regions = 2 credits.
Responses are cached on disk so reloading the page does not burn credits.

Credit usage is read from the response headers (x-requests-used / -remaining /
-last) and saved to .cache/credits.json with a short history of calls, so the
numbers survive restarts.
"""
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

from .core import normalize_event, summarise

BASE_URL = "https://api.the-odds-api.com/v4"


class OddsAPIError(Exception):
    pass


class OddsAPI:
    def __init__(self, api_key, cache_dir=".cache", cache_minutes=10, timeout=20):
        if not api_key:
            raise OddsAPIError("No API key. Put ODDS_API_KEY=your_key in the .env file.")
        self.api_key = api_key
        self.cache_dir = cache_dir
        self.cache_seconds = max(0, float(cache_minutes)) * 60
        self.timeout = timeout
        os.makedirs(cache_dir, exist_ok=True)
        self._credits_path = os.path.join(cache_dir, "credits.json")
        self._credits = self._load_credits()
        self._last_cost = None

    @property
    def remaining(self):
        return self._credits.get("remaining")

    @property
    def used(self):
        return self._credits.get("used")

    # -- HTTP -------------------------------------------------------------
    def _get(self, path, **params):
        params["apiKey"] = self.api_key
        url = BASE_URL + path + "?" + urllib.parse.urlencode(params)
        req = urllib.request.Request(url, headers={"User-Agent": "odds-server/1.0"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                self._read_credits(resp.headers)
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            self._read_credits(e.headers)
            try:
                detail = json.loads(e.read().decode("utf-8")).get("message", "")
            except Exception:
                detail = ""
            if e.code == 401:
                raise OddsAPIError("The API rejected your key (401). Check ODDS_API_KEY in .env. " + detail)
            if e.code == 429:
                raise OddsAPIError("Out of credits or too many requests (429). " + detail)
            raise OddsAPIError("API error %s. %s" % (e.code, detail))
        except urllib.error.URLError as e:
            raise OddsAPIError("Could not reach the API: %s" % e.reason)

    # -- Credits ----------------------------------------------------------
    def _load_credits(self):
        try:
            with open(self._credits_path, encoding="utf-8") as f:
                data = json.load(f)
            data.setdefault("log", [])
            return data
        except (OSError, ValueError):
            return {"used": None, "remaining": None, "updated": None, "log": []}

    def _save_credits(self):
        with open(self._credits_path, "w", encoding="utf-8") as f:
            json.dump(self._credits, f)

    def _read_credits(self, headers):
        if not headers:
            return
        rem, used, last = (headers.get("x-requests-remaining"), headers.get("x-requests-used"),
                           headers.get("x-requests-last"))
        if rem is None and used is None:
            return
        if rem is not None:
            self._credits["remaining"] = int(float(rem))
        if used is not None:
            self._credits["used"] = int(float(used))
        self._last_cost = int(float(last)) if last is not None else None
        self._credits["updated"] = time.time()
        self._save_credits()

    def _log_call(self, what, regions):
        cost = self._last_cost if self._last_cost is not None else len(regions.split(","))
        self._credits["log"] = ([{"t": time.time(), "what": what, "regions": regions, "cost": cost}]
                                + self._credits["log"])[:30]
        self._save_credits()

    def credit_status(self, regions="eu,uk"):
        """Summary for the UI: used, remaining, total, % left, loads left, recent calls."""
        used, rem = self._credits.get("used"), self._credits.get("remaining")
        total = used + rem if used is not None and rem is not None else None
        per_load = max(1, len(regions.split(",")))
        return {
            "known": total is not None,
            "used": used,
            "remaining": rem,
            "total": total,
            "pct_left": (rem / total) if total else None,
            "per_load": per_load,
            "loads_left": (rem // per_load) if rem is not None else None,
            "updated": self._credits.get("updated"),
            "log": self._credits["log"][:10],
        }

    def refresh_credits(self):
        """Update credit numbers with a free call (the sports list costs nothing)."""
        self._get("/sports")

    # -- Cache ------------------------------------------------------------
    def _cache_path(self, name):
        safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in name)
        return os.path.join(self.cache_dir, safe + ".json")

    def _cache_read(self, name):
        path = self._cache_path(name)
        if not os.path.exists(path):
            return None
        with open(path, encoding="utf-8") as f:
            return json.load(f)

    def _cache_write(self, name, payload):
        with open(self._cache_path(name), "w", encoding="utf-8") as f:
            json.dump(payload, f)

    # -- Public -----------------------------------------------------------
    def tennis_tournaments(self):
        """Active tennis tournaments (free call, no credits)."""
        sports = self._get("/sports")
        tours = [s for s in sports if s.get("group") == "Tennis" and s.get("active")]
        return [{"key": s["key"], "title": s.get("title", s["key"])} for s in tours]

    def tennis_odds(self, sport_key, regions="eu,uk", force=False):
        """Match-winner odds for one tournament, normalized and analysed.

        Returns {"sport", "regions", "fetched_at", "from_cache", "matches": [...]}.
        Uses the disk cache unless it is older than cache_minutes or force=True.
        """
        name = "%s__%s" % (sport_key, regions.replace(",", "-"))
        cached = self._cache_read(name)
        if cached and not force and time.time() - cached["fetched_at"] < self.cache_seconds:
            cached["from_cache"] = True
            return cached
        events = self._get(
            "/sports/%s/odds" % sport_key,
            regions=regions, markets="h2h", oddsFormat="decimal", dateFormat="iso",
        )
        self._log_call(sport_key, regions)
        matches = [summarise(normalize_event(ev)) for ev in events]
        matches = [m for m in matches if m["books"]]
        payload = {
            "sport": sport_key,
            "regions": regions,
            "fetched_at": time.time(),
            "from_cache": False,
            "matches": matches,
        }
        self._cache_write(name, payload)
        return payload
