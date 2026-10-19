# 🎾 odds-server

**An odds observer for tennis fans.** It follows match odds across dozens of bookmakers, turns them into
win probabilities, and shows you where the market can't make up its mind.

![odds-server screenshot](docs/screenshot.png)

Ever wondered why one site has Sinner at 1.45 and another at 1.52? Or what "2.10" actually says about a
player's chances? odds-server answers those questions for every match in a tournament, using only
Python's standard library and a single HTML page.

---

## What you can do with it

- **See the market's view of a match.** Every bookmaker's price is converted into an implied win
  probability. Their built-in margins are removed and the results are averaged into one consensus
  number per player.
- **Compare prices side by side.** The best price for each player is highlighted across all bookmakers.
- **Spot disagreements.** When the best prices for the two players add up to less than 100%, the
  bookmakers disagree about the match, and the match is flagged as a *pricing gap*.
- **Load a whole tournament at once.** Pick an event (say, WTA Ningbo or an ATP Masters), and every match
  is listed and sorted by how much the bookmakers disagree.
- **Save up to 5 matches** you're following. They're stored in your browser.
- **Watch your API usage.** A built-in meter tracks your free monthly credits.
- **Use it from the terminal** with `scan.py`, if you prefer text output.

## The ideas behind it

### Odds are probabilities in disguise

Decimal odds tell you how many units come back per unit, so `2.50` returns 2.5×. Flip that around and you get
the implied probability:

```
p = 1 / odds          2.50  →  40.0%
```

### Bookmakers add a margin

A single bookmaker's two probabilities add up to more than 100%. At `1.90 / 1.90` you get 52.6% + 52.6% = 105.3%.
The extra 5.3% is the bookmaker's margin, also called the *overround*.

### Finding the "fair" probability

To remove the margin, rescale each bookmaker's pair so it sums to 100%, then average across all bookmakers:

```
fair_i = (1/odds_i) / (1/odds_1 + 1/odds_2)      averaged over bookmakers
```

This gives the **Market view**, the crowd's best guess at each player's chance.

### When the market disagrees

Take the *best* price for each player, even if they come from different bookmakers:

```
implied_total = 1/best_1 + 1/best_2
```

Normally this is still above 100%. When it drops below, bookmakers disagree enough to leave a **pricing gap** of
`1/implied_total − 1`. Example: `2.10` at one bookmaker and `2.05` at another give 47.6% + 48.8% = 96.4%, a 3.73% gap.

### Equal-return allocation

The page also shows how a total amount `T` would be spread across the two best prices so that it returns the same
whichever player wins:

```
amount_i = T × (1/best_i) / implied_total
```

With rounding switched on (for example to the nearest 10), each amount is tried rounded down and up, and the
combination with the best worst-case result is kept.

## Getting started

You'll need **Python 3.9+**. No packages to install and no virtual environment needed.

1. **Get a free API key** from [the-odds-api.com](https://the-odds-api.com). The free plan gives 500 credits a month.
2. **Add your key.** Copy `.env.example` to `.env` and fill in `ODDS_API_KEY=...`.
3. **Start it:**
   - **Windows:** double-click `start.bat`.
   - **macOS / Linux:** `python3 server.py`.

   Your browser opens at http://127.0.0.1:8765.

No key? Open `web/odds-server-offline.html` directly and type odds in by hand.

### Terminal version

```bash
python scan.py --list                 # tennis tournaments with odds right now (free)
python scan.py                        # every match in every active tournament
python scan.py -t tennis_wta_ningbo_open
```

### Run the tests

```bash
python -m unittest discover tests
```

The tests run against a small fake API server, so they never use your real credits.

## Settings (`.env`)

| Setting | Default | What it does |
|---|---|---|
| `ODDS_API_KEY` | (none) | Your key from the-odds-api.com |
| `ODDS_REGIONS` | `eu,uk` | Which bookmakers to include, by region: `uk`, `eu`, `us`, `au` (1 credit each per tournament load) |
| `CACHE_MINUTES` | `10` | How long downloaded odds are reused before spending credits again |
| `PORT` | `8765` | Local port for the web page |

## How it's built

```
browser (web/index.html)
   │  fetch /api/tournaments, /api/odds, /api/credits
   ▼
server.py                ── tiny local web server; keeps your API key off the page
   │
   ▼
odds_server/odds_api.py  ── The Odds API client: caching, error messages, credit tracking
   │
   ▼
odds_server/core.py      ── the maths: implied probability, best prices, gaps, allocation
```

```
odds_server/core.py           pure functions, fully unit-tested
odds_server/odds_api.py       API client
odds_server/env.py            tiny .env reader
server.py                     local web server
scan.py                       command-line version
web/index.html                the web page
web/odds-server-offline.html  same page, no server needed
tests/                        unit tests + a sample API response
```

## Good to know

- Odds move quickly, so a gap you see now may close a few minutes later. Free-plan data can also lag a little.
- Bookmakers handle a mid-match retirement differently, which matters when you compare their prices.
- Coverage depends on The Odds API. Grand Slams and the bigger ATP/WTA events are covered best.

## About

A personal project for exploring tennis odds, probability and how prices form in a market.
Not financial advice.
