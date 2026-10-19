"""Odds math for 2-way markets (tennis match winner): implied probability,
best prices across bookmakers, pricing gaps and equal-return allocations.

A "book" here is a dict: {"name": str, "odds": [player1_odds, player2_odds], "comm": percent}
Odds are decimal. Missing odds can be None.
"""


def effective(odds, comm=0.0):
    """Decimal odds after an exchange fee (percent) taken from net returns."""
    return 1 + (odds - 1) * (1 - (comm or 0) / 100)


def best_prices(books):
    """Best effective price for each player across all books.

    Returns a list of two entries (or None where no price exists):
    {"k": player_index, "book": name, "odds": raw_odds, "eff": effective_odds}
    """
    best = [None, None]
    for book in books:
        comm = book.get("comm") or 0
        for k in (0, 1):
            odds = book["odds"][k] if k < len(book["odds"]) else None
            if odds is None or odds <= 1:
                continue
            eff = effective(odds, comm)
            if eff <= 1:
                continue
            if best[k] is None or eff > best[k]["eff"]:
                best[k] = {"k": k, "book": book["name"], "odds": odds, "eff": eff}
    return best


def analyse(books):
    """Check whether the best prices form a pricing gap (combined implied probability < 100%).

    Returns {"best": [...], "ok": bool, "implied": float, "gap": bool, "margin": float}.
    `implied` is the sum of 1/odds (under 1.0 = pricing gap). `margin` is the equal-split
    return on the total amount (e.g. 0.037 = 3.7%), negative when there is no gap.
    """
    best = best_prices(books)
    if best[0] is None or best[1] is None:
        return {"best": best, "ok": False}
    implied = 1 / best[0]["eff"] + 1 / best[1]["eff"]
    return {
        "best": best,
        "ok": True,
        "implied": implied,
        "gap": implied < 1,
        "margin": 1 / implied - 1,
    }


def allocate(best, total, round_to=0):
    """Allocate `total` across the two best prices so both outcomes return the same.

    With rounding, each amount is tried rounded down and up, and the combination
    with the best worst-case yield is used.
    Returns (amounts, returns, worst_case_surplus).
    """
    import math
    from itertools import product

    implied = 1 / best[0]["eff"] + 1 / best[1]["eff"]
    raw = [total * (1 / leg["eff"]) / implied for leg in best]
    if round_to:
        options = []
        for x in raw:
            lo, hi = math.floor(x / round_to) * round_to, math.ceil(x / round_to) * round_to
            options.append([lo, hi] if lo > 0 and lo != hi else [hi])
    else:
        options = [[round(x, 2)] for x in raw]

    def worst_case_yield(amounts):
        spent = sum(amounts)
        return (min(a * leg["eff"] for a, leg in zip(amounts, best)) - spent) / spent

    amounts = list(max(product(*options), key=worst_case_yield))
    returns = [a * leg["eff"] for a, leg in zip(amounts, best)]
    return amounts, returns, min(returns) - sum(amounts)


def normalize_event(event, market="h2h"):
    """Turn one The Odds API event into {id, commence, players, books}.

    Player order follows the API's home_team / away_team. Books missing a price
    for either player are skipped.
    """
    players = [event.get("home_team"), event.get("away_team")]
    books = []
    for bm in event.get("bookmakers", []):
        mkt = next((m for m in bm.get("markets", []) if m.get("key") == market), None)
        if not mkt:
            continue
        prices = {o.get("name"): o.get("price") for o in mkt.get("outcomes", [])}
        odds = [prices.get(players[0]), prices.get(players[1])]
        if None in odds:
            continue
        books.append({
            "name": bm.get("title") or bm.get("key"),
            "key": bm.get("key"),
            "odds": [float(odds[0]), float(odds[1])],
            "comm": 0,
            "updated": mkt.get("last_update") or bm.get("last_update"),
        })
    return {
        "id": event.get("id"),
        "tournament": event.get("sport_title"),
        "commence": event.get("commence_time"),
        "players": players,
        "books": books,
    }


def summarise(match):
    """Add pricing analysis to a normalized match (JSON-friendly)."""
    a = analyse(match["books"])
    out = dict(match)
    out["analysis"] = {
        "ok": a["ok"],
        "gap": a.get("gap", False),
        "implied": a.get("implied"),
        "margin": a.get("margin"),
        "best": a["best"],
    }
    return out
