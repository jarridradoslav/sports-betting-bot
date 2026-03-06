# odds_fetcher.py
# Pulls raw odds from The Odds API and normalises them into flat dicts
# ready for database insertion.

import logging
from typing import Optional

import requests

import config
from database import now_utc

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------- #
# API call                                                                     #
# --------------------------------------------------------------------------- #

def fetch_odds(sport: str) -> Optional[list[dict]]:
    """
    Call The Odds API for a single sport.

    Returns the parsed JSON list on success, None on any error.
    Remaining quota is logged for visibility.
    """
    url = f"{config.BASE_URL}/sports/{sport}/odds"
    params = {
        "apiKey":      config.API_KEY,
        "regions":     config.REGIONS,
        "markets":     config.MARKETS,
        "oddsFormat":  config.ODDS_FORMAT,
    }

    try:
        resp = requests.get(url, params=params, timeout=15)
        resp.raise_for_status()
    except requests.RequestException as exc:
        logger.error("API request failed for %s: %s", sport, exc)
        return None

    # Log remaining quota from response headers
    remaining = resp.headers.get("x-requests-remaining", "?")
    used      = resp.headers.get("x-requests-used",      "?")
    logger.info("[%s] quota used=%s remaining=%s", sport, used, remaining)

    return resp.json()


# --------------------------------------------------------------------------- #
# Normalise                                                                    #
# --------------------------------------------------------------------------- #

def flatten_events(sport: str, events: list[dict]) -> list[dict]:
    """
    Convert the nested API response into a flat list of row dicts,
    one row per (event × bookmaker × market × outcome).
    """
    rows: list[dict] = []
    ts = now_utc()

    for event in events:
        base = {
            "event_id":      event["id"],
            "sport":         sport,
            "home_team":     event.get("home_team", ""),
            "away_team":     event.get("away_team", ""),
            "commence_time": event.get("commence_time", ""),
            "timestamp":     ts,
        }

        for bookmaker in event.get("bookmakers", []):
            book_name = bookmaker["key"]

            for market in bookmaker.get("markets", []):
                market_key = market["key"]   # h2h | spreads | totals

                for outcome in market.get("outcomes", []):
                    rows.append({
                        **base,
                        "bookmaker": book_name,
                        "market":    market_key,
                        "outcome":   outcome["name"],
                        "odds":      outcome["price"],
                        "point":     outcome.get("point"),   # None for h2h
                    })

    return rows


# --------------------------------------------------------------------------- #
# Public entry point                                                           #
# --------------------------------------------------------------------------- #

def fetch_and_flatten(sport: str) -> list[dict]:
    """Fetch odds for one sport and return normalised rows."""
    raw = fetch_odds(sport)
    if raw is None:
        return []
    rows = flatten_events(sport, raw)
    logger.info("[%s] flattened %d rows from %d events",
                sport, len(rows), len(raw))
    return rows
