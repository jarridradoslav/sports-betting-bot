# odds_fetcher.py
# Pulls raw odds from OddsPapi and normalises them into flat dicts
# ready for database insertion.
#
# OddsPapi requires a multi-step flow:
#   1. GET /sports          → find sport IDs for NBA / NHL / NFL
#   2. GET /fixtures        → get upcoming games for each sport
#   3. GET /odds            → get bookmaker odds for each fixture

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

import requests

import config
from database import now_utc

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Shared session with auth param injected automatically
# ---------------------------------------------------------------------------

_session = requests.Session()
_session.params = {"apiKey": config.API_KEY, "oddsFormat": config.ODDS_FORMAT}  # type: ignore

# Market name normalisation — map OddsPapi market names → our internal names
MARKET_MAP = {
    "1x2":            "h2h",
    "moneyline":      "h2h",
    "home/away":      "h2h",
    "asian handicap": "spreads",
    "handicap":       "spreads",
    "spread":         "spreads",
    "over/under":     "totals",
    "totals":         "totals",
    "total goals":    "totals",
}


def _normalise_market(raw: str) -> Optional[str]:
    return MARKET_MAP.get(raw.lower().strip())


# ---------------------------------------------------------------------------
# Step 1 — fetch all sports and find IDs matching our config
# ---------------------------------------------------------------------------

def get_sport_ids() -> dict[str, int]:
    """
    Return {sport_label: sport_id} for every sport in config.SPORTS.
    Matches by checking if the config label appears in the API sport name.
    """
    url = f"{config.BASE_URL}/sports"
    try:
        resp = _session.get(url, timeout=15)
        resp.raise_for_status()
        sports_data = resp.json()
    except Exception as exc:
        logger.error("Failed to fetch sports list: %s", exc)
        return {}

    # sports_data may be a list or wrapped in a 'data' key
    if isinstance(sports_data, dict):
        sports_data = sports_data.get("data", sports_data.get("sports", []))

    result: dict[str, int] = {}
    for sport in sports_data:
        name = (sport.get("sportName") or sport.get("name") or "").lower()
        sid  = sport.get("sportId") or sport.get("id")
        if sid is None:
            continue
        for label in config.SPORTS:
            if label.lower() in name and label not in result:
                result[label] = int(sid)
                logger.info("Mapped '%s' → sport_id=%s (%s)", label, sid, name)

    return result


# ---------------------------------------------------------------------------
# Step 2 — fetch upcoming fixtures for a sport
# ---------------------------------------------------------------------------

def get_fixtures(sport_id: int) -> list[dict]:
    """Return upcoming fixtures for a sport ID (next 7 days)."""
    url = f"{config.BASE_URL}/fixtures"
    today     = datetime.now(timezone.utc).date()
    week_out  = today + timedelta(days=7)
    params = {
        "sportId":  sport_id,
        "fromDate": today.isoformat(),
        "toDate":   week_out.isoformat(),
        "statusId": 0,   # pending (not yet started)
    }
    try:
        resp = _session.get(url, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        logger.error("Failed to fetch fixtures for sport_id=%s: %s", sport_id, exc)
        return []

    if isinstance(data, dict):
        data = data.get("data", data.get("fixtures", []))

    logger.info("sport_id=%s → %d fixtures", sport_id, len(data))
    return data if isinstance(data, list) else []


# ---------------------------------------------------------------------------
# Step 3 — fetch odds for a single fixture
# ---------------------------------------------------------------------------

def get_odds(fixture_id: int | str) -> Optional[dict]:
    """Return raw odds payload for one fixture."""
    url = f"{config.BASE_URL}/odds"
    try:
        resp = _session.get(url, params={"fixtureId": fixture_id}, timeout=15)
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        logger.error("Failed to fetch odds for fixture_id=%s: %s", fixture_id, exc)
        return None

    if isinstance(data, dict) and "data" in data:
        return data["data"]
    return data


# ---------------------------------------------------------------------------
# Normalise one fixture's odds payload into flat row dicts
# ---------------------------------------------------------------------------

def _flatten_fixture_odds(sport_label: str, fixture: dict,
                           odds_payload: dict) -> list[dict]:
    """
    Convert a single fixture's odds payload into a flat list of row dicts.

    The OddsPapi response looks like:
    {
      "markets": {
        "moneyline": {
          "bookmakers": {
            "fanduel": {
              "outcomes": [
                {"name": "Home", "odds": -150},
                {"name": "Away", "odds": +130}
              ]
            }
          }
        }
      }
    }

    We log the raw payload on first call so the structure can be verified.
    """
    rows: list[dict] = []
    ts = now_utc()

    home = fixture.get("homeTeam") or fixture.get("home_team") or fixture.get("participants", [{}])[0].get("name", "Home")
    away = fixture.get("awayTeam") or fixture.get("away_team") or fixture.get("participants", [{}])[-1].get("name", "Away")
    fid  = str(fixture.get("fixtureId") or fixture.get("fixture_id") or fixture.get("id", ""))
    commence = fixture.get("startTime") or fixture.get("start_time") or fixture.get("commenceTime", "")

    base = {
        "event_id":      fid,
        "sport":         sport_label,
        "home_team":     home,
        "away_team":     away,
        "commence_time": commence,
        "timestamp":     ts,
    }

    markets = odds_payload.get("markets") or odds_payload.get("odds") or {}

    for market_raw, market_data in markets.items():
        market_key = _normalise_market(market_raw)
        if market_key is None:
            logger.debug("Skipping unknown market: %s", market_raw)
            continue

        # bookmakers can be a dict {book_slug: {outcomes: [...]}}
        # or a list [{bookmaker: slug, outcomes: [...]}]
        bookmakers = market_data.get("bookmakers") or market_data.get("books") or {}

        if isinstance(bookmakers, dict):
            books_iter = bookmakers.items()
        else:
            books_iter = ((b.get("bookmaker") or b.get("name"), b)
                          for b in bookmakers)

        for book_name, book_data in books_iter:
            if not book_name:
                continue
            outcomes = book_data.get("outcomes") or book_data.get("prices") or []
            for outcome in outcomes:
                name = outcome.get("name") or outcome.get("label") or ""
                odds = outcome.get("odds") or outcome.get("price")
                point = outcome.get("handicap") or outcome.get("point") or outcome.get("line")

                if odds is None:
                    continue

                rows.append({
                    **base,
                    "bookmaker": str(book_name),
                    "market":    market_key,
                    "outcome":   name,
                    "odds":      float(odds),
                    "point":     float(point) if point is not None else None,
                })

    return rows


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def fetch_and_flatten(sport_label: str, sport_id: int) -> list[dict]:
    """
    Full pipeline for one sport:
      fixtures → odds per fixture → flat rows
    """
    fixtures = get_fixtures(sport_id)
    if not fixtures:
        return []

    all_rows: list[dict] = []
    logged_sample = False

    for fixture in fixtures:
        fid = fixture.get("fixtureId") or fixture.get("fixture_id") or fixture.get("id")
        if fid is None:
            continue

        odds_payload = get_odds(fid)
        if not odds_payload:
            continue

        # Log the raw payload once per run to help debug response structure
        if not logged_sample:
            logger.debug("Sample odds payload for fixture %s: %s", fid, odds_payload)
            logged_sample = True

        rows = _flatten_fixture_odds(sport_label, fixture, odds_payload)
        all_rows.extend(rows)

    logger.info("[%s] fetched %d odds rows from %d fixtures",
                sport_label, len(all_rows), len(fixtures))
    return all_rows
